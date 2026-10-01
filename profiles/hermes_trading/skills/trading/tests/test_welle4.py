"""Welle 4 (Code-Pruefung 30.09.2026): M1 VIX-Halbierung, M2 Overnight-Gap, M3 SHORT-Thesis, M4 Conviction beim Entry."""
import ast
import os
import sqlite3
import types
from datetime import datetime, timedelta

import pandas as pd
import pytest

from scripts import signal_manager as sm

SRC_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "signal_manager.py")


def mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    return con


# ── M1 ──────────────────────────────────────────────────────────────────────────────────────
def _vix_db(regime_vix=None, macro_vix=None):
    con = mem()
    con.execute("CREATE TABLE regime_history (date TEXT, regime TEXT, vix REAL)")
    con.execute("CREATE TABLE macro_data (id INTEGER PRIMARY KEY, indicator TEXT NOT NULL, value REAL, date TEXT, "
                "fetched_at TEXT, signal TEXT, description TEXT)")
    if regime_vix is not None:
        con.execute("INSERT INTO regime_history VALUES ('2026-09-30','sideways',?)", (regime_vix,))
    if macro_vix is not None:
        con.execute("INSERT INTO macro_data (indicator, value, date) VALUES ('VIXCLS', ?, '2026-09-28')", (macro_vix,))
    con.commit()
    return con


@pytest.mark.parametrize(("regime", "macro", "expected"), [
    (35.0, None, 0.5), (16.0, None, 1.0), (30.0, None, 1.0), (None, 42.0, 0.5), (None, 15.0, 1.0), (None, None, 1.0),
])
def test_vix_halves_the_position_size_above_30(regime, macro, expected):
    factor, _vix = sm.vix_size_factor(_vix_db(regime, macro))
    assert factor == expected


def test_regime_history_wins_over_the_older_macro_value():
    assert sm.get_current_vix(_vix_db(regime_vix=16.0, macro_vix=45.0)) == 16.0


def test_a_broken_query_is_logged_not_swallowed_silently(caplog):
    con = mem()                                        # keine Tabellen
    with caplog.at_level("WARNING"):
        assert sm.get_current_vix(con) is None
    assert "VIX-Abfrage fehlgeschlagen" in caplog.text


def test_source_no_longer_uses_the_missing_column():
    assert "WHERE indicator_id" not in open(SRC_PATH, encoding="utf-8").read()


def test_vix_sql_is_valid_against_the_snapshot_schema():
    try:
        from config import DB_PATH
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        con.execute("SELECT 1 FROM macro_data LIMIT 1")
    except Exception as e:
        pytest.skip(f"kein Snapshot: {e}")
    assert sm.get_current_vix(con) is not None


# ── M3 ──────────────────────────────────────────────────────────────────────────────────────
def _fund_db(pe=30.0, median=20.0, days_old=1):
    con = mem()
    con.execute("""CREATE TABLE fundamentals_snapshot (date DATE NOT NULL, ticker TEXT NOT NULL, market_cap_eur REAL,
        pe_ttm REAL, pe_forward REAL, pe_sector_median REAL, fcf_yield REAL, revenue_growth_yoy REAL,
        short_interest_pct REAL, analyst_count INTEGER, debt_to_equity REAL, roic REAL, next_earnings_date DATE,
        flags_json TEXT, PRIMARY KEY (date, ticker))""")
    con.execute("CREATE TABLE watchlist (ticker TEXT, status TEXT, tech_direction TEXT, tech_score REAL)")
    d = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d")
    con.execute("INSERT INTO fundamentals_snapshot (date, ticker, pe_ttm, pe_sector_median) VALUES (?,?,?,?)",
                (d, "XYZ", pe, median))
    con.commit()
    return con


CFG = {"min_confidence_short": 0.65}


def test_short_thesis_valuation_criterion_scores_with_fresh_data():
    score, reasons = sm.check_short_thesis(_fund_db(30.0, 20.0, 1), "XYZ", 0.5, CFG)
    assert score == 1 and "P/E" in reasons[0]


def test_short_thesis_valuation_criterion_needs_a_real_premium():
    assert sm.check_short_thesis(_fund_db(21.0, 20.0, 1), "XYZ", 0.5, CFG) == (0, [])


def test_short_thesis_valuation_criterion_is_suspended_for_stale_snapshots(caplog):
    with caplog.at_level("INFO"):
        assert sm.check_short_thesis(_fund_db(30.0, 20.0, 60), "XYZ", 0.5, CFG) == (0, [])
    assert "ausgesetzt" in caplog.text


def test_short_thesis_without_the_table_does_not_crash():
    assert sm.check_short_thesis(mem(), "XYZ", 0.5, CFG) == (0, [])


# ── M2 ──────────────────────────────────────────────────────────────────────────────────────
def _df(opens, closes):
    idx = pd.date_range("2026-09-24", periods=len(closes), freq="D")
    return pd.DataFrame({"Open": opens, "Close": closes}, index=idx)


def test_momentum_day_without_opening_gap_is_not_blocked(monkeypatch):
    # Close springt von 100 auf 103 (1,5 ATR), aber die Eröffnung lag am Vortagesschluss
    df = _df([99.0, 100.1], [100.0, 103.0])
    monkeypatch.setattr(sm, "get_price_data_cached", lambda t: (103.0, 2.0, df))
    cur, prev = sm.get_overnight_gap_inputs("X")
    assert (cur, prev) == (100.1, 100.0)
    assert sm.has_overnight_gap(cur, 2.0, prev) is False
    # der alte Vergleich Close/Close hätte geblockt
    assert sm.has_overnight_gap(103.0, 2.0, 100.0) is True


def test_real_opening_gap_is_blocked(monkeypatch):
    df = _df([99.0, 104.0], [100.0, 104.5])
    monkeypatch.setattr(sm, "get_price_data_cached", lambda t: (104.5, 2.0, df))
    cur, prev = sm.get_overnight_gap_inputs("X")
    assert sm.has_overnight_gap(cur, 2.0, prev) is True


def test_gap_threshold_is_0_8_atr():
    assert sm.GAP_ATR_THRESHOLD == 0.8
    assert sm.has_overnight_gap(101.5, 2.0, 100.0) is False    # 0,75 ATR
    assert sm.has_overnight_gap(101.7, 2.0, 100.0) is True     # 0,85 ATR


def test_gap_inputs_are_none_without_data(monkeypatch):
    monkeypatch.setattr(sm, "get_price_data_cached", lambda t: (None, None, None))
    assert sm.get_overnight_gap_inputs("X") == (None, None)
    df = _df([float("nan"), float("nan")], [100.0, 101.0])
    monkeypatch.setattr(sm, "get_price_data_cached", lambda t: (101.0, 2.0, df))
    assert sm.get_overnight_gap_inputs("X") == (None, None)


# ── M4 ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("score", "tier"), [(0.9, "HIGH"), (0.8, "HIGH"), (0.7, "NORMAL"), (0.6, "NORMAL"), (0.3, "LOW"), (None, "LOW")])
def test_conviction_tier_thresholds(score, tier):
    assert sm.conviction_tier(score) == tier


def _positions_insert_call():
    tree = ast.parse(open(SRC_PATH, encoding="utf-8").read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str) and "INSERT INTO positions" in node.args[0].value
                and "exit_mode" in node.args[0].value):
            return node
    raise AssertionError("INSERT INTO positions nicht gefunden")


def test_entry_insert_stores_conviction_score_and_tier_with_matching_arity():
    call = _positions_insert_call()
    sql = call.args[0].value
    columns = [c.strip() for c in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
    placeholders = sql.split("VALUES", 1)[1].count("?")
    params = call.args[1]
    assert isinstance(params, ast.Tuple)
    assert "entry_conviction_score" in columns and "entry_conviction_tier" in columns
    assert len(columns) == placeholders == len(params.elts)


def test_segment_gate_only_blocks_when_explicitly_enforced():
    src = open(SRC_PATH, encoding="utf-8").read()
    assert 'cfg.get("segment_gate_enforce", False)' in src
