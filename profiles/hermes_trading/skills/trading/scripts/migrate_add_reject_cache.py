#!/usr/bin/env python3
"""
Migration: Negativ-Cache-Tabelle `validation_rejects` für company_validator.

Merkt sich abgelehnte Firmennamen (deterministische Gründe), damit der teure
yfinance-Gauntlet (yf.Search + .info) nicht jede Nacht erneut für denselben
Müll-Namen läuft. Idempotent — kann mehrfach laufen.
"""
import sys
import os

_TRADING_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (_TRADING_ROOT, os.path.join(_TRADING_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import db_connect

DDL = """
CREATE TABLE IF NOT EXISTS validation_rejects (
    name_key    TEXT PRIMARY KEY,           -- name.lower().strip()
    reason      TEXT,                        -- unknown | not_equity | name_mismatch | low_liquidity
    ticker      TEXT,                        -- bester abgelehnter Ticker (nullable)
    details     TEXT,                        -- gekürzte Details
    rejected_at TEXT DEFAULT (datetime('now')),
    hit_count   INTEGER DEFAULT 1            -- wie oft der Cache diesen Namen abgefangen hat
);
CREATE INDEX IF NOT EXISTS idx_validation_rejects_rejected_at
    ON validation_rejects(rejected_at);
"""


def main():
    con = db_connect()
    try:
        con.executescript(DDL)
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM validation_rejects").fetchone()[0]
        print(f"✓ validation_rejects bereit (aktuell {n} Einträge)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
