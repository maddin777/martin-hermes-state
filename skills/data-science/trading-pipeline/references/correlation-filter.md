# Correlation Filter — Entry Guard für korrelierte Positionen

Hinzugefügt: 11.06.2026  
Implementiert in: `signal_manager.py`  
Technik: Pearson-Korrelation der 60-Tage-Tagesrenditen, gecached 30min

## Zweck

Verhindert dass neue Positionen eröffnet werden, die mit bestehenden offenen Positionen gleicher Richtung zu stark korreliert sind. Schützt vor gehebelter Exposure durch korrelierte Assets.

## Schwellwert

- `max_correlation: 0.70` (absolut, positive + negative Korrelation)
- Überschreitung blockiert den Entry
- Nur **gleichgerichtete** Positionen werden geprüft (LONG↔LONG, SHORT↔SHORT).  
  LONG↔SHORT ist ein natürlicher Hedge und wird nicht gefiltert.

## Implementierung

### Cache-Architektur

```python
_CORR_CACHE: dict = {}           # frozenset(t1,t2) → (timestamp, correlation)
_CORR_TTL = 1800                 # 30 Minuten
```

- **Key:** `frozenset([t1, t2])` — order-unabhängig, speichert jedes Paar nur einmal
- **TTL:** 30 Minuten — weit genug für Pipeline-Läufe (04:00–07:00), kurz genug für taggleiche Updates
- **Struktur:** Modul-globales Dict (lebt für Prozessdauer, Cron-Job ist kurzlebig)

### yfinance MultiIndex-Handling

```python
import pandas as pd
df = yf.download([t1, t2], period="60d", interval="1d",
                 progress=False, auto_adjust=True)

if isinstance(df.columns, pd.MultiIndex):
    close = df["Close"]           # MultiIndex: (Price, Ticker) — Close = level 0
else:
    close = df[["Close"]] if "Close" in df else df
```

**Wichtig:** yfinance gibt bei Mehrfach-Ticker-Downloads einen **MultiIndex** auf den Columns zurück. `df["Close"]` selektiert alle Close-Spalten. Ohne MultiIndex-Check crasht der Zugriff.

### Berechnung

```python
r1 = close.iloc[:, 0].pct_change().dropna()
r2 = close.iloc[:, 1].pct_change().dropna()
corr = float(r1.corr(r2))
```

- Benötigt min. 15 Datenpunkte (von 60 Tagen) sonst `None`
- `pct_change()` → Tagesrenditen → `corr()` → Pearson
- `float()` cast — corr() gibt numpy.float64 zurück

## Einbindung im Entry-Flow

Eingefügt in `open_new_positions()`:

```
12. Correlation-Filter → check_correlation_with_open()
    → prüft neue Ticker gegen alle offenen Positionen gleicher Richtung
    → bei Korrelation > 0.70: Print + continue
```

## Verhalten bei Fehlern

- yfinance-Fehler (Timeouts, delisted ticker) → Exception → `return None` → Filter ist **permissiv** (lässt durch)
- Nur `None`-Ergebnisse → kein Block
- Korrelation kann nicht berechnet werden → Entry erlaubt