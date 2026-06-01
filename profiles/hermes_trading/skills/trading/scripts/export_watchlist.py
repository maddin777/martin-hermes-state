"""
Exportiert die komplette Watchlist als Markdown in den Obsidian Vault
"""
import sqlite3
import json
from datetime import datetime


import os
from config import DB_PATH, OBSIDIAN_WATCHLIST_PATH
os.makedirs(os.path.dirname(OBSIDIAN_WATCHLIST_PATH), exist_ok=True)

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

watchlist = con.execute("""
    SELECT w.*,
           COALESCE(c.sector, 'Other') AS company_sector
    FROM watchlist w
    LEFT JOIN companies c ON c.ticker = w.ticker
    WHERE w.status IN ('watching','bought')
      AND (w.conviction_score >= 0.76 OR w.status = 'bought')
    ORDER BY w.conviction_score DESC
""").fetchall()

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
lines.append(f"*Filter: conviction ≥ 76% oder bereits gekauft*\n")
lines.append("---\n")

# Tabellen-Header
lines.append("| # | Unternehmen | Ticker | Sektor | Mentions | Bull↑ | Bear↓ | Conviction | Tech | Richtung | Kanäle | Zuletzt |")
lines.append("|---|-------------|--------|--------|----------|-------|-------|------------|------|----------|--------|---------|")

for i, w in enumerate(watchlist, 1):
    channels = json.loads(w["channels"] or "[]")
    channels_str = ", ".join(list(set(channels))[:3])
    conviction = w["conviction_score"] or 0
    tech = f"{w['tech_score']:.2f}" if w["tech_score"] else "–"
    direction = w["tech_direction"] or "–"
    status_icon = "🛒" if w["status"] == "bought" else ""
    lines.append(
        f"| {i} | {status_icon}{w['name']} | {w['ticker'] or '?'} | "
        f"{w['company_sector']} | {w['mention_count']} | "
        f"{w['bullish_count']} | {w['bearish_count']} | "
        f"{conviction:.0%} | {tech} | {direction} | "
        f"{channels_str} | {w['last_seen'] or '–'} |"
    )

with open(OBSIDIAN_WATCHLIST_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"✅ Watchlist exportiert: {len(watchlist)} Einträge → {OBSIDIAN_WATCHLIST_PATH}")
