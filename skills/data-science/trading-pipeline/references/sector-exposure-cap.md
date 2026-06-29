# Sektor-Exposure-Cap (70%)

Eingeführt: 28.06.2026  
Config: `strategy_config.json: max_sector_exposure_pct: 0.70`

## Motivation

Die Signalquellen (YouTube, RSS, Twitter) sind stark tech-lastig. Das alte
Limit von **max 2 Positionen pro Sektor** begrenzte Tech auf ~20–25%
Portfolio-Anteil, selbst wenn die besten Signale aus Tech kamen. Neues Limit:
**max 70% Portfolio-Exposure pro Sektor** — ein Sektor kann dominant sein.

## Logik

Prüfung in `signal_manager.py`, Funktion `open_new_positions()`:

### Vor dem Umbau (alt)
```python
# Sektor-Cap: max 2 Positionen pro Sektor (VOR Sizing)
sector_counts = {}
# ... COUNT(*) aus DB ...
if sector_counts.get(ticker_sector, 0) >= MAX_POSITIONS_PER_SECTOR:
    continue
```

### Nach dem Umbau (neu)
```python
# Sektor-Exposure: SUM(position_size) aus DB
sector_exposure = {}
# ... SUM(p.position_size) ...
max_sector_exposure = cfg.get("max_sector_exposure_pct", 0.70)
current_exposure = sector_exposure.get(ticker_sector, 0)

# Prüfung NACH Sizing mit tatsächlicher position_size
new_exposure_pct = (current_exposure + position_size) / portfolio_value
if new_exposure_pct > max_sector_exposure:
    continue

# Post-Entry: exposure statt count erhöhen
sector_exposure[ticker_sector] += position_size
```

### Wichtige Design-Entscheidungen

| Aspekt | Entscheidung | Begründung |
|--------|-------------|------------|
| Prüf-Zeitpunkt | **Nach Sizing** | Wir kennen die tatsächliche Positionsgröße erst nach Vola-bereinigung |
| Einheit | **EUR-Exposure**, nicht Anzahl | 2 große Positionen können mehr Exposure haben als 5 kleine |
| Vererbung | `sector_counts[ticker_sector] += 1` → `+ position_size` | Konsequent Exposure-basiert |

### Interaktion mit anderen Filtern

1. **Sector Blacklist** (vor Exposure-Check): Sektoren mit negativer 14d-P&L
   werden 14 Tage gesperrt → greift vor dem Exposure-Check
2. **Correlation Filter** (vor Sizing): Prüft Pearson > 0.70 mit offenen
   Positionen → verhindert Klumpenrisiko auch innerhalb eines Sektors
3. **Budget-Limit** (vor Sizing): max 70% investiert → tech-lastiges Portfolio
   könnte schneller am Gesamt-Budget scheitern als am Sektor-Limit

## Erklaerung.md

Der Eintrag in der Entry-Hierarchie (Punkt 7) wurde aktualisiert:
> **Sektor-Exposure-Cap:** max 70% des Portfolios pro Sektor
> (via `strategy_config.json: max_sector_exposure_pct`, geprüft NACH Sizing
> mit tatsächlicher Positionsgröße)