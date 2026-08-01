# 🛒 Marker-Gap Bug (fix 31.07.2026)

## Symptom

Watchlist-Header zeigt mehr "Gekauft" als 🛒-Marker in der Tabelle.
Beispiel: **Gekauft: 74** im Header, aber nur **73 🛒** in der Tabelle.

## Root Cause

Stats-Query zählt raw DB-Rows, aber die Tabelle rendert **merged** Rows
(nach canonical_tickers). Wenn `YDX.MU → NBIS` zwei bought-Einträge merged,
zählt die Query 2, die Tabelle zeigt 1 → Gap.

## Fix

### 1. Stats aus merged list statt raw DB

```python
# ALT: raw DB-Query
stats = con.execute("SELECT COUNT(*) as total, SUM(CASE WHEN status='bought'...")

# NEU: aus merged watchlist
merged_bought = sum(1 for w in watchlist if w["status"] == "bought")
stats = {"total": len(watchlist), "bought": merged_bought, ...}
```

### 2. Status-Bubble bei Merge

```python
if w["status"] == "bought" and existing.get("status") != "bought":
    existing["status"] = "bought"
```

## Verifikation

```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading && PYTHONPATH=. python3 scripts/export_watchlist.py
head -5 /root/obsidian-vault/Trading/Watchlist.md
grep -c '🛒' /root/obsidian-vault/Trading/Watchlist.md
# → Header "Gekauft: X" muss === grep-count sein
```

## Monitoring

Cron `watchlist-marker-gap-check` (ID: `53e28fdb66d4`), Mo–Fr 22:20,
no_agent Script `~/.hermes/scripts/watchlist_marker_check.py`.
Silent bei OK, Alarm bei Gap > 0.