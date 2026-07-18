"""
roles/ — Hedgefonds-Rollen-Layer fuer Hermes Trading (Sprint R1-R4).

Enthaelt LLM-Rollen, die AUSSCHLIESSLICH an Urteils-Stellen der bestehenden
Pipeline eingehaengt werden. Der deterministische Backbone bleibt unangetastet.

Grundregeln (siehe Konzept, Abschnitt 0):
  - Fail-Open: jeder Fehler/Timeout/Budget-Stopp fuehrt zum heutigen Verhalten.
  - Alles geloggt: jeder Rollen-Call landet in der DB (Audit-Trail).
  - Kein Rollen-Fehler darf jemals in den Entry-Loop propagieren.

Layout:
    roles/__init__.py        # Schema-Migration (idempotent)
    roles/budget.py          # Token-Budget-Verwaltung
    roles/committee.py       # Investment Committee (Bull / Bear / Risk)
    roles/devils_advocate.py # Devil's Advocate (Thesis-Monitor Stufe 2)
"""
import sys

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")

_SCHEMA_READY = False


def ensure_roles_schema(con):
    """
    Idempotente Schema-Migration fuer den Rollen-Layer.

    Wird von jeder Rolle beim Start aufgerufen. Prozess-weit gecacht, damit der
    Entry-Loop nicht bei jedem Kandidaten DDL absetzt.

    Args:
        con: bestehende DB-Connection (wird DURCHGEREICHT, nie neu geoeffnet).
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    con.execute("""
        CREATE TABLE IF NOT EXISTS llm_budget_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            date      TEXT NOT NULL,
            role      TEXT NOT NULL,
            tokens_in  INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            calls      INTEGER DEFAULT 0,
            model      TEXT,
            UNIQUE(date, role, model)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS committee_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            check_date    TEXT NOT NULL,
            ticker        TEXT NOT NULL,
            direction     TEXT NOT NULL,
            mode          TEXT NOT NULL,
            bull_json     TEXT,
            bear_json     TEXT,
            risk_json     TEXT,
            final_verdict TEXT,
            size_factor   REAL DEFAULT 1.0,
            would_block   INTEGER DEFAULT 0,
            entry_happened INTEGER DEFAULT 0,
            tokens_in     INTEGER,
            tokens_out    INTEGER,
            models_used   TEXT,
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)

    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_committee_ticker_date
        ON committee_log(ticker, check_date)
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_budget_date_role
        ON llm_budget_log(date, role)
    """)

    con.commit()
    _SCHEMA_READY = True
