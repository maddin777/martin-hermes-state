# Signal-Kalibrierung nach avg_pnl_per_trade

Seit 30.07.2026. Kalibriert Signalstärke zwischen lauten unpräzisen und leisen präzisen Quellen.

## Funktion: `get_channel_calibration(con)`

Liest `avg_pnl_per_trade` aus `source_registry` und wandelt in Faktor [0.3, 1.5]:

| avg_pnl | Faktor | Bedeutung |
|---------|--------|-----------|
| ≥ +50€  | 1.5x   | Starke Quelle |
| ≥ +20€  | 1.2x   | Gute Quelle |
| ≥ -5€   | 1.0x   | Neutral |
| ≥ -20€  | 0.7x   | Schwache Quelle |
| < -20€  | 0.3x   | Schlechte Quelle |
| Keine Daten | 1.0x | Unbekannt |

## Integration

Alle drei Conviction-Funktionen akzeptieren optionalen `calibration`-Parameter:

- `calculate_conviction()` — multipliziert jedes Channel-Weight mit calibration-Faktor
- `calculate_conviction_bear()` — selbe Logik
- `calculate_conviction_aged()` — selbe Logik im Time-Decay-Pfad

Der Faktor wird auf das Channel-Weight multipliziert:
```python
chw = (channel_weights or {}).get(r["channel"], 1.0)
chw *= (calibration or {}).get(r["channel"], 1.0)
```

## Effekt

Eine leise, präzise Quelle (5 Mentions, +50€/Trade) bekommt 1.5x Gewicht pro Mention,
eine laute, mittelmäßige Quelle (100 Mentions, -10€/Trade) nur 0.7x.
Die 5 präzisen Mentions wiegen damit so viel wie ~10 normale — die 100 lauten
Mentions werden auf ~70 normalisiert. Lautstärke allein überstimmt Qualität nicht mehr.

## Output

Im `watchlist_manager.py`-Lauf:
```
📐 Quellen-Kalibrierung: 12 Quellen, 3 mit abweichendem Faktor
```

## Code

```python
def get_channel_calibration(con):
    try:
        rows = con.execute("""
            SELECT display_name, avg_pnl_per_trade
            FROM source_registry
            WHERE status IN ('active', 'probation') AND enabled = 1
              AND avg_pnl_per_trade IS NOT NULL
        """).fetchall()
        result = {}
        for r in rows:
            pnl = r["avg_pnl_per_trade"]
            if pnl >= 50.0:         result[r["display_name"]] = 1.5
            elif pnl >= 20.0:       result[r["display_name"]] = 1.2
            elif pnl >= -5.0:       result[r["display_name"]] = 1.0
            elif pnl >= -20.0:      result[r["display_name"]] = 0.7
            else:                   result[r["display_name"]] = 0.3
        return result
    except Exception:
        return {}
```
