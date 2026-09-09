#!/usr/bin/env python3
"""
stale_refresh_queue.py — Kuratierte Refresh-Queue für Top-Conviction-Positionen.

Problem (vault-insights 08.09.2026, Punkt 3): 77% der Watchlist ist >14d stale.
Die Top-Conviction-Positionen (NVDA, MSFT, GOOGL, AMD …) erhalten seit Mai keine
frischen YouTube/RSS-Mentions mehr → `last_seen` altert → JEDE Entscheidung auf
diesen Positionen beruht auf wochen/monatelten Mentions. Die 22:30-Cleanup-Schleife
beobachtet das nur; `watchlist_manager` (03:30) DROPPT watching-Einträge sogar bei
last_seen < 14d ohne frische Mention.

Fix: Aktive Refresh-Queue. Nimm die Top-N-Conviction-Positionen (watching + bought),
hole für Positionen deren last_seen älter als STALE_DAYS ist KOSTENLOSE frische News
(Google News RSS — kein API-Key, gleiches Muster wie last30days_gate), frisch last_seen
auf heute auf und protokolliere je Lauf in `stale_refresh_log`.

Nutzung:
    python3 stale_refresh_queue.py [--top 20] [--stale-days 14] [--apply]
                 # Dry-Run (default): zeigt, was refresht WÜRDE. --apply schreibt.
"""

import json
import sqlite3
import sys
import argparse
from datetime import datetime

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa
from config import DB_PATH, db_connect
from scripts.last30days_gate import search_news, analyze_sentiment


def main():
    parser = argparse.ArgumentParser(description="Stale-Refresh-Queue für Top-Conviction")
    parser.add_argument("--top", type=int, default=20, help="Anzahl Positionen (default 20)")
    parser.add_argument("--stale-days", type=int, default=14,
                        help="Ab wieviel Tagen ohne Mention als stale refreshen (default 14)")
    parser.add_argument("--apply", action="store_true",
                        help="Tatsächlich last_seen auffrischen + protokollieren (Dry-Run sonst)")
    parser.add_argument("--db", default=DB_PATH,
                        help="DB-Pfad (default: Produktiv-DB). Für Tests Pfad einer Kopie angeben.")
    args = parser.parse_args()

    con = db_connect(args.db)
    # ✳ Migration-Style: stale_refresh_log anlegen, falls noch nicht vorhanden
    con.execute("""
        CREATE TABLE IF NOT EXISTS stale_refresh_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT,
            refreshed_at TEXT NOT NULL,
            old_last_seen TEXT,
            new_last_seen TEXT,
            news_count INTEGER DEFAULT 0,
            sentiment_score REAL,
            sentiment_label TEXT,
            status TEXT,
            notes TEXT
        )
    """)

    # ── Top-N nach Conviction (raw — höchste Handlungsrelevanz), watching + bought ──
    rows = con.execute("""
        SELECT w.rowid, w.ticker, w.name, w.conviction_score, w.status,
               w.last_seen, w.notes
        FROM watchlist w
        WHERE w.status IN ('watching', 'bought')
          AND w.ticker IS NOT NULL
        ORDER BY w.conviction_score DESC
        LIMIT ?
    """, (args.top,)).fetchall()

    print(f"🔁 Stale-Refresh-Queue (Top {args.top} nach Conviction)")
    print(f"   {'APPLY' if args.apply else 'DRY-RUN (keine Änderungen, --apply für echten Lauf)'}")
    print(f"   Stale-Schwelle: >{args.stale_days} Tage → Google-News-Refresh")
    print(f"{'='*60}")
    print(f"{'Ticker':10} {'Conv':>5} {'stat':>9} {'age_d':>5}  {'#News':>5} {'Sent':>5}  Ergebnis")

    today = datetime.now().strftime("%Y-%m-%d")
    to_refresh = []
    unchanged = 0
    for r in rows:
        try:
            age = (datetime.now() - datetime.strptime(r["last_seen"] or today, "%Y-%m-%d")).days
        except ValueError:
            # z.B. "20260619" (YYYYMMDD) — normalisieren
            raw = r["last_seen"] or today
            try:
                age = (datetime.now() - datetime.strptime(raw, "%Y%m%d")).days
            except ValueError:
                age = args.stale_days + 1  # nicht parsebar → als stale behandeln
        age = max(0, age)

        if age <= args.stale_days:
            unchanged += 1
            print(f"{r['ticker']:10} {r['conviction_score'] or 0:5.2f} {r['status']:>9} {age:5d}    {'–':>5} {'–':>5}  frisch (kein Refresh nötig)")
            continue

        # Google-News-Refresh (kostenlos, kein API-Key)
        try:
            news = search_news(r["ticker"], r["name"] or "")
            errors = [n for n in news if "Fehler" in n.get("title", "")]
            valid = [n for n in news if not "Fehler" in n.get("title", "") and n.get("title")]
            if errors and not valid:
                print(f"{r['ticker']:10} {r['conviction_score'] or 0:5.2f} {r['status']:>9} {age:5d}     0 {'–':>5}  ⚠ News-Fehler ({errors[0]['title'][:30]})")
                continue
            combined = " ".join(n["title"] for n in valid)
            score, neg, pos = analyze_sentiment(combined) if combined else (0.5, [], [])
            label = "bullish" if score > 0.65 else ("bearish" if score < 0.45 else "neutral")
            to_refresh.append({**dict(r), "age": age, "news": valid, "score": score,
                               "label": label, "news_count": len(valid)})
            print(f"{r['ticker']:10} {r['conviction_score'] or 0:5.2f} {r['status']:>9} {age:5d} {len(valid):5d} {score:5.2f}  → refresh ({label})")
        except Exception as e:
            print(f"{r['ticker']:10} → ⚠ Fehler: {e}")

    print(f"\n📊 {len(to_refresh)} zu refreshen (stale), {unchanged} frisch, Top {args.top} gesamt")

    if not args.apply:
        # Dry-Run — keine Schreibzugriffe
        con.close()
        if to_refresh:
            print("\nNächster Schritt bei --apply:")
            for t in to_refresh:
                print(f"  - {t['ticker']}: last_seen {t['last_seen']} → {today}, "
                      f"{t['news_count']} News, Sentiment {t['score']:.2f} ({t['label']})")
        return

    # ── APPLY: last_seen auffrischen + protokollieren ─────────────
    now_iso = datetime.now().isoformat(timespec="seconds")
    applied = 0
    for t in to_refresh:
        old = t["last_seen"]
        # Merke bestehende notes (nicht überschreiben), ergänze Refresh-Marker
        notes = t["notes"] or ""
        markers = [m for m in notes.split("|") if m.strip()] if notes else []
        if not any("stale-refresh" in m for m in markers):
            markers.append("stale-refresh")
        new_notes = "|".join(markers)
        con.execute(
            "UPDATE watchlist SET last_seen=?, notes=? WHERE rowid=?",
            (today, new_notes, t["rowid"]),
        )
        con.execute("""
            INSERT INTO stale_refresh_log
                (ticker, name, refreshed_at, old_last_seen, new_last_seen,
                 news_count, sentiment_score, sentiment_label, status, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (t["ticker"], t["name"], now_iso, old, today, t["news_count"],
              t["score"], t["label"], t["status"],
              json.dumps([n["title"] for n in t["news"][:5]])))
        applied += 1

    con.commit()
    con.close()
    print(f"\n✅ APPLY: {applied} Positionen refresht (last_seen→{today}) + protokolliert.")


if __name__ == "__main__":
    main()