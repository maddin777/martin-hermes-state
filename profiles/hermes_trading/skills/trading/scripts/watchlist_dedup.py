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
    """
    if len(rows) <= 1:
        return 0

    # 1. Kanonischen Namen bestimmen
    names = [r["name"] for r in rows]
    # Bevorzuge kürzesten Namen der NICHT auf legal-Suffix endet
    canon = min(names, key=lambda n: (
        len(n) if not any(n.lower().endswith(s) for s in
                          ["inc", "inc.", "corp", "corp.", "ltd", "ltd.", "ag",
                           "se", "plc", "llc", "gmbh", "nv", "sa", "ab", "oy",
                           "holdings", "group", "plc", "co.", "company"])
        else len(n) + 1000,  # penalize suffixed names
        names.index(n)  # tie-breaker: first appearance
    ))
    # Nochmal check: falls ein Name den normalisierten Namen exakt matcht, den nehmen
    norm = normalize_company_name(canon)
    for n in names:
        if n.lower() == norm.lower():
            canon = n
            break

    # 2. Stats aggregieren
    merged = {}
    for col in MERGE_COLS:
        merged[col] = sum(r[col] or 0 for r in rows)

    # Channels: union aller Channels
    all_channels = set()
    for r in rows:
        chans = json.loads(r["channels"]) if r["channels"] else []
        all_channels.update(chans)
    merged["channels"] = json.dumps(sorted(all_channels))

    # Date range: earliest first_seen, latest last_seen
    merged["first_seen"] = min(r["first_seen"] for r in rows if r["first_seen"])
    merged["last_seen"]  = max(r["last_seen"] for r in rows if r["last_seen"])

    # Ticker: prefer the one that actually resolves (not a weird alternative)
    tickers = [r["ticker"] for r in rows if r["ticker"]]
    merged["ticker"] = tickers[0] if tickers else None

    # Conviction: MAX (nicht Sum – Score > 1.0 macht keinen Sinn)
    merged["conviction_score"]      = max(r["conviction_score"]      or 0 for r in rows)
    merged["conviction_score_bear"] = max(r["conviction_score_bear"] or 0 for r in rows)
    merged["conviction_score_aged"] = max(r["conviction_score_aged"] or 0 for r in rows)

    # Canonical row für id-basierte Updates
    canon_row = next((r for r in rows if r["name"] == canon), rows[0])
    canon_id  = canon_row["id"]

    # 3. Canonical Eintrag updaten (per id – robust gegen Namens-Änderungen)
    update_cols = MERGE_COLS + [
        "conviction_score", "conviction_score_bear", "conviction_score_aged",
        "channels", "first_seen", "last_seen", "ticker",
    ]
    set_parts = [f"{col}=?" for col in update_cols] + ["name=?", "status=?"]
    params    = [merged[col] for col in update_cols] + [canon, "watching", canon_id]

    con.execute(f"UPDATE watchlist SET {', '.join(set_parts)} WHERE id=?", params)

    # 4. Duplikate droppen
    dropped = 0
    for r in rows:
        if r["id"] == canon_id:
            continue
        con.execute(
            "UPDATE watchlist SET status='dropped', notes=? WHERE id=?",
            (f"merged into '{canon}' (watchlist_dedup)", r["id"])
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
        SELECT * FROM watchlist
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
        SELECT * FROM watchlist
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

def dedup_ticker_variants(con):
    """
    Phase 3: Einträge mit unterschiedlichen Tickern, die aber die gleiche
    Firma repräsentieren (z.B. NVDA + NVD.DE, SAP.DE + SAP).
    Nur konkrete bekannte Varianten mergen.
    """
    # Manuelle Paare von tickern die die gleiche Firma sind
    TICKER_GROUPS = {
        "NVDA": ["NVDA", "NVD.DE", "NVD.F"],
        "META": ["META"],
        "GOOGL": ["GOOGL", "GOOG", "ABEA.F"],
        "AMZN": ["AMZN"],
        "MSFT": ["MSFT"],
        "AAPL": ["AAPL"],
        "SAP.DE": ["SAP.DE", "SAP"],
        "IFX.DE": ["IFX.DE"],
        "MTX.DE": ["MTX.DE"],
        "SIE.DE": ["SIE.DE"],
        "ALV.DE": ["ALV.DE"],
        "CBK.DE": ["CBK.DE"],
        "DBK.DE": ["DBK.DE"],
        "BAYN.DE": ["BAYN.DE"],
        "BAS.DE": ["BAS.DE"],
        "TTWO": ["TTWO"],
        "PLTR": ["PLTR"],
        "AMD": ["AMD"],
        "INTC": ["INTC"],
        "QCOM": ["QCOM"],
        "MSTR": ["MSTR"],
        "CRWD": ["CRWD"],
        "NU": ["NU"],
        "UBER": ["UBER"],
        # Quantum Computing: Zertifikate/strukturierte Produkte auf QUBT
        "QUBT": ["QUBT", "DE000SL0FUQ7.SG"],
    }

    # Automatische Erkennung: Ticker mit Exchange-Suffix (.SG, .MU, .F, .DE, .L etc.)
    # die ISIN/WKN-artige Basis haben (>6 Zeichen vor dem Punkt = strukturiertes Produkt)
    import re
    STRUCTURED_PRODUCT_RE = re.compile(
        r'^([A-Z]{2}[0-9A-Z]{10,})\.(SG|MU|F|DE|L|PA|SW|VI|AS)$'
    )
    structured = con.execute("""
        SELECT ticker FROM watchlist
        WHERE status='watching' AND ticker IS NOT NULL
    """).fetchall()
    for row in structured:
        t = row["ticker"]
        m = STRUCTURED_PRODUCT_RE.match(t)
        if m:
            # Strukturiertes Produkt erkannt — in dropped überführen (kein echter Aktien-Ticker)
            dropped = con.execute("""
                UPDATE watchlist SET status='dropped', notes=?
                WHERE ticker=? AND status='watching'
            """, (f"strukturiertes Produkt / Zertifikat erkannt: {t}", t)).rowcount
            if dropped:
                print(f"  🗑 Strukturiertes Produkt entfernt: {t}", flush=True)
    con.commit()
    total = 0
    for canonical_ticker, variants in TICKER_GROUPS.items():
        if len(variants) <= 1:
            continue
        rows = con.execute("""
            SELECT * FROM watchlist
            WHERE status='watching' AND ticker IN ({})
            ORDER BY mention_count DESC
        """.format(",".join("?" for _ in variants)), variants).fetchall()
        if len(rows) <= 1:
            continue
        # Ticker auf canonical setzen vor merge
        for r in rows:
            if r["ticker"] != canonical_ticker:
                con.execute("UPDATE watchlist SET ticker=? WHERE id=?", (canonical_ticker, r["id"]))
        con.commit()
        # Erneutes Laden mit einheitlichem Ticker
        rows = con.execute("""
            SELECT * FROM watchlist
            WHERE status='watching' AND ticker=?
            ORDER BY mention_count DESC
        """, (canonical_ticker,)).fetchall()
        if len(rows) > 1:
            total += merge_group(con, rows, canonical_ticker, "ticker-variant")
    con.commit()
    return total

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
    total += dedup_ticker_variants(con)  # erst ticker-varianten angleichen
    total += dedup_ticker(con)           # dann ticker-basiert mergen
    total += dedup_name(con)             # dann name-basiert (ohne ticker)

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