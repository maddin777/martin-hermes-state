"""
Exportiert die komplette Watchlist als Markdown in den Obsidian Vault
"""
import sqlite3
import json
from datetime import datetime

DB_PATH      = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
OBSIDIAN_PATH = "/root/obsidian-vault/Trading/Watchlist.md"

import os
os.makedirs(os.path.dirname(OBSIDIAN_PATH), exist_ok=True)

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

watchlist = con.execute("""
    SELECT * FROM watchlist
    WHERE status IN ('watching','bought')
    ORDER BY conviction_score DESC
""").fetchall()

stats = con.execute("""
    SELECT COUNT(*) as total,
           SUM(CASE WHEN status='watching' THEN 1 ELSE 0 END) as watching,
           SUM(CASE WHEN status='bought'   THEN 1 ELSE 0 END) as bought
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
             f"**Gekauft:** {stats['bought']}\n")
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
        f"{w['sector'] or 'Other'} | {w['mention_count']} | "
        f"{w['bullish_count']} | {w['bearish_count']} | "
        f"{conviction:.0%} | {tech} | {direction} | "
        f"{channels_str} | {w['last_seen'] or '–'} |"
    )

with open(OBSIDIAN_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"✅ Watchlist exportiert: {len(watchlist)} Einträge → {OBSIDIAN_PATH}")
