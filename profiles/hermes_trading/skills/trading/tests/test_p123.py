"""P1/P2/P3 aus der Nachpruefung vom 30.09.2026.

P1: Der Entry-Loop hielt die Positionslimits nur VOR dem Laden der Kandidaten ein. Im Loop galten 8 freie Plaetze
    (cfg max_positions) statt des Drawdown-Limits, und die Grenzen je Richtung (Regime) wurden nie mitgezaehlt.
P2: Die Positionsgroesse rechnete mit dem Sektor-Regime, der Anfangs-Stop (compute_sl_tp) mit dem Gesamtmarkt-Regime:
    das Ist-Risiko wich vom Zielrisiko (risk_pct_per_trade) ab. Jetzt nutzen Groesse, Stop, would_sl und Exit-Check
    das Sektor-Regime der Position (Fallback global).
P3: watchlist_dedup._ticker_priority stufte 5-Buchstaben-OTC-ADRs (DLAKY) als US-Primaerlisting ein und zog sie
    der Heimatboerse (LHA.DE) vor.
"""
import os
import sqlite3
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from scripts import signal_manager as sm          # noqa: E402
from scripts import watchlist_dedup as dedup      # noqa: E402
from tests.test_welle3 import make_db as make_wl_db, add_wl   # noqa: E402

PV = 9000.0
CHANNELS = '["kanal a", "kanal b"]'


def _db(cash=7400.0):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE watchlist (id INTEGER PRIMARY KEY, name TEXT, ticker TEXT, status TEXT,
                   conviction_score REAL, conviction_score_bear REAL, mention_count INTEGER, channels TEXT,
                   tech_score REAL, tech_direction TEXT, last_seen TEXT, notes TEXT)""")
    con.execute("CREATE TABLE companies (ticker TEXT PRIMARY KEY, sector TEXT, industry TEXT)")
    sm.init_db(con)
    cols = {r[1] for r in con.execute("PRAGMA table_info(positions)")}
    for col, typ in (("signal_source", "TEXT"), ("entry_conviction_score", "REAL"),
                     ("entry_conviction_tier", "TEXT"), ("asset_type", "TEXT"),
                     ("crabel_at_entry", "TEXT"), ("exit_mode", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE positions ADD COLUMN {col} {typ}")
    con.execute("DELETE FROM portfolio")
    con.execute("INSERT INTO portfolio (id, cash, total_value, ath_value) VALUES (1, ?, ?, ?)",
                (cash, PV, 11207.85))
    con.commit()
    return con


def _open_pos(con, ticker, direction="LONG", size=550.0):
    entry = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
    con.execute("INSERT INTO positions (ticker, name, direction, entry_price, entry_date, stop_loss, take_profit, "
                "trailing_sl, position_size, shares, status) VALUES (?,?,?,?,?,?,?,?,?,?,'open')",
                (ticker, ticker, direction, 100.0, entry, 90.0, 130.0, 90.0, size, size / 100.0))
    con.commit()


def _cand(con, ticker, direction, conv=0.7, conv_bear=0.1, tech=0.8, sector="Technology"):
    con.execute("INSERT INTO watchlist (name, ticker, status, conviction_score, conviction_score_bear, mention_count, "
                "channels, tech_score, tech_direction, last_seen) VALUES (?,?,'watching',?,?,5,?,?,?,?)",
                (f"{ticker} Corp", ticker, conv, conv_bear, CHANNELS, tech, direction,
                 datetime.now().strftime("%Y-%m-%d")))
    con.execute("INSERT OR REPLACE INTO companies (ticker, sector, industry) VALUES (?,?,NULL)", (ticker, sector))
    con.commit()


def _cfg(**kw):
    cfg = dict(sm.DEFAULT_CONFIG)
    cfg.update({
        "max_positions": 8, "yt_fade_enabled": False, "committee_enabled": False, "conviction_high": 0.99,
        "risk_pct_per_trade": 0.008, "max_position_pct": 0.125, "min_cash_reserve": 1500,
        "max_portfolio_allocation": 0.70, "max_long_allocation": 0.70, "max_short_allocation": 0.30,
        "min_conviction": 0.60, "min_mentions": 2, "min_confidence_short": 0.55, "min_mentions_short": 2,
        "min_distinct_channels": 1, "crabel_gate_mode": "off", "max_sector_exposure_pct": 0.95,
        "size_brake_floor": 0.4,
    })
    cfg.update(kw)
    return cfg


def _run(con, cfg, dd=(0.193, "ok", {"size_factor": 0.65, "min_confidence": 0.75, "max_positions": 6}),
         macro=("neutral", "sideways"), sector_regime="bull", global_regime="sideways", price=100.0, atr=2.0):
    patches = {
        "check_drawdown": mock.MagicMock(return_value=dd),
        "get_macro_signal": mock.MagicMock(return_value=macro),
        "update_sector_blacklist": mock.MagicMock(side_effect=lambda c, cfg_: cfg_),
        "get_current_price_and_atr": mock.MagicMock(return_value=(price, atr)),
        "sector_regime_key": mock.MagicMock(return_value="XLK"),
        "get_sector_regime": mock.MagicMock(
            side_effect=sector_regime if callable(sector_regime) else (lambda *a, **k: sector_regime)),
        "get_canonical_ticker": mock.MagicMock(side_effect=lambda c, t: t),
        "get_technical_score": mock.MagicMock(return_value={}),
        "passes_liquidity_filter": mock.MagicMock(return_value=True),
        "entry_gate_reason": mock.MagicMock(return_value=None),
        "check_short_thesis": mock.MagicMock(return_value=(2, ["a", "b"])),
        "is_sector_allowed": mock.MagicMock(return_value=(True, False, "")),
        "check_correlation_with_open": mock.MagicMock(return_value=(True, "")),
        "has_upcoming_earnings": mock.MagicMock(return_value=False),
        "is_macro_event_day": mock.MagicMock(return_value=False),
        "check_segment_performance": mock.MagicMock(return_value=(True, None)),
        "get_overnight_gap_inputs": mock.MagicMock(return_value=(None, None)),
        "get_crabel_patterns": mock.MagicMock(return_value=None),
        "vix_size_factor": mock.MagicMock(return_value=(1.0, 15.0)),
        "get_current_regime": mock.MagicMock(return_value=(global_regime, 15.0)),
        "price_to_eur": mock.MagicMock(side_effect=lambda p, t: p),
        "position_size_in_shares": mock.MagicMock(side_effect=lambda size, px, t: size / px),
        "open_positions_market_value_eur": mock.MagicMock(
            side_effect=lambda rows: sum(r["position_size"] for r in rows)),
        "send_telegram": mock.MagicMock(),
        "save_config": mock.MagicMock(),
        "log_blocked_entry": mock.MagicMock(),
    }
    with ExitStack() as stack:
        for name, m in patches.items():
            stack.enter_context(mock.patch.object(sm, name, m))
        sm.open_new_positions(con, cfg)


def _count(con, direction=None):
    sql = "SELECT COUNT(*) FROM positions WHERE status='open'" + (" AND direction=?" if direction else "")
    return con.execute(sql, (direction,) if direction else ()).fetchone()[0]


# ── P1 ──────────────────────────────────────────────────────────────────────────────────────
def test_p1_drawdown_limit_holds_within_one_run():
    con = _db()
    for t in ("OLD1", "OLD2", "OLD3"):
        _open_pos(con, t)
    for i in range(10):
        _cand(con, f"NEW{i}", "LONG")
    _run(con, _cfg())                     # Drawdown-Matrix: max. 6 Positionen
    assert _count(con) == 6               # vorher 8 (8 - 3 = 5 neue)


def test_p1_short_limit_of_the_regime_holds_within_one_run():
    con = _db()
    for i in range(6):
        _cand(con, f"SH{i}", "SHORT", conv=0.1, conv_bear=0.8, tech=0.3)
    _run(con, _cfg(), sector_regime="bear")   # seitwaerts: max. 3 SHORT
    assert _count(con, "SHORT") == 3          # vorher 4 (nur die Allokation bremste)


def test_p1_full_long_side_does_not_stop_the_short_side():
    con = _db()
    for i in range(5):
        _open_pos(con, f"OLD{i}", size=500.0)
    for i in range(4):
        _cand(con, f"L{i}", "LONG", conv=0.8, tech=0.9)
    for i in range(2):
        _cand(con, f"S{i}", "SHORT", conv=0.1, conv_bear=0.7, tech=0.4)
    _run(con, _cfg(), dd=(0.05, "ok", {"size_factor": 1.0, "min_confidence": 0.70, "max_positions": 8}),
         sector_regime="sideways")
    assert _count(con, "LONG") == 6           # seitwaerts: max. 6 LONG (vorher 8)
    assert _count(con, "SHORT") == 2          # die SHORTs kommen trotzdem noch dran


# ── P2 ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("direction", "sector_regime", "global_regime", "macro"), [
    ("SHORT", "bear", "sideways", ("neutral", "sideways")),
    ("LONG", "bull", "bear", ("neutral", "sideways")),
])
def test_p2_actual_risk_matches_the_risk_target(direction, sector_regime, global_regime, macro):
    con = _db()
    if direction == "LONG":
        _cand(con, "RISK", "LONG")
    else:
        _cand(con, "RISK", "SHORT", conv=0.1, conv_bear=0.8, tech=0.3)
    cfg = _cfg(risk_pct_per_trade=0.001)   # Risiko-Sizing bindet: 9 EUR Zielrisiko
    _run(con, cfg, dd=(0.05, "ok", {"size_factor": 1.0, "min_confidence": 0.70, "max_positions": 8}),
         macro=macro, sector_regime=sector_regime, global_regime=global_regime, atr=1.0)
    pos = con.execute("SELECT position_size, entry_price, stop_loss FROM positions WHERE ticker='RISK'").fetchone()
    assert pos is not None
    actual_risk = pos["position_size"] * abs(pos["stop_loss"] - pos["entry_price"]) / pos["entry_price"]
    target = PV * cfg["risk_pct_per_trade"]
    assert actual_risk == pytest.approx(target, rel=0.02)   # vorher 20-25 % daneben


@pytest.mark.parametrize(("direction", "sector_regime", "global_regime"), [
    ("SHORT", "bear", "sideways"),
    ("LONG", "sideways", "bear"),
])
def test_p2_initial_stop_follows_the_sector_regime_like_the_exit_check(direction, sector_regime, global_regime):
    """Der Exit-Check (check_open_positions/active_exit_check) nutzt seit 06.09. das Sektor-Regime der Position;
    der Anfangs-Stop muss dieselbe Matrix-Zelle treffen."""
    con = _db()
    if direction == "LONG":
        _cand(con, "RISK", "LONG")
    else:
        _cand(con, "RISK", "SHORT", conv=0.1, conv_bear=0.8, tech=0.3)
    _run(con, _cfg(), dd=(0.05, "ok", {"size_factor": 1.0, "min_confidence": 0.70, "max_positions": 8}),
         sector_regime=sector_regime, global_regime=global_regime, atr=1.0)
    pos = con.execute("SELECT entry_price, stop_loss FROM positions WHERE ticker='RISK'").fetchone()
    expected = sm.get_exit_config(asset_type="TECH", regime=sector_regime)["sl"]
    assert abs(pos["stop_loss"] - pos["entry_price"]) == pytest.approx(expected, abs=0.011)


def test_p2_would_sl_in_blocked_entries_uses_the_same_regime():
    con = _db()
    cand = {"name": "XTEST Corp", "tech_score": 0.3}
    with mock.patch.object(sm, "get_current_regime", return_value=("sideways", 15.0)):
        sm.log_blocked_entry(con, cand, "XTEST", "SHORT", "crabel", 100.0, 1.0, "Technology", 0.8,
                             None, None, sector_regime="bear")
    row = con.execute("SELECT would_entry, would_sl FROM blocked_entries WHERE ticker='XTEST'").fetchone()
    expected = sm.get_exit_config(asset_type="TECH", regime="bear")["sl"]
    assert abs(row["would_sl"] - row["would_entry"]) == pytest.approx(expected, abs=0.001)


# ── P3 ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("otc", ["DLAKY", "BAYRY", "NSRGF"])
def test_p3_otc_adr_ranks_behind_every_exchange_listing(otc):
    for listed in ("LHA.DE", "TSCO.L", "LHA.MU", "7203.T", "0700.HK"):
        assert dedup._ticker_priority(otc) > dedup._ticker_priority(listed), listed
    assert dedup._ticker_priority(otc) < dedup._ticker_priority("DE000A0XYZ123.SG")


@pytest.mark.parametrize("us", ["ING", "SAP", "GOOGL", "OMEGA", "ALPH", "NVDA"])
def test_p3_us_primary_listings_stay_first(us):
    assert dedup._ticker_priority(us) == 0


def test_p3_dedup_keeps_the_home_listing_instead_of_the_otc_adr():
    con = make_wl_db()
    add_wl(con, "Deutsche Lufthansa AG", "DLAKY", mentions=4)
    add_wl(con, "DEUTSCHE LUFTHANSA AG", "LHA.DE", mentions=9)
    dedup.dedup_by_name(con)
    live = con.execute("SELECT ticker FROM watchlist WHERE status IN ('watching','bought')").fetchall()
    assert [r["ticker"] for r in live] == ["LHA.DE"]      # vorher DLAKY
