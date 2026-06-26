# Sector Blacklist + Probation-Mechanismus

## Konzept

Sektoren mit schlechter 14d-P&L werden automatisch auf eine Blacklist gesetzt. Nach einem Cooldown ist ein Probation-Trade (50% Size) erlaubt. Bei Gewinn → Sektor frei, bei Verlust → erneuter Cooldown.

## Implementierung (signal_manager.py)

### update_sector_blacklist() — Blacklist-Update

Läuft am Anfang von `open_new_positions()`:

```python
# 14d P&L pro Sektor aggregieren
SELECT c.sector, COUNT(*) as trades, SUM(p.pnl_eur) as total_pnl, AVG(p.pnl_pct) as avg_pnl_pct
FROM positions p
JOIN companies c ON c.ticker = p.ticker
WHERE p.exit_date >= date('now', '-14 days') AND p.status = 'closed'
GROUP BY c.sector

# Blacklist-Kriterium:
# trades >= 3 UND total_pnl < 0 → auf Blacklist
```

### is_sector_allowed() — Entry-Check

Probiert beim Entry-Check für jeden Kandidaten:

| Zustand | Ergebnis |
|---------|----------|
| Nicht auf Blacklist | ✅ Freigegeben |
| Auf Blacklist, Cooldown < 14d | 🚫 **Gesperrt** |
| Auf Blacklist, Cooldown ≥ 14d, kein Probation-Versuch | 🧪 **Probation** (50% Size) |
| Probation-Trade war da → P&L positiv | ✅ **Sektor freigegeben** |
| Probation-Trade war da → P&L negativ | 🚫 **Erneuter 14d Cooldown** |

Die Blacklist wird in `strategy_config.json` persistiert (Key: `sector_blacklist`).

### Position Sizing in Probation

```python
if is_probation:
    pct = pct * cfg.get("sector_probation_size_pct", 0.5)
    # → max 7.5% des Portfolios statt 15%
```

## Beispiel

Technology wurde am 25.06. auf die Blacklist gesetzt:
- 4 Trades in 14 Tagen, −228€, −4,9% Ø
- Cooldown: 14 Tage (bis 09.07.)
- Danach: 1 Trade mit 50% Size erlaubt
- Ergebnis entscheidet über Re-Entry oder Verlängerung

## Verwandte Referenzen

- `references/adapt-strategy-regime-blindness.md` — Regime-bewusste SL/TP-Anpassung
- `references/other-sector-private-companies.md` — Sektor-Mapping für Private Companies