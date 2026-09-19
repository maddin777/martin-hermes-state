#!/usr/bin/env python3
"""Repariert die Extremwert-Sentinels in positions (18.09.2026).

Bis zum 18.09.2026 setzte signal_manager beim Entry nur das RICHTUNGS-guenstige
Extrem auf den Entry-Preis und das jeweils andere auf 0:

    highest_price = entry if LONG else 0
    lowest_price  = entry if SHORT else 0

Zwei Probleme:
  1. 0 ist als Sentinel nicht von einem echten Kurs unterscheidbar. Jede
     Auswertung, die min(lowest_price, ...) rechnet, bekommt 0 und damit eine
     scheinbar unendliche Gegenbewegung.
  2. Die maximale Gegenbewegung (MAE) war fuer LONGs nie messbar, die MFE fuer
     SHORTs nie — in 88 geschlossenen Trades fehlte die MAE damit vollstaendig.

Dieses Skript setzt 0-Sentinels auf den Entry-Preis. Das ist die korrekte
untere Schranke: zum Entry-Zeitpunkt waren beide Extremwerte per Definition
der Entry-Preis. Fuer bereits GESCHLOSSENE Trades laesst sich die tatsaechliche
Gegenbewegung nicht rekonstruieren — deren Zeilen werden deshalb markiert,
nicht erfunden: sie behalten den Entry-Preis und sind an
highest_price == lowest_price == entry_price als "nicht gemessen" erkennbar.

Idempotent. Aufruf:  python3 scripts/migrate_fix_extremes.py [--apply]
"""
import sys

from config import db_connect


def main(apply: bool) -> None:
    con = db_connect()
    rows = con.execute("""
        SELECT id, ticker, direction, status, entry_price,
               highest_price, lowest_price
        FROM positions
        WHERE entry_price IS NOT NULL
          AND (highest_price IS NULL OR highest_price <= 0
               OR lowest_price IS NULL OR lowest_price <= 0)
    """).fetchall()

    if not rows:
        print("✅ Keine 0-Sentinels gefunden — nichts zu tun.")
        con.close()
        return

    open_n = sum(1 for r in rows if r["status"] == "open")
    print(f"🔧 {len(rows)} Zeilen mit 0-Sentinel "
          f"({open_n} offen, {len(rows) - open_n} geschlossen)")

    for r in rows[:10]:
        print(f"   {r['ticker']:10s} {r['direction']:5s} {r['status']:6s} "
              f"entry={r['entry_price']:.2f} "
              f"high={r['highest_price']} low={r['lowest_price']}")
    if len(rows) > 10:
        print(f"   ... und {len(rows) - 10} weitere")

    if not apply:
        print("\nProbelauf. Mit --apply schreiben.")
        con.close()
        return

    for r in rows:
        hi = r["highest_price"] if (r["highest_price"] or 0) > 0 else r["entry_price"]
        lo = r["lowest_price"] if (r["lowest_price"] or 0) > 0 else r["entry_price"]
        # Konsistenz erzwingen: high >= entry >= low gilt immer.
        hi = max(hi, r["entry_price"])
        lo = min(lo, r["entry_price"])
        con.execute("UPDATE positions SET highest_price=?, lowest_price=? WHERE id=?",
                    (round(hi, 4), round(lo, 4), r["id"]))
    con.commit()
    print(f"\n✅ {len(rows)} Zeilen repariert.")
    print("   Hinweis: Fuer geschlossene Trades ist die MAE damit NICHT")
    print("   rekonstruiert, nur der Sentinel entfernt. Echte MAE-Daten")
    print("   entstehen ab jetzt im laufenden Betrieb.")
    con.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
