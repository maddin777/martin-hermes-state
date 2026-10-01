"""M6: nightly_eval speichert die Risiko-Kennzahlen und misst das Top-Band ueber gekaufte Titel mit."""
import sqlite3
from datetime import datetime, timedelta

from scripts import nightly_eval as ne

EVAL_DDL = """CREATE TABLE eval_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, metric_type TEXT NOT NULL,
    new_companies INTEGER DEFAULT 0, confirmed INTEGER DEFAULT 0, contradicted INTEGER DEFAULT 0,
    avg_conviction REAL DEFAULT 0, signals_bought INTEGER DEFAULT 0, open_positions INTEGER DEFAULT 0,
    win_rate_7d REAL DEFAULT 0, win_rate_30d REAL DEFAULT 0, profit_factor_7d REAL DEFAULT 0,
    avg_holding_days REAL DEFAULT 0, exit_sl_pct REAL DEFAULT 0, exit_tp_pct REAL DEFAULT 0,
    exit_tech_pct REAL DEFAULT 0, created_at TEXT, notes TEXT, UNIQUE(date, metric_type))"""


def make_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, cash REAL, total_value REAL)")
    con.execute("INSERT INTO portfolio VALUES (1, 5000, 10000)")
    con.execute("""CREATE TABLE positions (id INTEGER PRIMARY KEY, ticker TEXT, name TEXT, direction TEXT,
        status TEXT, pnl_eur REAL, position_size REAL, entry_date TEXT, exit_date TEXT, exit_reason TEXT)""")
    con.execute("CREATE TABLE watchlist (ticker TEXT, name TEXT, status TEXT, conviction_score REAL)")
    con.execute(EVAL_DDL)
    return con


def add_closed(con, pnl, days_ago, ticker="T"):
    d = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    con.execute("INSERT INTO positions (ticker, name, direction, status, pnl_eur, position_size, entry_date, exit_date, "
                "exit_reason) VALUES (?,?, 'LONG', 'closed', ?, 500, ?, ?, 'SL_HIT')",
                (ticker, ticker, pnl, d, d))


SM = {"new_companies": 1, "confirmed": 0, "contradicted": 0, "avg_conviction": 0.6, "signals_bought": 0}


def test_risk_metrics_are_stored_and_not_zero_when_there_are_trades():
    con = make_db()
    for i, pnl in enumerate([120, -80, 60, -200, 40, -30]):
        add_closed(con, pnl, 3 + i * 3)
    con.execute("INSERT INTO positions (ticker, name, direction, status, position_size) VALUES ('O','O','LONG','open',1000)")
    con.commit()
    pm = ne.calc_portfolio_metrics(con)
    assert pm["max_drawdown_30d"] > 0 and pm["sortino_30d"] != 0 and pm["exposure_long_pct"] > 0
    ne.store_eval_metrics(con, "2026-09-30", "daily", SM, pm, "done")
    row = con.execute("SELECT * FROM eval_metrics").fetchone()
    for key in ("sortino_30d", "calmar_30d", "max_drawdown_30d", "avg_r_multiple",
                "exposure_long_pct", "exposure_short_pct", "exposure_net_pct"):
        assert row[key] == pm[key], key
    assert row["max_drawdown_30d"] > 0 and row["exposure_long_pct"] == 10.0


def test_missing_risk_columns_are_migrated_and_the_second_write_replaces_the_row():
    con = make_db()
    add_closed(con, -50, 5)
    add_closed(con, 30, 8)
    con.commit()
    pm = ne.calc_portfolio_metrics(con)
    ne.store_eval_metrics(con, "2026-09-30", "daily", SM, pm, "done")
    ne.store_eval_metrics(con, "2026-09-30", "daily", SM, pm, "running")
    rows = con.execute("SELECT notes FROM eval_metrics").fetchall()
    assert len(rows) == 1 and rows[0]["notes"] == "pipeline=running"


def test_top_band_counts_titles_that_were_bought():
    con = make_db()
    for ticker, status, conv in [("AAA", "bought", 0.95), ("BBB", "watching", 0.90), ("CCC", "watching", 0.80)]:
        con.execute("INSERT INTO watchlist VALUES (?,?,?,?)", (ticker, ticker, status, conv))
    d = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    con.execute("INSERT INTO positions (ticker, name, direction, status, pnl_eur, position_size, entry_date, exit_date) "
                "VALUES ('AAA','AAA','LONG','closed', 40, 500, ?, ?)", (d, d))
    con.commit()
    tb = ne.calc_top_band_metrics(con)
    assert tb["top3_bought"] == 1 and tb["top3_win_rate"] == 1.0 and tb["top3_pnl"] == 40.0
