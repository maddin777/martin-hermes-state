"""
config.py — gemeinsamer Config-/DB-Helper für den Forex-Paper-Bot.

Lädt config.json (Single Source of Truth), stellt DB-Connection + Schema bereit.
DB-First: keine Hardcodes in Scripts.
"""
import json
import os
import sqlite3

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()


def db_path():
    return os.path.join(SKILL_DIR, CONFIG["db_path"])


def db_connect():
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=120000")
    return con


def init_db(con=None):
    """Erzeugt das Schema, falls nicht vorhanden. Idempotent."""
    own = con is None
    if own:
        con = db_connect()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,             -- LONG | SHORT
            entry_time TEXT,
            entry_price REAL,
            exit_time TEXT,
            exit_price REAL,
            sl REAL,
            tp REAL,
            trail_stop REAL,
            size_units REAL,
            risk_eur REAL,
            spread_cost_eur REAL,
            pnl_gross REAL,
            pnl_net REAL,
            exit_reason TEXT,
            params_snapshot TEXT,                -- JSON der genutzten Parameter
            status TEXT NOT NULL                 -- open | closed
        );
        CREATE TABLE IF NOT EXISTS params_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            pair TEXT,
            params_json TEXT NOT NULL,
            lookback_weeks INTEGER,
            metric_name TEXT,
            metric_value REAL,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            starting_capital REAL NOT NULL,
            cash REAL NOT NULL,
            equity_peak REAL NOT NULL,
            realized_pnl REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            trades_count INTEGER,
            gross_pnl REAL,
            net_pnl REAL,
            win_rate REAL,
            profit_factor REAL,
            drawdown_pct REAL,
            report_md TEXT,
            UNIQUE(report_date)
        );
    """)
    # Portfolio-Seed
    if con.execute("SELECT COUNT(*) FROM portfolio WHERE id=1").fetchone()[0] == 0:
        con.execute(
            "INSERT INTO portfolio (id, starting_capital, cash, equity_peak, realized_pnl) "
            "VALUES (1, ?, ?, ?, 0)",
            (CONFIG["capital"], CONFIG["capital"], CONFIG["capital"]),
        )
    if own:
        con.commit()
        con.close()


def get_portfolio(con):
    row = con.execute("SELECT * FROM portfolio WHERE id=1").fetchone()
    if row is None:
        init_db(con)
        row = con.execute("SELECT * FROM portfolio WHERE id=1").fetchone()
    return row


def update_portfolio(con, **kw):
    cols = ", ".join(f"{k}=?" for k in kw)
    con.execute(f"UPDATE portfolio SET {cols} WHERE id=1", list(kw.values()))
    con.commit()


def drawdown_pct(con):
    """Aktueller Drawdown in % (basierend auf realized PnL + equity_peak)."""
    p = get_portfolio(con)
    if p["equity_peak"] <= 0:
        return 0.0
    # aktuelle Equity = cash (realisierte Gewinne/Verluste schlagen auf cash durch)
    equity = p["cash"]
    dd = (p["equity_peak"] - equity) / p["equity_peak"]
    return max(0.0, dd)
