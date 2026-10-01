"""Welle 5: M5 (Stop-Durchrutschen opt-in), N9 (Time-Stop-Deckel abschaltbar), N4 (ehrliche Meldung/Beschriftung)."""
import os
import sqlite3
from unittest import mock

import pandas as pd
import pytest

import exit_rules
from scripts import crabel_shadow_eval as cse
from scripts import signal_manager as sm
from tests.test_k3_teil_tp import Ticks, _cfg, _make_db, _open_long, _tick

ROOT = os.path.dirname(os.path.dirname(__file__))


# ── M5 ───────────────────────────────────────────────────────────────────────────────────────
def _bars(*rows):
    return [{"high": h, "low": l, "close": c} for h, l, c in rows]


def _replay(**kw):
    bars = _bars((100, 100, 100), (101, 95, 96))                    # zweite Kerze reißt durch den Stop (97)
    return exit_rules.replay_exit_path(bars, 0, 100.0, "LONG", 2.0, sl_mult=1.5, **kw)


def test_replay_default_fills_the_stop_exactly_like_before():
    r = _replay()
    assert r["reason"] == "SL_HIT" and r["r_multiple"] == pytest.approx(-1.0)


def test_replay_with_slippage_fills_below_the_stop():
    r = _replay(stop_slippage_atr=exit_rules.LIVE_STOP_SLIPPAGE_ATR)
    assert r["r_multiple"] == pytest.approx((97 - 0.35 * 2 - 100) / 3.0)         # -1,233 R statt -1,0 R


def test_replay_slippage_is_mirrored_for_shorts():
    bars = _bars((100, 100, 100), (105, 99, 104))
    r0 = exit_rules.replay_exit_path(bars, 0, 100.0, "SHORT", 2.0, sl_mult=1.5)
    r1 = exit_rules.replay_exit_path(bars, 0, 100.0, "SHORT", 2.0, sl_mult=1.5, stop_slippage_atr=0.35)
    assert r0["r_multiple"] == pytest.approx(-1.0) and r1["r_multiple"] < r0["r_multiple"]


def test_stop_fill_price_helper():
    assert exit_rules.stop_fill_price(97.0, 2.0, "LONG", 0.35) == pytest.approx(96.3)
    assert exit_rules.stop_fill_price(103.0, 2.0, "SHORT", 0.35) == pytest.approx(103.7)
    assert exit_rules.stop_fill_price(97.0, 2.0, "LONG") == 97.0


def _forward(slip):
    idx = pd.date_range("2026-09-24", periods=3, freq="D")
    df = pd.DataFrame({"High": [101, 100, 100], "Low": [99, 95, 99], "Close": [100, 96, 99]}, index=idx)
    return cse.simulate_forward(df, 100.0, 97.0, 110.0, 2.0, "LONG", "STANDARD", {}, "sideways",
                                stop_slippage_atr=slip)


def test_simulate_forward_default_is_unchanged_and_slippage_is_opt_in():
    assert _forward(0.0)[:2] == ("SL_HIT", 97.0)
    outcome, px, _ = _forward(0.35)
    assert outcome == "SL_HIT" and px == pytest.approx(96.3)


# ── N9 ───────────────────────────────────────────────────────────────────────────────────────
def _time_stop_exit_price(protected):
    con, ticks, cfg = _make_db(), Ticks(), _cfg()
    cfg["time_stop_protected_fill"] = protected
    _open_long(con, days_old=40)
    _tick(con, cfg, ticks, 90.0)                        # weit unter dem Anfangs-Stop (97)
    row = con.execute("SELECT exit_reason, exit_price FROM positions").fetchone()
    return row["exit_reason"], row["exit_price"]


def test_time_stop_default_still_caps_the_fill_at_the_initial_stop():
    sl = sm.get_exit_config(asset_type="STANDARD", regime="sideways")["sl"]
    assert _time_stop_exit_price(True) == ("TIME_STOP", pytest.approx(100.0 - 2.0 * sl, abs=0.01))


def test_time_stop_can_book_at_the_real_price():
    assert _time_stop_exit_price(False) == ("TIME_STOP", pytest.approx(90.0))


# ── N4 ───────────────────────────────────────────────────────────────────────────────────────
def _adapt(cfg_updates, regime):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, status TEXT, pnl_eur REAL)")
    for _ in range(4):
        con.execute("INSERT INTO positions (status, pnl_eur) VALUES ('closed', 10)")
    cfg = dict(sm.DEFAULT_CONFIG)
    cfg.update(cfg_updates)
    sent = []
    with mock.patch.object(sm, "get_current_regime", return_value=(regime, 15.0)), \
         mock.patch.object(sm, "get_exit_config", return_value={"sl": cfg["atr_sl_multiplier"], "tp": cfg["atr_tp_multiplier"]}), \
         mock.patch.object(sm, "send_telegram", side_effect=sent.append), \
         mock.patch.object(sm, "save_config"):
        sm.adapt_strategy(cfg, con)
    return "\n".join(sent)


def test_tp_message_says_lowered_when_the_cap_lowers_the_value():
    text = _adapt({"consecutive_wins": 3, "atr_tp_multiplier": 4.5}, "bull")
    assert "gesenkt" in text and "erhöht" not in text


def test_tp_message_says_raised_when_it_is_raised():
    text = _adapt({"consecutive_wins": 3, "atr_tp_multiplier": 3.0}, "bull")
    assert "erhöht auf 3.25" in text


def test_no_message_when_nothing_changes():
    assert _adapt({"consecutive_wins": 3, "atr_tp_multiplier": 3.5}, "bull") == ""


def test_sl_message_names_the_real_direction():
    assert "enger" in _adapt({"consecutive_losses": 3, "atr_sl_multiplier": 1.5}, "bull")
    assert "weiter" in _adapt({"consecutive_losses": 3, "atr_sl_multiplier": 1.0}, "bull")


def test_regime_probability_label_is_no_longer_called_next_week():
    src = open(os.path.join(ROOT, "scripts", "fundamental_data.py"), encoding="utf-8").read()
    assert "Nächste Woche:" not in src and "Folgetag" in src
