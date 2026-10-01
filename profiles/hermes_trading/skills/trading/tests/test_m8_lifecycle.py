"""M8: source_lifecycle vergleicht in der richtigen Einheit und bestraft kein leeres 90-Tage-Fenster."""
import sqlite3
from datetime import datetime, timedelta

from scripts import source_lifecycle as sl


def make_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    sl.ensure_schema(con)
    con.execute("""CREATE TABLE positions (id INTEGER PRIMARY KEY, status TEXT, pnl_eur REAL, pnl_pct REAL,
        position_size REAL, exit_date TEXT, source_channel TEXT)""")
    con.execute("CREATE TABLE watchlist_mentions (id INTEGER PRIMARY KEY, channel TEXT, mention_date TEXT)")
    return con


def add_source(con, name, status="active"):
    con.execute("INSERT INTO source_registry (source_type, source_key, display_name, status, weight, enabled, "
                "last_mention_date, added_at) VALUES ('youtube', ?, ?, ?, 1.0, 1, date('now'), date('now','-200 day'))",
                (name.lower(), name, status))
    return con.execute("SELECT id FROM source_registry WHERE display_name=?", (name,)).fetchone()[0]


def add_trades(con, channel, results, days_ago=10):
    """results: Liste (pnl_eur, pnl_pct)"""
    for i, (eur, pct) in enumerate(results):
        d = (datetime.now() - timedelta(days=days_ago + i)).strftime("%Y-%m-%d")
        con.execute("INSERT INTO positions (status, pnl_eur, pnl_pct, position_size, exit_date, source_channel) "
                    "VALUES ('closed', ?, ?, 700, ?, ?)", (eur, pct, d, channel.lower()))
    con.commit()


def state(con, name):
    r = con.execute("SELECT status, weight, enabled FROM source_registry WHERE display_name=?", (name,)).fetchone()
    return r["status"], r["weight"], r["enabled"]


def run(con):
    sl.evaluate_active_sources(con)
    sl.demote_bad_sources(con)
    con.commit()


def test_a_small_euro_loss_is_not_a_two_percent_loss():
    con = make_db()
    add_source(con, "Tippgeber")
    # 6 Trades: 3 Gewinner, 3 Verlierer, Durchschnitt -8 EUR = -1,1 % auf 700 EUR (Verlustserie < 5)
    add_trades(con, "Tippgeber", [(30, 4.3), (-60, -8.6), (25, 3.6), (-55, -7.9), (20, 2.9), (-8, -1.1)])
    run(con)
    r = con.execute("SELECT avg_pnl_per_trade, avg_pnl_pct FROM source_registry").fetchone()
    assert r["avg_pnl_per_trade"] < -2 and -2 < r["avg_pnl_pct"] < 0      # alt: als -2 EUR gegen -2 verglichen
    assert state(con, "Tippgeber") == ("active", 1.0, 1)


def test_a_source_with_a_real_percent_loss_is_still_penalized():
    con = make_db()
    add_source(con, "Verlierer")
    add_trades(con, "Verlierer", [(-70, -10.0), (20, 2.9), (-60, -8.6), (30, 4.3), (-50, -7.1)])
    run(con)
    st, weight, enabled = state(con, "Verlierer")
    assert weight == sl.THRESHOLDS["penalize_min_weight"] and enabled == 1


def test_an_empty_ninety_day_window_is_no_reason_to_penalize_or_remove():
    con = make_db()
    add_source(con, "Ruhig")
    # 12 alte Gewinner-/Verlierer-Trades, alle älter als 90 Tage
    add_trades(con, "Ruhig", [(10, 1.4)] * 6 + [(-5, -0.7)] * 6, days_ago=120)
    run(con)
    r = con.execute("SELECT win_rate_90d, trades_90d FROM source_registry").fetchone()
    assert r["trades_90d"] == 0 and r["win_rate_90d"] == 0.0
    assert state(con, "Ruhig") == ("active", 1.0, 1)


def test_a_source_with_enough_recent_losses_is_still_removed():
    con = make_db()
    add_source(con, "Schlecht")
    add_trades(con, "Schlecht", [(-10, -1.4)] * 12 + [(5, 0.7)], days_ago=5)      # WR 90d ~ 8 %
    run(con)
    assert state(con, "Schlecht")[0] == "removed"


def test_metric_columns_are_migrated_on_an_old_table():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE source_registry (id INTEGER PRIMARY KEY, display_name TEXT)")
    sl._ensure_metric_columns(con)
    sl._ensure_metric_columns(con)                       # idempotent
    cols = {r[1] for r in con.execute("PRAGMA table_info(source_registry)")}
    assert {"trades_90d", "avg_pnl_pct"} <= cols
