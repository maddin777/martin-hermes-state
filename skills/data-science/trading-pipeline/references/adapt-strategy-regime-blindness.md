# adapt_strategy() — Regime-Blindheit

## Problem

Die Funktion `adapt_strategy()` in `signal_manager.py` (Zeile 233) passt SL/TP-Multiplikatoren REIN basierend auf Trade-Ergebnissen an — **ohne das aktuelle Marktregime zu berücksichtigen**.

```python
# Aktuell — blind:
3× Verlust → SL enger (1,5→1,0)   # Im Sideways TOD
3× Gewinn → TP weiter (2,5→4,0)   # Im Sideways unerreichbar
```

## Abwärtsspirale

```
Sideways-Markt → viele SL_HITs (normal in Range)
  → adapt_strategy: SL enger ziehen
    → noch mehr SL_HITs
      → SL noch enger (1,0×)
        → 81% SL-Rate, nur 15% TP, Portfolio −358€
```

## Was fehlt

Die Anpassung müsste vor jeder Änderung prüfen:

1. **Gesamtmarkt-Regime** (aus `regime_history`):
   - Bull → TP weiter (2,5→3,0) OK
   - Bear → SL enger (1,5→1,0) OK, Shorts bevorzugen
   - **Sideways → WEDER TP weiter NOCH SL enger!** Stattdessen min_confidence erhöhen

2. **Sektor-Regime** (14d P&L pro Sektor aus `positions`):
   - Sektor mit negativer 14d-Performance → keine neuen Entries
   - Unterschiedliche Sektoren können in unterschiedlichen Regimen sein

## Fix-Implementierung (25.06.2026)

Die `adapt_strategy()` in `signal_manager.py` wurde umgebaut auf **regime-bewusste Anpassung**:

```python
def adapt_strategy(cfg, con):
    regime, vix = get_current_regime(con)

    if cfg["consecutive_wins"] >= 3:
        if regime == "sideways":
            # TP nicht weiter machen (unerreichbar)
            min_confidence += ...  # stattdessen Qualität erhöhen
        else:
            tp_multiplier += 0.25  # normale Anpassung

    if cfg["consecutive_losses"] >= 3:
        if regime == "sideways":
            # SL NICHT enger machen (tödlich!)
            min_confidence += ...  # stattdessen Qualität erhöhen
        else:
            sl_multiplier -= 0.25  # max 1.2× (nicht 1.0×!)
```

### Drei zusätzliche Mechanismen:

1. **Regime-Awareness:** Sideways → KEINE SL/TP-Veränderung. Stattdessen wird `min_confidence` erhöht (bessere Selektion statt schlechterer Stops).

2. **VIX-basiert:** Bei VIX > 25 wird `min_confidence` auf mindestens 0.70 angehoben.

3. **SL-Untergrenze:** `max(1.2, ...)` statt `max(1.0, ...)` — das alte Minimum von 1.0× war eine der Hauptursachen der Abwärtsspirale.

4. **TP-Obergrenze:** `min(3.5, ...)` statt `min(4.0, ...)` — 4.0× TP ist selbst im Bull-Markt schwer erreichbar.

Die `strategy_config.json` wurde auf SL=1.5×, TP=2.5×, consecutive_losses=0 zurückgesetzt.

Siehe auch: `references/sector-blacklist-probation.md`