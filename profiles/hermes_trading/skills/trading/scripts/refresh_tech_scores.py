#!/usr/bin/env python3
"""
refresh_tech_scores.py

Berechnet tech_score und tech_direction für alle Watchlist-Einträge neu.
Nötig nach Paket-C-Migration (alle tech_scores wurden genullt).

Laufzeit: ~2-3 min bei 50+ Einträgen (yfinance-Downloads).

AUSFÜHREN:
    cd /root/.hermes/.../scripts
    python3 refresh_tech_scores.py [--min-conviction 0.3]
"""
import sqlite3
import sys
import argparse
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa
from config import DB_PATH, db_connect
from utils import get_technical_score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-conviction", type=float, default=0.3,
                        help="Nur Einträge mit conviction >= X neu berechnen (default: 0.3)")
    parser.add_argument("--all", action="store_true",
                        help="Alle Einträge neu berechnen, auch dropped")
    args = parser.parse_args()

    con = db_connect()
    status_filter = "status IN ('watching','bought')" if not args.all else "1=1"
    candidates = con.execute(f"""
        SELECT name, ticker, conviction_score, tech_score, status
        FROM watchlist
        WHERE {status_filter}
          AND ticker IS NOT NULL
          AND conviction_score >= ?
        ORDER BY conviction_score DESC
    """, (args.min_conviction,)).fetchall()

    print(f"🔄 Tech-Scores neu berechnen: {len(candidates)} Einträge "
          f"(conviction ≥ {args.min_conviction})\n")

    ok = skipped = errors = 0
    cleared = 0
    for c in candidates:
        print(f"  {c['name']:30} {c['ticker']:10} Conv:{c['conviction_score']:.2f}",
              end="  ", flush=True)
        tech = get_technical_score(c["ticker"])
        if tech:
            con.execute("""
                UPDATE watchlist SET tech_score=?, tech_direction=?
                WHERE ticker=?
            """, (tech["confidence"], tech["direction"], c["ticker"]))
            con.commit()
            print(f"→ {tech['confidence']:.2f} {tech['direction']}", flush=True)
            ok += 1
        else:
            # FIX 16.08.: veraltete Scores NICHT stehen lassen. Wenn der
            # UK-Liquidity-Gate / Bar-Gate jetzt None liefert (z.B. AIM/Nano-Cap
            # .L nach neuem UK_MIN_TURNOVER_EUR-Gate), muss der alte Score
            # gecleart werden — sonst sieht der Eintrag entry-fähig aus und
            # verzerrt die Conviction-/DQ-Verteilung. (Doku-Gotcha 14.08.)
            cur = con.execute("""
                UPDATE watchlist
                SET tech_score=NULL, tech_direction=NULL, weekly_trend=NULL
                WHERE ticker=? AND tech_score IS NOT NULL
            """, (c["ticker"],))
            was_cleared = cur.rowcount > 0
            if was_cleared:
                cleared += 1
            con.commit()
            print("→ keine Daten (Score gecleart)" if was_cleared
                  else "→ keine Daten", flush=True)
            skipped += 1

    con.close()
    print(f"\n✅ Fertig: {ok} aktualisiert, {skipped} übersprungen (davon {cleared} veraltete Scores gecleart), {errors} Fehler")


if __name__ == "__main__":
    main()
