"""P5–P9 aus der Nachpruefung vom 30.09.2026.

P5 llm_validator: 19/19 UNCERTAIN — alte Kandidaten, Begruendungen nur unter dem exakten Namen, Screener-Zeilen ohne Meinung.
P6 Committee: Reasoning-Modelle liefen ins Token-Limit (leere/abgeschnittene Antwort) → 8/26 ERROR_FAIL_OPEN.
P7 nightly_eval: R-Multiple war Rendite je Position, Sortino mit sqrt(252) auf Trades, kein Drawdown vom ATH,
   Top-Band "WR 0 %" ohne geschlossene Trades.
P8 Sektor-Probation war unerreichbar: nach dem Cooldown wurde die Sperre komplett geloescht.
P9 source_lifecycle mischte 90-Tage-Win-Rate mit All-time-Durchschnitt; eine Quelle auf 0,3 kam nie wieder hoch.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from scripts import llm_validator as lv            # noqa: E402
from scripts import nightly_eval as ne             # noqa: E402
from scripts import signal_manager as sm           # noqa: E402
from scripts import source_lifecycle as sl         # noqa: E402
from roles import committee                        # noqa: E402
from thematic.lib import llm_client                # noqa: E402

TODAY = datetime.now()


def _d(days_ago):
    return (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")


# ── P5 ──────────────────────────────────────────────────────────────────────────────────────
def _lv_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE watchlist (id INTEGER PRIMARY KEY, name TEXT, ticker TEXT, status TEXT,
        conviction_score REAL, mention_count INTEGER, bullish_count INTEGER, bearish_count INTEGER, channels TEXT,
        tech_score REAL, tech_direction TEXT, last_seen TEXT, llm_verdict TEXT, llm_verdict_at TEXT)""")
    con.execute("""CREATE TABLE watchlist_mentions (id INTEGER PRIMARY KEY, name TEXT, channel TEXT, video_id TEXT,
        video_title TEXT, sentiment TEXT, reason TEXT, mention_date TEXT, strength TEXT)""")
    con.execute("CREATE TABLE company_aliases (alias TEXT PRIMARY KEY, ticker TEXT)")
    return con


def _wl(con, name, ticker, last_seen, conv=0.8, tech=0.7):
    con.execute("INSERT INTO watchlist (name, ticker, status, conviction_score, mention_count, bullish_count, "
                "bearish_count, channels, tech_score, tech_direction, last_seen) "
                "VALUES (?,?,'watching',?,5,4,1,'[]',?,'LONG',?)", (name, ticker, conv, tech, last_seen))


def _m(con, name, channel, reason, days_ago=2):
    con.execute("INSERT INTO watchlist_mentions (name, channel, reason, mention_date, sentiment) "
                "VALUES (?,?,?,?,'bullish')", (name, channel, reason, _d(days_ago)))


def test_p5_reasons_are_found_under_name_variants_ticker_and_aliases():
    con = _lv_db()
    con.execute("INSERT INTO company_aliases VALUES ('lufthansa', 'LHA.DE')")
    _m(con, "Deutsche Lufthansa", "aktien mit kopf", "Streik belastet, Prognose gesenkt")
    _m(con, "Lufthansa", "der aktionaer", "Kursziel 9 EUR bestaetigt")
    _m(con, "Lufthansa Technik", "rss:x", "anderes Unternehmen", days_ago=1)
    _m(con, "Deutsche Lufthansa", "der aktionaer", "zu alt", days_ago=45)
    got = lv.collect_reasons(con, "Deutsche Lufthansa AG", "LHA.DE")
    texts = [r for _, r in got]
    assert "Streik belastet, Prognose gesenkt" in texts and "Kursziel 9 EUR bestaetigt" in texts
    assert "zu alt" not in texts and "anderes Unternehmen" not in texts


def test_p5_only_fresh_candidates_with_an_opinion_reach_the_llm():
    con = _lv_db()
    _wl(con, "Alt AG", "ALT", "20260607")                         # Kompaktdatum, Monate alt
    _wl(con, "Screener Inc.", "SCR", _d(1))                        # nur Screener-Zeile
    _wl(con, "Advanced Micro Devices, Inc.", "AMD", _d(1))
    _m(con, "Screener Inc.", "screener_nasdaq", "Tech LONG conf=0.80; 1% unter 52W-Hoch")
    _m(con, "AMD", "ohne aktien wird schwer", "KI-Nachfrage, Kursziel angehoben")
    _m(con, "Advanced Micro Devices", "der aktionaer", "strammer Marsch Richtung Kursziel")
    calls = []

    def fake_validate(name, ticker, sentiment, mentions, reasons, tech=None):
        calls.append((ticker, reasons))
        return "CONFIRMED", "passt"

    stats = lv.run(con, validate=fake_validate)
    assert [t for t, _ in calls] == ["AMD"]
    assert any("KI-Nachfrage" in r for r in calls[0][1]) and any("der aktionaer" in r for r in calls[0][1])
    assert stats == {"CONFIRMED": 1, "CONTRADICTED": 0, "UNCERTAIN": 0, "SKIPPED": 1}
    scr = con.execute("SELECT conviction_score, llm_verdict FROM watchlist WHERE ticker='SCR'").fetchone()
    assert scr["conviction_score"] == 0.8 and scr["llm_verdict"].startswith("SKIPPED")
    alt = con.execute("SELECT llm_verdict FROM watchlist WHERE ticker='ALT'").fetchone()
    assert alt["llm_verdict"] is None


def test_p5_prompt_contains_reasons_tech_and_the_decision_rules():
    seen = {}

    class R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"verdict": "CONTRADICTED", "reason": "x"}'}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(json)
        return R()

    with mock.patch.object(lv, "OPENROUTER_KEY", "k"), mock.patch.object(lv.requests, "post", fake_post):
        verdict, _ = lv.validate_signal("AMD", "AMD", "bullish", 5, ["[der aktionaer] Kursziel angehoben"],
                                        tech=("LONG", 0.75))
    prompt = seen["messages"][0]["content"]
    assert verdict == "CONTRADICTED"
    assert "[der aktionaer] Kursziel angehoben" in prompt and "0.75" in prompt and "UNCERTAIN" in prompt
    assert seen["reasoning"] == {"enabled": False}


# ── P6 ──────────────────────────────────────────────────────────────────────────────────────
def test_p6_llm_client_passes_the_reasoning_switch():
    seen = {}

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(json)
        return R()

    with mock.patch.object(llm_client, "OPENROUTER_KEY", "k"), mock.patch.object(llm_client.requests, "post", fake_post):
        llm_client.call_llm("p", "deepseek/deepseek-v4-pro", json_mode=True, reasoning={"enabled": False})
    assert seen["reasoning"] == {"enabled": False}


def test_p6_committee_roles_run_without_reasoning_with_headroom_and_one_retry():
    answers = [{"ok": False, "error": "leere Antwort (finish_reason=length)", "tokens": {"input": 10, "output": 0}},
               {"ok": True, "content": '{"thesis": "gut"}', "tokens": {"input": 10, "output": 50}}]
    kwargs_seen = []

    def fake_call(prompt, model, **kw):
        kwargs_seen.append(kw)
        return answers.pop(0)

    acc = {"tokens_in": 0, "tokens_out": 0, "models": []}
    with mock.patch.object(committee.llm_client, "call_llm", side_effect=fake_call), \
         mock.patch.object(committee.llm_client, "get_model", return_value="deepseek/deepseek-v4-pro"), \
         mock.patch.object(committee.budget, "record_spend") as spend:
        data, ok = committee._call_role(None, "2026-09-30", "prompt", "committee_bull", acc)
    assert ok and data == {"thesis": "gut"}
    assert len(kwargs_seen) == 2 and spend.call_count == 2
    assert all(kw.get("reasoning") == {"enabled": False} for kw in kwargs_seen)
    assert kwargs_seen[0]["max_tokens"] >= 2500


# ── P7 ──────────────────────────────────────────────────────────────────────────────────────
def _ne_db(total=9048.86, ath=11207.85):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE positions (id INTEGER PRIMARY KEY, ticker TEXT, direction TEXT, status TEXT,
        entry_price REAL, entry_date TEXT, exit_date TEXT, exit_reason TEXT, pnl_eur REAL, pnl_pct REAL,
        position_size REAL, partial_size_eur REAL DEFAULT 0, initial_stop_loss REAL)""")
    con.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, cash REAL, total_value REAL, ath_value REAL)")
    con.execute("INSERT INTO portfolio VALUES (1, 7000, ?, ?)", (total, ath))
    return con


def _closed(con, pnl_eur, pnl_pct, size=1000.0, entry=100.0, isl=None, days_ago=3, partial=0.0):
    con.execute("INSERT INTO positions (ticker, direction, status, entry_price, entry_date, exit_date, exit_reason, "
                "pnl_eur, pnl_pct, position_size, partial_size_eur, initial_stop_loss) "
                "VALUES ('X','LONG','closed',?,?,?,'SL_HIT',?,?,?,?,?)",
                (entry, _d(days_ago + 5), _d(days_ago), pnl_eur, pnl_pct, size, partial, isl))


def test_p7_r_multiple_uses_the_initial_stop_and_the_full_position():
    con = _ne_db()
    _closed(con, 100.0, 10.0, isl=95.0)                 # Risiko 1000 x 5 % = 50 EUR -> +2,0 R
    _closed(con, -30.0, -3.0, size=500.0, partial=500.0, isl=90.0)   # Risiko 1000 x 10 % = 100 EUR -> -0,3 R
    _closed(con, 40.0, 4.0)                              # Alt-Trade ohne Anfangs-Stop: zaehlt fuer R nicht
    pm = ne.calc_portfolio_metrics(con)
    assert pm["avg_r_multiple"] == pytest.approx((2.0 - 0.3) / 2, abs=0.01)
    assert pm["avg_return_pct"] == pytest.approx((10.0 - 3.0 + 4.0) / 3, abs=0.01)


def test_p7_without_initial_stops_there_is_no_r_multiple():
    con = _ne_db()
    _closed(con, 40.0, 4.0)
    assert ne.calc_portfolio_metrics(con)["avg_r_multiple"] is None


def test_p7_drawdown_from_ath_and_per_trade_sortino():
    con = _ne_db(total=9048.86, ath=11207.85)
    _closed(con, 100.0, 10.0, days_ago=3)
    _closed(con, -50.0, -5.0, days_ago=2)
    pm = ne.calc_portfolio_metrics(con)
    assert pm["dd_from_ath_pct"] == pytest.approx(19.26, abs=0.01)
    base = 9048.86
    r = [100 / base * 100, -50 / base * 100]
    avg = sum(r) / 2
    dstd = (r[1] ** 2 / 2) ** 0.5
    assert pm["sortino_30d"] == pytest.approx(avg / dstd, abs=0.01)     # vorher x sqrt(252)


def test_p7_new_metrics_are_stored():
    con = _ne_db()
    con.execute("""CREATE TABLE eval_metrics (date TEXT, metric_type TEXT, new_companies INTEGER, confirmed INTEGER,
        contradicted INTEGER, avg_conviction REAL, signals_bought INTEGER, open_positions INTEGER, win_rate_7d REAL,
        win_rate_30d REAL, profit_factor_7d REAL, avg_holding_days REAL, exit_sl_pct REAL, exit_tp_pct REAL,
        exit_tech_pct REAL, created_at TEXT, notes TEXT, PRIMARY KEY (date, metric_type))""")
    _closed(con, 40.0, 4.0)
    pm = ne.calc_portfolio_metrics(con)
    smx = {"new_companies": 0, "confirmed": 0, "contradicted": 0, "avg_conviction": 0, "signals_bought": 0}
    ne.store_eval_metrics(con, "2026-09-30", "daily", smx, pm, "done")
    row = con.execute("SELECT avg_r_multiple, avg_return_pct, dd_from_ath_pct FROM eval_metrics").fetchone()
    assert row["avg_r_multiple"] is None and row["avg_return_pct"] == pytest.approx(4.0)
    assert row["dd_from_ath_pct"] == pytest.approx(19.26, abs=0.01)


def test_p7_top_band_has_no_win_rate_without_closed_trades():
    con = _ne_db()
    con.execute("CREATE TABLE watchlist (ticker TEXT, name TEXT, conviction_score REAL, status TEXT)")
    con.execute("INSERT INTO watchlist VALUES ('OPN', 'Offen AG', 0.9, 'bought')")
    con.execute("INSERT INTO positions (ticker, direction, status, entry_price, entry_date, position_size) "
                "VALUES ('OPN', 'LONG', 'open', 10, ?, 500)", (_d(1),))
    tb = ne.calc_top_band_metrics(con)
    assert tb["top3_bought"] == 1 and tb["top3_win_rate"] is None     # vorher 0 (= "WR 0 %")


def test_p7_entry_stores_the_initial_stop():
    from tests.test_p123 import _db, _cand, _run, _cfg
    con = _db()
    _cand(con, "INI", "LONG")
    _run(con, _cfg(), dd=(0.05, "ok", {"size_factor": 1.0, "min_confidence": 0.70, "max_positions": 8}))
    pos = con.execute("SELECT stop_loss, initial_stop_loss FROM positions WHERE ticker='INI'").fetchone()
    assert pos["initial_stop_loss"] is not None and pos["initial_stop_loss"] == pos["stop_loss"]


# ── P8 ──────────────────────────────────────────────────────────────────────────────────────
def _sector_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE companies (ticker TEXT PRIMARY KEY, sector TEXT, industry TEXT)")
    con.execute("CREATE TABLE watchlist (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT, conviction_score REAL)")
    sm.init_db(con)
    sm._ensure_sector_table(con)
    return con


def test_p8_after_the_cooldown_the_sector_is_offered_a_probation_trade_instead_of_full_release():
    con, cfg = _sector_db(), {"sector_cooldown_days": 14, "sector_probation_size_pct": 0.5}
    con.execute("INSERT INTO sector_blacklist (sector, blocked_at, cooldown_days) VALUES ('Industrials', ?, 14)",
                (_d(20),))
    con.commit()
    sm.update_sector_blacklist(con, cfg)                       # Fenster leer: vorher Zeile geloescht
    assert con.execute("SELECT COUNT(*) FROM sector_blacklist WHERE sector='Industrials'").fetchone()[0] == 1
    ok, probation, _ = sm.is_sector_allowed("Industrials", con, cfg)
    assert ok is True and probation is True


def test_p8_a_won_probation_trade_releases_the_sector():
    con, cfg = _sector_db(), {"sector_cooldown_days": 14, "sector_reentry_threshold_pnl": 0}
    con.execute("INSERT INTO sector_blacklist (sector, blocked_at, cooldown_days) VALUES ('Industrials', ?, 14)",
                (_d(20),))
    cur = con.execute("INSERT INTO positions (ticker, direction, status, pnl_eur, position_size) "
                      "VALUES ('GE', 'LONG', 'closed', 25.0, 300)")
    sm.mark_probation_started(con, "Industrials", "GE", cur.lastrowid)
    sm.update_sector_blacklist(con, cfg)                       # Probation laeuft: Zeile bleibt
    ok, probation, why = sm.is_sector_allowed("Industrials", con, cfg)
    assert ok is True and probation is False and "bestanden" in why
    assert con.execute("SELECT COUNT(*) FROM sector_blacklist").fetchone()[0] == 0


# ── P9 ──────────────────────────────────────────────────────────────────────────────────────
from tests.test_m8_lifecycle import make_db as _sl_db, add_source, add_trades, state   # noqa: E402


def _sl_run(con):
    sl.evaluate_active_sources(con)
    sl.demote_bad_sources(con)
    sl.adjust_weights(con)
    con.commit()


def test_p9_old_losses_outside_ninety_days_no_longer_penalize():
    con = _sl_db()
    add_source(con, "Erholt")
    add_trades(con, "Erholt", [(-90, -12.0)] * 4, days_ago=150)      # alte Verluste
    add_trades(con, "Erholt", [(30, 4.0), (25, 3.5), (-10, -1.4), (20, 2.8)], days_ago=10)
    _sl_run(con)
    r = con.execute("SELECT avg_pnl_pct, trades_90d FROM source_registry").fetchone()
    assert r["trades_90d"] == 4 and r["avg_pnl_pct"] == pytest.approx((4.0 + 3.5 - 1.4 + 2.8) / 4, abs=0.01)
    assert state(con, "Erholt")[1] >= 1.0                              # vorher 0,3 (All-time -4,8 %)


def test_p9_too_few_recent_trades_do_not_trigger_the_average_rule():
    con = _sl_db()
    add_source(con, "Selten")
    add_trades(con, "Selten", [(5, 0.7)] * 3, days_ago=150)          # alte kleine Gewinner
    add_trades(con, "Selten", [(-80, -11.0), (-70, -10.0)], days_ago=5)
    _sl_run(con)
    assert state(con, "Selten")[1] == 1.0                             # vorher 0,3 (All-time -3,8 %)


def test_p9_a_penalized_source_with_good_recent_results_recovers_step_by_step():
    con = _sl_db()
    sid = add_source(con, "Comeback")
    con.execute("UPDATE source_registry SET weight=0.3 WHERE id=?", (sid,))
    add_trades(con, "Comeback", [(15, 2.1), (-5, -0.7), (12, 1.7), (8, 1.1)], days_ago=10)
    _sl_run(con)
    w1 = state(con, "Comeback")[1]
    assert 0.3 < w1 < 1.0
    for _ in range(10):
        _sl_run(con)
    assert state(con, "Comeback")[1] == 1.0


def test_p9_a_source_that_still_fails_the_rules_stays_penalized():
    con = _sl_db()
    sid = add_source(con, "Dauerverlierer")
    con.execute("UPDATE source_registry SET weight=0.3 WHERE id=?", (sid,))
    add_trades(con, "Dauerverlierer", [(-60, -8.5), (10, 1.4), (-50, -7.1), (-40, -5.7)], days_ago=10)
    _sl_run(con)
    assert state(con, "Dauerverlierer")[1] == sl.THRESHOLDS["penalize_min_weight"]
