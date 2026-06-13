#!/usr/bin/env python3
"""
cleanup_db.py

Bereinigt Backup-Tabellen und alte Artefakte aus der Trading-DB.

Entfernt:
  - watchlist_with_sector_bak  (Rollback-Tabelle aus Paket D.4)
  - watchlist_old              (Audit-Tabelle aus Paket C, falls vorhanden)

AUSFÜHREN (erst nach ~1-2 Tagen Verifikation):
    cd /root/.hermes/.../scripts
    python3 cleanup_db.py [--dry-run]
"""
import sqlite3
import sys
import argparse
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading/scripts")
from config import DB_PATH, db_connect


TABLES_TO_DROP = [
    "watchlist_with_sector_bak",   # Rollback aus D.4
    "watchlist_old",               # Audit aus Paket C
    "watchlist_no_sector",         # Zwischentabelle aus D.4 (falls noch da)
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Nur anzeigen, nichts löschen")
    args = parser.parse_args()

    con = db_connect()

    existing = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    print("=== cleanup_db: Backup-Tabellen entfernen ===\n")
    dropped = []
    for table in TABLES_TO_DROP:
        if table in existing:
            count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if args.dry_run:
                print(f"  [DRY-RUN] würde löschen: {table} ({count} Zeilen)")
            else:
                con.execute(f"DROP TABLE IF EXISTS {table}")
                con.commit()
                print(f"  ✅ Gelöscht: {table} ({count} Zeilen)")
                dropped.append(table)
        else:
            print(f"  ℹ️  Nicht vorhanden: {table}")

    if not args.dry_run:
        # VACUUM nach Drop (gibt Speicher frei)
        print("\n  VACUUM läuft...")
        con.execute("VACUUM")
        print(f"✅ Fertig. {len(dropped)} Tabelle(n) entfernt.")
    else:
        print("\n(Dry-Run – keine Änderungen)")

    con.close()


if __name__ == "__main__":
    main()
