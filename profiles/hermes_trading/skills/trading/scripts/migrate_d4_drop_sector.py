#!/usr/bin/env python3
"""
migrate_d4_drop_sector.py — Paket D.4

Entfernt die denormalisierte `sector`-Spalte aus der `watchlist`-Tabelle.
Sektor wird ab jetzt ausschließlich per JOIN aus `companies.sector` gelesen.

VORAUSSETZUNGEN:
  - Paket D.2: export_watchlist.py nutzt bereits JOIN ✅
  - Paket D.3: watchlist_dedup.py nutzt bereits JOIN (erst nach Cron-Check!)
  - watchlist_manager.py: Schreibvorgänge auf watchlist.sector entfernt ✅

ABLAUF:
  1. Backup der DB anlegen
  2. Neue Tabelle ohne sector-Spalte anlegen
  3. Daten kopieren
  4. Tabellen tauschen
  5. Verify

AUSFÜHREN:
  python3 migrate_d4_drop_sector.py

Sicher rückgängig zu machen über das Backup.
"""
import sqlite3
import shutil
import os
from datetime import datetime

DB_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
BACKUP_PATH = DB_PATH.replace(
    "trading.db",
    f"trading.db.pre-d4-drop-sector.{datetime.now().strftime('%Y-%m-%d-%H%M')}.bak"
)


def main():
    print("=== Paket D.4: sector-Spalte aus watchlist entfernen ===\n")

    # 1. Backup
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"✅ Backup: {BACKUP_PATH}")

    con = db_connect()
    # 2. Prüfen ob sector-Spalte noch existiert
    cols = [r["name"] for r in con.execute("PRAGMA table_info(watchlist)").fetchall()]
    print(f"   Aktuelle Spalten: {cols}")

    if "sector" not in cols:
        print("ℹ️  sector-Spalte existiert nicht mehr – Migration bereits durchgeführt.")
        con.close()
        return

    # 3. Prüfen ob watchlist_manager noch sector schreibt (Safety-Check)
    # Falls noch watchlist.sector im INSERT/UPDATE steht, abbrechen
    wm_path = os.path.join(os.path.dirname(DB_PATH), "..", "scripts", "watchlist_manager.py")
    wm_path = os.path.normpath(wm_path)
    if os.path.exists(wm_path):
        with open(wm_path) as f:
            wm_code = f.read()
        # Nach INSERT-Blocks suchen die sector enthalten (aber nicht JOIN/SELECT)
        import re
        inserts_with_sector = re.findall(
            r'INSERT INTO watchlist[^;]*?sector[^;]*?;', wm_code, re.DOTALL
        )
        updates_with_sector = re.findall(
            r'UPDATE watchlist SET[^;]*?sector\s*=[^;]*?;', wm_code, re.DOTALL
        )
        if inserts_with_sector or updates_with_sector:
            print("⚠️  STOP: watchlist_manager.py schreibt noch sector in watchlist!")
            print("   Erst watchlist_manager.py anpassen (sector aus INSERT/UPDATE raus).")
            print("   Dann dieses Skript erneut ausführen.")
            con.close()
            return

    # 4. Neue Tabelle ohne sector anlegen
    print("\n   Lege watchlist_no_sector an...")
    cols_no_sector = [c for c in cols if c != "sector"]
    col_list = ", ".join(cols_no_sector)

    con.execute("DROP TABLE IF EXISTS watchlist_no_sector")
    con.execute(f"""
        CREATE TABLE watchlist_no_sector AS
        SELECT {col_list}
        FROM watchlist
    """)

    # Indices übertragen
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist_no_sector(ticker)")
    count_new = con.execute("SELECT COUNT(*) FROM watchlist_no_sector").fetchone()[0]
    count_old = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    print(f"   watchlist_no_sector: {count_new} Einträge (watchlist: {count_old})")

    if count_new != count_old:
        print(f"❌ ABBRUCH: Zeilenanzahl stimmt nicht ({count_new} != {count_old})")
        con.execute("DROP TABLE watchlist_no_sector")
        con.close()
        return

    # 5. Tausch
    print("\n   Tausche Tabellen...")
    con.execute("ALTER TABLE watchlist RENAME TO watchlist_with_sector_bak")
    con.execute("ALTER TABLE watchlist_no_sector RENAME TO watchlist")

    con.commit()

    # 6. Verify
    new_cols = [r["name"] for r in con.execute("PRAGMA table_info(watchlist)").fetchall()]
    final_count = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    con.close()

    print(f"\n   Neue Spalten: {new_cols}")
    print(f"   Einträge: {final_count}")

    if "sector" in new_cols:
        print("❌ sector-Spalte noch vorhanden – Fehler im Tausch")
    else:
        print("\n✅ Paket D.4 erfolgreich: sector-Spalte entfernt!")
        print(f"   Rollback-Tabelle: watchlist_with_sector_bak (nach Verifikation löschen)")
        print(f"   Rollback-DB:      {BACKUP_PATH}")


if __name__ == "__main__":
    main()
