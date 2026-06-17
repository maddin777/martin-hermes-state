# Weekly Trend Filter — Entry Gate gegen den Trend

Hinzugefügt: 11.06.2026
Pipeline: `utils.py` → `watchlist_manager.py` → `signal_manager.py`

## Zweck

Blockiert Entries die gegen den übergeordneten weekly Trend laufen. 
Multi-Day Haltedauer (5-14 Tage) bedeutet: wenn der weekly Trend bearish ist, kämpft ein LONG jede Woche uphill. 

**Regel:** Don't fight the tape. Weekly EMA20 = Trendrichtung.

| Weekly Trend | Erlaubt | Geblockt |
|-------------|---------|----------|
| `bullish`   | LONG    | SHORT    |
| `bearish`   | SHORT   | LONG     |
| `neutral`   | Beide   | —        |

## Implementierung

### Schritt 1: Extraktion in `get_technical_score()` (utils.py)

```python
close_w = close.resample('W').last()      # daily → weekly
weekly_trend = "neutral"
if len(close_w) > 20:
    ema20_w = ta.ema(close_w, length=20)
    if close_w.iloc[-1] > ema20_w.iloc[-1]:
        weekly_trend = "bullish"
    elif ...:
        weekly_trend = "bearish"
```

Rückgabe: Neues Feld `weekly_trend` im Dict (zusätzlich zu score/confidence/direction).

### Schritt 2: Speicherung in watchlist-Tabelle (watchlist_manager.py)

- Migration: `ALTER TABLE watchlist ADD COLUMN weekly_trend TEXT DEFAULT 'neutral'`
- Tech-Update-SQL: `UPDATE watchlist SET tech_score=?, tech_direction=?, weekly_trend=?`

### Schritt 3: Filter in `open_new_positions()` (signal_manager.py)

```python
wt = c["weekly_trend"] if "weekly_trend" in c.keys() else "neutral"
if wt == "bearish" and direction == "LONG":
    print(f"  📉 {c['name']}: Weekly Trend BEARISH → LONG geblockt")
    continue
if wt == "bullish" and direction == "SHORT":
    print(f"  📈 {c['name']}: Weekly Trend BULLISH → SHORT geblockt")
    continue
```

**⚠️ Achtung `sqlite3.Row`:** `c` ist ein `sqlite3.Row`-Objekt, KEIN dict. `c.get("key")` crasht mit `AttributeError`. Siehe `references/sqlite3-row-get-pitfall.md`.

## Platz in der Entry-Hierarchie

Eingefügt als Schritt 13:
```
12. Earnings-Blackout: 5 Tage vor Earnings
13. Weekly Trend Filter: Weekly EMA20 = Trendrichtung. BEARISH → keine LONGs. BULLISH → keine SHORTs.
14. Correlation Filter: Pearson-Korrelation > 0.70 blockiert Entry
```

## Abgrenzung

- **Nicht** ein soft weighting im tech_score (der weekly Trend war schon als ±1 von 10 Punkten drin)
- **Hartes Gate:** Entries gegen den Trend werden komplett geblockt, nicht nur runtergewichtet
- **Neutral-Trend** (Preis nahe EMA20 weekly, kein klares Signal) erlaubt beide Richtungen

## Warum nicht 15min / Intraday

Hierarchische Timeframe-Strategie (daily = Entry, weekly = Trendfilter) statt Multi-Timeframe im Intraday-Bereich:

- Unsere Haltedauer ist 5-14 Tage → kein 15min Mean-Reversion-Setup sinnvoll
- 15min-Trading braucht Hebel, TR-Kosten killen die Edge bei 1x
- Pipeline läuft 1x täglich morgens, kein Markt-Daemon