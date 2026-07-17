#!/usr/bin/env python3
"""
Migration: Crabel-Instrumentierung (Stufe 1 — Messen, nicht Entscheiden).

Legt an:
  1. Tabelle `blocked_entries` — Shadow-Log aller vom Crabel-Gate verhinderten
     Entries inkl. der SL/TP-Level, die gegolten hätten. Wird von
     `crabel_shadow_eval.py` vorwärts bepreist → liefert den Counterfactual,
     den `positions` prinzipbedingt NICHT enthalten kann (dort stehen nur die
     Trades, die der Filter durchgelassen hat → Survivorship Bias).
  2. Spalte `positions.crabel_at_entry` — Pattern-State beim Entry als JSON,
     damit gelaufene Trades später in Kohorten gesplittet werden können
     (Breakout nach Kontraktion bestätigt vs. Gate war gar nicht scharf).

Idempotent — kann mehrfach laufen.
"""
import sys
import os

_TRADING_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (_TRADING_ROOT, os.path.join(_TRADING_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import db_connect

DDL = """
CREATE TABLE IF NOT EXISTS blocked_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    name            TEXT,
    direction       TEXT NOT NULL,          -- LONG | SHORT
    gate            TEXT NOT NULL,          -- 'crabel' (erweiterbar für weitere Filter)
    blocked_at      TEXT,                   -- ISO datetime
    block_date      TEXT NOT NULL,          -- YYYY-MM-DD (Dedup-Schlüssel)

    -- Zustand zum Block-Zeitpunkt (alles in Heimwährung des Tickers)
    price_at_block  REAL,                   -- current_price
    would_entry     REAL,                   -- effective_entry inkl. Entry-Slippage
    would_sl        REAL,
    would_tp        REAL,
    atr_at_block    REAL,
    asset_type      TEXT,
    conviction      REAL,
    tech_score      REAL,
    crabel_state    TEXT,                   -- JSON-Dump von get_crabel_patterns()
    breakout_level  REAL,                   -- der Level, der nicht erreicht wurde

    -- Auswertung (von crabel_shadow_eval.py gefüllt)
    eval_status     TEXT DEFAULT 'pending', -- pending | evaluated | no_data
    eval_date       TEXT,
    outcome         TEXT,                   -- SL_HIT | TP_HIT | TIMEOUT
    days_to_outcome INTEGER,
    exit_price_sim  REAL,
    pnl_pct_sim     REAL,                   -- ohne Commission (wie positions.pnl_pct)

    -- Wurde derselbe Kandidat später doch noch real eingekauft?
    later_entered     INTEGER DEFAULT 0,
    later_entry_days  INTEGER,
    later_entry_price REAL
);

-- Dedup: signal_manager kann mehrfach täglich laufen. Ohne diesen Index würde
-- derselbe geblockte Kandidat pro Lauf erneut geloggt und das Sample aufblähen.
CREATE UNIQUE INDEX IF NOT EXISTS idx_blocked_entries_dedup
    ON blocked_entries(ticker, direction, block_date, gate);

CREATE INDEX IF NOT EXISTS idx_blocked_entries_status
    ON blocked_entries(eval_status, block_date);
"""


def main():
    con = db_connect()
    try:
        con.executescript(DDL)

        # Spalte positions.crabel_at_entry (ALTER TABLE ist nicht idempotent)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(positions)").fetchall()}
        if "crabel_at_entry" not in cols:
            con.execute("ALTER TABLE positions ADD COLUMN crabel_at_entry TEXT")
            print("  ✓ positions: Spalte crabel_at_entry hinzugefügt")
        else:
            print("  · positions.crabel_at_entry existiert bereits")

        con.commit()
        n = con.execute("SELECT COUNT(*) FROM blocked_entries").fetchone()[0]
        print(f"✓ blocked_entries bereit (aktuell {n} Einträge)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
