# Sector Probation Check

**Cron:** `sector-probation-check` (dda431ae4b55), Mo–Fr 09:30
**Script:** `/root/.hermes/profiles/hermes_trading/skills/trading/scripts/sector_probation_check.py`
**Ablage:** Trading-Profil `scripts/`

## Problem

Sektoren landen auf der Blacklist (via `update_sector_blacklist()` in `signal_manager.py`). Nach Ablauf des Cooldowns (Default 14 Tage) öffnet sich ein Probation-Fenster für genau einen Trade. Wird dieser Trade nie gemacht, bleibt der Sektor in einem "ewigen Probation-Fenster" — weder gesperrt noch aktiv genutzt.

## Lösung

Der Cron-Job prüft täglich:
1. **DB `sector_blacklist`**: Sektoren mit `probation_status IS NULL` und abgelaufenem Cooldown
2. **Watchlist + Companies JOIN**: Top-Kandidaten ≥70% Conviction im Sektor
3. **Offene Positionen**: Bereits gekauft im Sektor?
4. **Telegram-Alert**: Wenn Probation-Fenster offen + kein Trade gemacht

## DB-Query (Core)

```sql
SELECT w.ticker, w.name, w.conviction_score,
       w.tech_direction, w.tech_score
FROM watchlist w
JOIN companies c ON c.ticker = w.ticker
WHERE c.sector = ?
  AND w.status NOT IN ('removed', 'closed', 'bought')
  AND w.conviction_score >= 0.70
ORDER BY w.conviction_score DESC
LIMIT 5
```

## Alert-Format

```
⚠️ Probation-Fenster: Industrials
Cooldown seit 10 Tagen abgelaufen (2026-07-25), noch kein Probation-Trade.
Top-Kandidat: RTX (95%)
50% Size, min 14d Haltedauer empfohlen.
```

## Manueller Test

```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading && \
  PYTHONPATH=. python3 scripts/sector_probation_check.py
```

## Cron-Schedule

- Hermes Cron `dda431ae4b55`
- Mo–Fr 09:30 UTC
- Deliver: local (Script sendet eigenen Telegram-Alert)
- Skills: trading-pipeline