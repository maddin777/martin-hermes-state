#!/usr/bin/env python3
"""
migrate_add_strength.py

Fügt die `strength`-Spalte (strong/moderate/weak) zur watchlist_mentions-Tabelle hinzu.
Diese Information wurde vom LLM extrahiert aber nie persistiert.

Danach speichert watchlist_manager.py den strength-Wert bei jedem INSERT.
Bestehende Einträge erhalten 'moderate' als Standardwert.

AUSFÜHREN (einmalig):
    cd /root/.hermes/.../scripts
    python3 migrate_add_strength.py
"""
import sqlite3
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading/scripts")
from config import DB_PATH


def main():
    print("=== migrate_add_strength: strength-Spalte zu watchlist_mentions ===\n")
    con = sqlite3.connect(DB_PATH)

    cols = [r[1] for r in con.execute("PRAGMA table_info(watchlist_mentions)").fetchall()]
    print(f"   Aktuelle Spalten: {cols}")

    if "strength" in cols:
        print("ℹ️  strength-Spalte bereits vorhanden – nichts zu tun.")
        con.close()
        return

    con.execute("ALTER TABLE watchlist_mentions ADD COLUMN strength TEXT DEFAULT 'moderate'")
    con.commit()

    count = con.execute("SELECT COUNT(*) FROM watchlist_mentions").fetchone()[0]
    print(f"✅ strength-Spalte hinzugefügt. {count} bestehende Einträge → 'moderate'")
    con.close()


if __name__ == "__main__":
    main()
