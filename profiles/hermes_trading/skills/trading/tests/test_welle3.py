"""Welle 3 (Code-Pruefung 30.09.2026): K4 bought-Status, M11 kompakte Datumswerte, M12 Dedup-Prioritaet/UNIQUE,
M10 Alias-Plausibilitaet, M15 PEAD-NaN. Alle Datenbanken sind im Speicher, alle Netzaufrufe gemockt."""
import json
import math
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest

from scripts import company_validator as cv
from scripts import pead_signal as pead
from scripts import watchlist_dedup as dedup
from scripts import watchlist_manager as wm

WATCHLIST_DDL = """CREATE TABLE watchlist(id INT, ticker TEXT, name TEXT, first_seen TEXT, last_seen TEXT,
  mention_count INT, bullish_count INT, bearish_count INT, neutral_count INT, conviction_score REAL,
  conviction_score_bear REAL, tech_score REAL, tech_direction TEXT, channels TEXT, status TEXT, notes TEXT,
  conviction_score_aged REAL, conviction_score_raw REAL, llm_verdict TEXT, llm_verdict_at TEXT, weekly_trend TEXT);
  CREATE UNIQUE INDEX idx_watchlist_ticker ON watchlist(ticker);"""


def make_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(WATCHLIST_DDL)
    con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, ticker TEXT, name TEXT, status TEXT, exit_date TEXT)")
    return con


def add_wl(con, name, ticker, status="watching", last_seen="2026-09-28", mentions=3, first_seen="2026-09-01"):
    con.execute("INSERT INTO watchlist (name, ticker, status, last_seen, first_seen, mention_count, bullish_count, "
                "bearish_count, neutral_count, conviction_score, conviction_score_bear, conviction_score_aged, channels) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, ticker, status, last_seen, first_seen, mentions, mentions, 0, 0, 0.7, 0.1, 0.6, "[]"))
    con.commit()


def add_pos(con, ticker, name, status, exit_date=None):
    con.execute("INSERT INTO positions (ticker, name, status, exit_date) VALUES (?,?,?,?)",
                (ticker, name, status, exit_date))
    con.commit()


def status_of(con, ticker):
    return con.execute("SELECT status FROM watchlist WHERE ticker=?", (ticker,)).fetchone()[0]


# ── K4 ──────────────────────────────────────────────────────────────────────────────────────
def test_bought_with_open_position_stays_bought():
    con = make_db()
    add_wl(con, "Apple", "AAPL", "bought")
    add_pos(con, "AAPL", "Apple", "open")
    assert wm.reactivate_closed_bought(con) == 0
    assert status_of(con, "AAPL") == "bought"


def test_bought_during_the_cooldown_after_an_exit_stays_bought():
    con = make_db()
    add_wl(con, "Apple", "AAPL", "bought")
    add_pos(con, "AAPL", "Apple", "closed", (datetime.now() - timedelta(hours=2)).isoformat())
    assert wm.reactivate_closed_bought(con) == 0
    assert status_of(con, "AAPL") == "bought"


def test_bought_after_the_cooldown_returns_to_watching():
    con = make_db()
    add_wl(con, "Apple", "AAPL", "bought")
    add_pos(con, "AAPL", "Apple", "closed", (datetime.now() - timedelta(hours=30)).isoformat())
    assert wm.reactivate_closed_bought(con) == 1
    assert status_of(con, "AAPL") == "watching"


def test_bought_without_any_position_row_returns_and_other_status_is_untouched():
    con = make_db()
    add_wl(con, "Amd", "AMD", "bought")
    add_wl(con, "Old", "OLD", "dropped")
    add_wl(con, "Now", "NOW", "watching")
    assert wm.reactivate_closed_bought(con) == 1
    assert (status_of(con, "AMD"), status_of(con, "OLD"), status_of(con, "NOW")) == ("watching", "dropped", "watching")


def test_open_position_matched_by_name_blocks_reactivation():
    con = make_db()
    add_wl(con, "Apple", "AAPL", "bought")
    add_pos(con, "AAPL.DE", "Apple", "open")
    assert wm.reactivate_closed_bought(con) == 0


def test_snapshot_no_orphan_bought_titles_remain_after_the_reactivation():
    try:
        from config import DB_PATH
        src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        con = sqlite3.connect(":memory:")
        src.backup(con)
        con.row_factory = sqlite3.Row
        before = con.execute("SELECT COUNT(*) FROM watchlist WHERE status='bought'").fetchone()[0]
    except Exception as e:
        pytest.skip(f"kein Snapshot: {e}")
    changed = wm.reactivate_closed_bought(con)
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    keep = {r[0] for r in con.execute("SELECT name FROM positions WHERE status='open' "
                                      "OR (status='closed' AND exit_date >= ?)", (cutoff,))}
    keep |= {r[0] for r in con.execute("SELECT ticker FROM positions WHERE status='open' "
                                       "OR (status='closed' AND exit_date >= ?)", (cutoff,))}
    remaining = con.execute("SELECT name, ticker FROM watchlist WHERE status='bought'").fetchall()
    assert all(r["name"] in keep or r["ticker"] in keep for r in remaining)
    assert len(remaining) + changed == before


# ── M11 ─────────────────────────────────────────────────────────────────────────────────────
def test_compact_dates_are_normalized_and_then_found_by_the_stale_query():
    con = make_db()
    add_wl(con, "Alt", "ALT", last_seen="20260621", first_seen="20260503")
    add_wl(con, "Neu", "NEU", last_seen="2026-09-29")
    assert wm.normalize_compact_dates(con) == 2
    row = con.execute("SELECT first_seen, last_seen FROM watchlist WHERE ticker='ALT'").fetchone()
    assert (row["first_seen"], row["last_seen"]) == ("2026-05-03", "2026-06-21")
    cutoff = (datetime(2026, 9, 30) - timedelta(days=14)).strftime("%Y-%m-%d")
    stale = [r[0] for r in con.execute("SELECT ticker FROM watchlist WHERE last_seen < ? AND status='watching'", (cutoff,))]
    assert stale == ["ALT"]
    assert wm.normalize_compact_dates(con) == 0            # idempotent


# ── M12 ─────────────────────────────────────────────────────────────────────────────────────
def test_dedup_by_name_keeps_the_best_ticker_without_unique_violation():
    con = make_db()
    add_wl(con, "ALPHA GROUP", "ALPHA.DE", mentions=9)
    add_wl(con, "Alpha Group", "ALPH", mentions=4)
    dedup.dedup_by_name(con)                                # vorher: IntegrityError oder falscher Ticker
    live = con.execute("SELECT name, ticker FROM watchlist WHERE status IN ('watching','bought')").fetchall()
    assert len(live) == 1 and live[0]["ticker"] == "ALPH"
    dropped = con.execute("SELECT ticker, notes FROM watchlist WHERE status='dropped'").fetchall()
    assert len(dropped) == 1 and "watchlist_dedup" in dropped[0]["notes"]


def test_dedup_merge_normalizes_compact_last_seen_and_sums_counters():
    con = make_db()
    add_wl(con, "OMEGA GROUP", "OMEGA", last_seen="20260921", mentions=2)
    add_wl(con, "Omega Group", "OMEGA.DE", last_seen="2026-09-25", mentions=3)
    dedup.dedup_by_name(con)
    row = con.execute("SELECT * FROM watchlist WHERE status='watching'").fetchone()
    assert row["mention_count"] == 5 and row["last_seen"] == "2026-09-25" and row["ticker"] == "OMEGA"


def test_dedup_ticker_phase_still_merges_and_keeps_bought():
    con = make_db()
    add_wl(con, "GAMMA GROUP", "GAM", "bought", mentions=1)
    add_wl(con, "Gamma Group", "GAM.DE", "watching", mentions=6)
    dedup.dedup_by_name(con)
    live = con.execute("SELECT status, ticker FROM watchlist WHERE status IN ('watching','bought')").fetchall()
    assert len(live) == 1 and live[0]["status"] == "bought" and live[0]["ticker"] == "GAM"


# ── M10 ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("name", "yahoo"), [
    ("Nissan Motor Corporation", "ZIM Integrated Shipping Services Ltd."),
    ("Capcom Co., Ltd.", "ZIM Integrated Shipping Services Ltd."),
    ("Champions Oncology, Inc.", "D-Wave Quantum Inc."),
])
def test_unrelated_names_sharing_only_filler_words_are_rejected(name, yahoo):
    assert cv._name_plausible(name, yahoo) is False


@pytest.mark.parametrize(("name", "yahoo"), [
    ("Apple", "Apple Inc."),
    ("Eli Lilly", "Eli Lilly and Company"),
    ("Alphabet", "Alphabet Inc."),
    ("NVIDIA Corp", "NVIDIA Corporation"),
    ("Deutsche Bank", "Deutsche Bank Aktiengesellschaft"),
    ("Marathon Digital Holdings", "Marathon Digital Holdings, Inc."),
    ("Moodys", "Moody's Corporation"),
    ("Citi", "Citigroup Inc."),
])
def test_real_aliases_still_pass(name, yahoo):
    assert cv._name_plausible(name, yahoo) is True


def test_a_name_that_is_the_ticker_symbol_passes_only_with_the_matching_ticker():
    assert cv._name_plausible("AAPL", "Apple Inc.") is False
    assert cv._name_plausible("AAPL", "Apple Inc.", ticker="AAPL") is True
    assert cv._name_plausible("COK.DE", "Cancom SE", ticker="COK.DE") is True


# ── M15 ─────────────────────────────────────────────────────────────────────────────────────
def _earnings(actual, estimate, days_ago=1):
    idx = pd.DatetimeIndex([pd.Timestamp(datetime.now() - timedelta(days=days_ago))])
    return pd.DataFrame({"EPS Estimate": [estimate], "Reported EPS": [actual]}, index=idx)


class _T:
    def __init__(self, df):
        self.earnings_dates = df


@pytest.mark.parametrize(("actual", "estimate"), [(float("nan"), 0.45), (0.5, float("nan")), (None, 0.4)])
def test_missing_numbers_are_no_signal(monkeypatch, actual, estimate):
    monkeypatch.setattr(pead.yf, "Ticker", lambda t: _T(_earnings(actual, estimate)))
    assert pead.get_pead_boost("XYZ") == (0.0, 0.0, None)


def test_real_beat_and_miss_still_work(monkeypatch):
    monkeypatch.setattr(pead.yf, "Ticker", lambda t: _T(_earnings(0.60, 0.50)))
    bl, bs, info = pead.get_pead_boost("XYZ")
    assert (bl, bs) == (pead.PEAD_BOOST_AMOUNT, 0.0) and info["surprise"] == "BEAT"
    monkeypatch.setattr(pead.yf, "Ticker", lambda t: _T(_earnings(0.40, 0.50)))
    bl, bs, info = pead.get_pead_boost("XYZ")
    assert (bl, bs) == (0.0, pead.PEAD_BOOST_AMOUNT) and info["surprise"] == "MISS"


def test_nan_entry_in_the_cache_is_recomputed(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    pead.ensure_pead_cache_table(con)
    poisoned = {"surprise": "MISS", "eps_actual": float("nan"), "eps_estimate": 0.45, "surprise_pct": float("nan")}
    con.execute("INSERT INTO pead_cache (ticker, boost_long, boost_short, info_json, fetched_at) VALUES (?,?,?,?,?)",
                ("MU", 0.0, 0.05, json.dumps(poisoned), datetime.now().isoformat()))
    con.commit()
    monkeypatch.setattr(pead.yf, "Ticker", lambda t: _T(_earnings(float("nan"), 0.45)))
    assert pead.get_pead_boost_cached("MU", con) == (0.0, 0.0, None)
    assert con.execute("SELECT boost_short FROM pead_cache WHERE ticker='MU'").fetchone()[0] == 0.0


def test_valid_cache_entry_is_still_served_from_cache(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    pead.ensure_pead_cache_table(con)
    info = {"surprise": "BEAT", "eps_actual": 0.6, "eps_estimate": 0.5, "surprise_pct": 0.2}
    con.execute("INSERT INTO pead_cache VALUES (?,?,?,?,?)",
                ("OK", 0.05, 0.0, json.dumps(info), datetime.now().isoformat()))
    con.commit()
    monkeypatch.setattr(pead.yf, "Ticker", lambda t: (_ for _ in ()).throw(AssertionError("kein Abruf erwartet")))
    assert pead.get_pead_boost_cached("OK", con)[:2] == (0.05, 0.0)
