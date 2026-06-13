"""
Exportiert die komplette Watchlist als Markdown in den Obsidian Vault.
Nutzt canonical_tickers-Tabelle zum Zusammenführen von Duplikaten.
"""
import sqlite3
import json
from datetime import datetime


import os
from config import DB_PATH, OBSIDIAN_WATCHLIST_PATH
os.makedirs(os.path.dirname(OBSIDIAN_WATCHLIST_PATH), exist_ok=True)

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

# ── Canonical Ticker Map laden ─────────────────────────────────────────
ct_map = {}
try:
    for row in con.execute(
        "SELECT source_ticker, target_ticker FROM canonical_tickers"
    ).fetchall():
        ct_map[row["source_ticker"]] = row["target_ticker"]
except Exception:
    pass  # Tabelle existiert noch nicht → kein Merge

# ── Rohdaten laden ─────────────────────────────────────────────────────
raw = con.execute("""
    SELECT w.*,
           COALESCE(c.sector, 'Other') AS company_sector
    FROM watchlist w
    LEFT JOIN companies c ON c.ticker = w.ticker
    WHERE w.status IN ('watching','bought')
      AND (w.conviction_score >= 0.76 OR w.status = 'bought')
    ORDER BY w.conviction_score DESC
""").fetchall()

# ── Duplikate mit canonical_ticker mergen ─────────────────────────────
# Wenn zwei Einträge denselben canonical-target haben:
# höheren conviction_score behalten, mentions addieren
merged = {}  # canonical_ticker → dict
for w in raw:
    raw_ticker = w["ticker"] or ""
    canonical = ct_map.get(raw_ticker, raw_ticker)

    if canonical in merged:
        existing = merged[canonical]
        # Höheren Conviction-Score behalten
        existing_conv = existing.get("conviction_score") or 0
        current_conv = w["conviction_score"] or 0
        if current_conv > existing_conv:
            existing["name"] = w["name"]
            existing["company_sector"] = w["company_sector"]
            existing["tech_score"] = w["tech_score"]
            existing["tech_direction"] = w["tech_direction"]
            existing["last_seen"] = w["last_seen"]
        # Mentions addieren
        existing["mention_count"] = (existing.get("mention_count") or 0) + (w["mention_count"] or 0)
        existing["bullish_count"] = (existing.get("bullish_count") or 0) + (w["bullish_count"] or 0)
        existing["bearish_count"] = (existing.get("bearish_count") or 0) + (w["bearish_count"] or 0)
        # Channels mergen
        new_chans = set(json.loads(existing.get("channels_raw") or "[]"))
        for c in json.loads(w["channels"] or "[]"):
            new_chans.add(c)
        existing["channels_raw"] = json.dumps(list(new_chans))
        existing["merge_note"] = f"⚠️ Mergeb mit {raw_ticker}"
    else:
        merged[canonical] = {
            "name": w["name"],
            "canonical_ticker": canonical,
            "raw_ticker": raw_ticker,
            "company_sector": w["company_sector"],
            "mention_count": w["mention_count"],
            "bullish_count": w["bullish_count"],
            "bearish_count": w["bearish_count"],
            "conviction_score": w["conviction_score"],
            "tech_score": w["tech_score"],
            "tech_direction": w["tech_direction"],
            "channels_raw": w["channels"] or "[]",
            "last_seen": w["last_seen"],
            "status": w["status"],
            "merge_note": None,
        }

watchlist = list(merged.values())
watchlist.sort(key=lambda x: x["conviction_score"] or 0, reverse=True)

# ── Statistiken ───────────────────────────────────────────────────────
stats = con.execute("""
    SELECT COUNT(*) as total,
           SUM(CASE WHEN status='watching' THEN 1 ELSE 0 END) as watching,
           SUM(CASE WHEN status='bought'   THEN 1 ELSE 0 END) as bought,
           SUM(CASE WHEN status='watching' AND conviction_score >= 0.76
                    THEN 1 ELSE 0 END) as high_conviction
    FROM watchlist
    WHERE status IN ('watching','bought')
""").fetchone()

con.close()

now = datetime.now().strftime("%d.%m.%Y %H:%M")

lines = []
lines.append("# Trading Watchlist")
lines.append(f"*Exportiert: {now}*\n")
lines.append(f"**Gesamt:** {stats['total']} | "
             f"**Beobachtet:** {stats['watching']} | "
             f"**Gekauft:** {stats['bought']} | "
             f"**≥76% Conviction:** {stats['high_conviction']}\n")
lines.append(f"*Filter: conviction ≥ 76% oder bereits gekauft*"
             f" | *Canonical-Merge aktiv ({len(ct_map)} Regeln)*\n")
lines.append("---\n")

# Tabellen-Header
lines.append("| # | Unternehmen | Ticker | Sektor | Mentions | Bull↑ | Bear↓ | Conviction | Tech | Richtung | Kanäle | Zuletzt |")
lines.append("|---|-------------|--------|--------|----------|-------|-------|------------|------|----------|--------|---------|")

for i, w in enumerate(watchlist, 1):
    channels_raw = json.loads(w.get("channels_raw") or "[]")
    channels_str = ", ".join(list(set(channels_raw))[:3])
    conviction = w["conviction_score"] or 0
    tech = f"{w['tech_score']:.2f}" if w["tech_score"] else "–"
    direction = w["tech_direction"] or "–"
    status_icon = "🛒" if w["status"] == "bought" else ""
    ticker_display = w["canonical_ticker"]
    if w["merge_note"]:
        ticker_display += "*"
    lines.append(
        f"| {i} | {status_icon}{w['name']} | {ticker_display} | "
        f"{w['company_sector']} | {w['mention_count']} | "
        f"{w['bullish_count']} | {w['bearish_count']} | "
        f"{conviction:.0%} | {tech} | {direction} | "
        f"{channels_str} | {w['last_seen'] or '–'} |"
    )

with open(OBSIDIAN_WATCHLIST_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

merged_count = sum(1 for w in watchlist if w["merge_note"])
print(f"✅ Watchlist exportiert: {len(watchlist)} Einträge → {OBSIDIAN_WATCHLIST_PATH}"
      f" ({merged_count} gemerged, {len(ct_map)} canonical rules)")