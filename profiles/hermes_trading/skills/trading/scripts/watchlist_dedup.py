#!/usr/bin/env python3
"""
Watchlist Dedup — dedupliziert die watchlist-Tabelle auf zwei Ebenen:
  1. Ticker-basiert (gleicher Ticker → merge)
  2. Name-basiert (normalisierte Names → merge)

Konsolidiert Conviction, Mentions, Channels und droppt Duplikate.
Kann standalone oder als Cron (z.B. wöchentlich) laufen.
"""
import sqlite3, json, os, sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401

# Normalisierungslogik zentral in company_normalizer.py (DRY, vereint mit watchlist_manager.py).
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading/scripts")
from company_normalizer import (

    normalize_company_name, NORMALIZE_ALIASES,
    LEGAL_SUFFIX_RE, BRACKET_NOTE_RE
)
from config import DB_PATH

# Spalten die beim Zusammenführen summiert werden (nur Zähler, keine Scores)
MERGE_COLS = [
    "mention_count", "bullish_count", "bearish_count", "neutral_count",
]

def merge_group(con, rows, key, key_label):
    """Merge eine Gruppe von Duplikaten in einen kanonischen Eintrag.
    rows: Liste von sqlite3.Row-Dicts (alle mit status='watching')
    key: Beschriftung für Logging
    Nutzt rowid statt id, da viele Watchlist-Einträge id=NULL haben.
    """
    if len(rows) <= 1:
        return 0

    # 1. Kanonischen Namen bestimmen
    names = [r["name"] for r in rows]
    canon = min(names, key=lambda n: (
        len(n) if not any(n.lower().endswith(s) for s in
                          ["inc", "inc.", "corp", "corp.", "ltd", "ltd.", "ag",
                           "se", "plc", "llc", "gmbh", "nv", "sa", "ab", "oy",
                           "holdings", "group", "plc", "co.", "company"])
        else len(n) + 1000,
        names.index(n)
    ))
    norm = normalize_company_name(canon)
    for n in names:
        if n.lower() == norm.lower():
            canon = n
            break

    # rowid des kanonischen Eintrags ermitteln
    canon_row = next((r for r in rows if r["name"] == canon), rows[0])
    canon_rowid = canon_row["rowid"] or canon_row["id"]

    # 2. Stats aggregieren
    merged = {}
    for col in MERGE_COLS:
        merged[col] = sum(r[col] or 0 for r in rows)
    all_channels = set()
    for r in rows:
        chans = json.loads(r["channels"]) if r["channels"] else []
        all_channels.update(chans)
    merged["channels"] = json.dumps(sorted(all_channels))
    merged["first_seen"] = min(r["first_seen"] for r in rows if r["first_seen"])
    merged["last_seen"]  = max(r["last_seen"] for r in rows if r["last_seen"])
    tickers = [r["ticker"] for r in rows if r["ticker"]]
    merged["ticker"] = tickers[0] if tickers else None
    merged["conviction_score"]      = max(r["conviction_score"]      or 0 for r in rows)
    merged["conviction_score_bear"] = max(r["conviction_score_bear"] or 0 for r in rows)
    merged["conviction_score_aged"] = max(r["conviction_score_aged"] or 0 for r in rows)

    # 3. Canonical per rowid updaten (robust gegen id=NULL)
    update_cols = MERGE_COLS + [
        "conviction_score", "conviction_score_bear", "conviction_score_aged",
        "channels", "first_seen", "last_seen", "ticker",
    ]
    set_parts = [f"{col}=?" for col in update_cols] + ["name=?", "status=?"]
    params    = [merged[col] for col in update_cols] + [canon, "watching", canon_rowid]

    if canon_rowid:
        con.execute(f"UPDATE watchlist SET {', '.join(set_parts)} WHERE rowid=?", params)
    else:
        con.execute(f"UPDATE watchlist SET {', '.join(set_parts)} WHERE name=? AND ticker=?",
                    params[:-1] + [canon_row["ticker"]])

    # 4. Duplikate per rowid droppen
    dropped = 0
    for r in rows:
        rid = r["rowid"] or r["id"]
        if rid == canon_rowid:
            continue
        if rid:
            con.execute(
                "UPDATE watchlist SET status='dropped', notes=? WHERE rowid=?",
                (f"merged into '{canon}' (watchlist_dedup)", rid)
            )
            dropped += 1

    print(f"  🔗 {len(rows)} → '{canon}'  ({key_label}: {key})  "
          f"Conv:{merged['conviction_score']:.2f} Mentions:{merged['mention_count']} "
          f"Dropped:{dropped}", flush=True)
    return dropped

# ── Hauptlogik ────────────────────────────────────────────────────────

def dedup_ticker(con):
    """Phase 1: Gleicher Ticker → merge."""
    rows = con.execute("""
        SELECT rowid, * FROM watchlist
        WHERE status='watching' AND ticker IS NOT NULL
        ORDER BY ticker, mention_count DESC
    """).fetchall()
    groups = {}
    for r in rows:
        t = r["ticker"].strip().upper()
        groups.setdefault(t, []).append(r)
    total = 0
    for ticker, group in groups.items():
        total += merge_group(con, group, ticker, "ticker")
    con.commit()
    return total

def dedup_name(con):
    """Phase 2: Normalisierter Name → merge (für Einträge OHNE Ticker)."""
    rows = con.execute("""
        SELECT rowid, * FROM watchlist
        WHERE status='watching' AND ticker IS NULL
        ORDER BY mention_count DESC
    """).fetchall()
    groups = {}
    for r in rows:
        norm = normalize_company_name(r["name"]).lower()
        groups.setdefault(norm, []).append(r)
    total = 0
    for norm, group in groups.items():
        if len(group) <= 1:
            continue
        total += merge_group(con, group, norm[:40], "name")
    con.commit()
    return total

def _ticker_priority(ticker):
    """
    Bewertet einen Ticker nach Börsen-Herkunft.
    Rückgabe: Zahl (niedriger = besser)
    0 = US-Primär (kein Suffix, kurz)
    1 = US-ADR (endet auf Y)
    2 = EU-Primär (.DE, .PA, .AS, .HE etc.)
    3 = London (.L, .IL)
    4 = Sonstige (.MU, .F, .SG, .BE etc.)
    5 = Strukturierte Produkte / ISIN-WKN-Konstrukte
    """
    if not ticker:
        return 99
    import re
    # Strukturierte Produkte: ISIN-ähnlich (2 Buchstaben + 10+ Zeichen) + Exchange-Suffix
    if re.match(r'^[A-Z]{2}[0-9A-Z]{10,}\.(SG|MU|F|DE|L|PA|SW|VI|AS)$', ticker):
        return 5
    # ISIN-ähnlich ohne Punkt
    if re.match(r'^[A-Z]{2}[0-9A-Z]{10,}$', ticker):
        return 5
    # Exchange-Suffix erkennen
    suffix = ticker.split('.')[-1] if '.' in ticker else ''
    if not suffix:
        # Kein Suffix → US-Primär (TRI, TGT, BLK) oder japanisch/koreanisch (.T/.KS ohne Punkt?)
        if ticker.isalpha() and len(ticker) <= 5:
            return 0
        # Zahlen-Dominiert (006400.KS, 6752.T) — asiatisch
        if ticker[0].isdigit():
            return 4
        return 1
    suffix = suffix.upper()
    # US ADRs enden oft auf Y
    if suffix == 'Y' and len(ticker) <= 5:
        return 1
    # EU-Primärbörsen
    if suffix in ('DE', 'PA', 'AS', 'HE', 'BR', 'VI', 'SW', 'ST', 'CO'):
        return 2
    # London
    if suffix in ('L', 'IL'):
        return 3
    # Deutsche Nebenbörsen / Sonstige
    if suffix in ('MU', 'F', 'SG', 'BE', 'DU', 'BM', 'HA', 'HM'):
        return 4
    # Toronto / Australien / andere
    if suffix in ('TO', 'V', 'AX', 'XA'):
        return 4
    return 4


def dedup_by_name(con):
    """
    Phase 3 (ersetzt statische TICKER_GROUPS):
    Findet Watchlist-Einträge mit gleichem Namen aber unterschiedlichen Tickern.
    Merged sie und behält den Ticker mit der höchsten Priorität (US > EU > LSE > Strukturiert).
    """
    rows = con.execute("""
        SELECT rowid, * FROM watchlist
        WHERE status='watching' AND ticker IS NOT NULL
        ORDER BY name, mention_count DESC
    """).fetchall()

    groups = {}
    for r in rows:
        groups.setdefault(r["name"], []).append(r)

    total_dropped = 0
    for name, group in groups.items():
        if len(group) <= 1:
            continue
        # Ticker-Priorität bestimmen
        best = min(group, key=lambda r: _ticker_priority(r["ticker"]))
        if all(r["ticker"] == best["ticker"] for r in group):
            continue  # Alle haben den gleichen besten Ticker → kein Merge nötig

        print(f"  🔗 {name}: {[r['ticker'] for r in group]} → {best['ticker']} "
              f"(Prio:{_ticker_priority(best['ticker'])})", flush=True)
        dropped = merge_group(con, group, name, "name")
        total_dropped += dropped
    con.commit()
    return total_dropped

def main():
    print("🧹 Watchlist Dedup gestartet", flush=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Bestand vorher
    before = con.execute(
        "SELECT COUNT(*) FROM watchlist WHERE status='watching'"
    ).fetchone()[0]

    print(f"  Vorher: {before} watching entries", flush=True)

    total = 0
    total += dedup_by_name(con)            # Phase 3: Name-basiert (US > EU > LSE)
    total += dedup_ticker(con)             # Phase 1: Ticker-basiert mergen
    total += dedup_name(con)               # Phase 2: Name-basiert (ohne ticker)

    # Nachher
    after = con.execute(
        "SELECT COUNT(*) FROM watchlist WHERE status='watching'"
    ).fetchone()[0]
    still_watching = after

    print(f"\n  Ergebnis: {before} → {after} watching  (-{before - after})", flush=True)
    print(f"  🗑 {total} Duplikate gedroppt", flush=True)

    # Unresolved ticker report
    unresolved = con.execute("""
        SELECT name, mention_count, conviction_score
        FROM watchlist
        WHERE status='watching' AND ticker IS NULL
        ORDER BY mention_count DESC LIMIT 15
    """).fetchall()
    if unresolved:
        print(f"\n❓ Noch {len(unresolved)} watching ohne Ticker:", flush=True)
        for u in unresolved:
            print(f"   {u['name']:30} {u['mention_count']:4}x  Conv:{u['conviction_score']:.2f}", flush=True)

    # Top 3 merge groups report
    print(f"\n  Noch {still_watching} watching entries in Watchlist", flush=True)
    print("✅ Watchlist Dedup abgeschlossen", flush=True)

    con.close()

if __name__ == "__main__":
    main()