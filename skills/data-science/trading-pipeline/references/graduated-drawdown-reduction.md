# Graduated Drawdown Reduction

## Problem

Der alte Binary-Stopp (`no_entry` bei ≥15% Drawdown) erzeugte eine **Heilungsfalle**:

```
Drawdown > 15% → keine neuen Trades
→ Laufender Trade schließt im SL → Drawdown steigt auf 16-17%
→ Immer noch keine neuen Trades
→ Drawdown bleibt für immer eingefroren
```

## Lösung: Dreistufige Graduierung

Statt komplettem Stopp werden drei Parameter abhängig vom Drawdown-Level angepasst:

| Parameter | Wirkung | Implementiert in |
|-----------|---------|-----------------|
| `size_factor` | Multipliziert den Positionsgrößen-Prozentsatz (`pct`) | Position Sizing, nach VIX + Probation |
| `min_confidence` | Erhöht die Mindest-Tech-Score für Watchlist-Kandidaten | DB-Query in `candidates_long` |
| `max_positions` | Begrenzt die maximale Anzahl offener Positionen | `base_max` vor Regime-Caps |

## Implementierung

### `check_drawdown()` — Rückgabe

```python
def check_drawdown(con):
    # ... (Berechnung wie gehabt) ...
    
    # Graduierte Reduzierung statt Binary-Stopp
    if drawdown >= 0.25:
        return drawdown, "close_all", {"size_factor": 0.0, "min_confidence": 1.0, "max_positions": 0}
    elif drawdown >= 0.15:
        return drawdown, "ok", {"size_factor": 0.50, "min_confidence": 0.80, "max_positions": 4}
    elif drawdown >= 0.12:
        return drawdown, "ok", {"size_factor": 0.75, "min_confidence": 0.75, "max_positions": 6}
    else:
        return drawdown, "ok", {"size_factor": 1.0, "min_confidence": 0.70, "max_positions": 8}
```

### `open_new_positions()` — Drei Anwendungspunkte

**1. Max-Positionen (Zeile ~1022):**
```python
base_max = dd_max_positions  # Vom Drawdown bestimmt (12%-Stufen)
```

**2. Confidence-Schwelle (Zeile ~1132):**
```python
cfg.get("min_conviction", 0.60),
cfg.get("min_mentions", 2),
dd_min_confidence,  # Drawdown-abhängig: 0.70/0.75/0.80
```

**3. Size-Faktor (Zeile ~1360):**
```python
# Drawdown-Faktor: Positionsgröße ab 12% Drawdown reduziert
if dd_size_factor < 1.0:
    pct = pct * dd_size_factor
    sizing_label += f" | Drawdown ({dd_size_factor:.0%})"
```

### Reihenfolge der Size-Modifikatoren

```
pct = basis_pct (HIGH/NORMAL/LOW)
  → pct = pct * vix_factor          (VIX > 30 → 0.5)
  → pct = pct * probation_factor    (Sektor-Re-Entry → 0.5)
  → pct = pct * dd_size_factor      (Drawdown → 0.75/0.50)
  → position_size = min(pct * portfolio_value, cash, remaining_budget)
```

## Heilungsmechanismus

Der Drawdown wird bei jedem Pipeline-Lauf (per `check_drawdown()`) neu berechnet. Sobald der MtM-Wert steigt (durch Gewinne in laufenden oder neuen Trades), sinkt der Drawdown und die Schwellen werden automatisch angepasst:

```
-15.5% Drawdown → 50% Size, 80% Conf, 4 Pos
  → 1 Trade mit +3% auf 50% Size → +1.5% Portfolio
  → Drawdown sinkt auf ~14%
  → 75% Size, 75% Conf, 6 Pos
  → Noch 1 Trade mit +3% auf 75% Size → +2.25% Portfolio
  → Drawdown sinkt unter 12%
  → 100% Size, 70% Conf, 8 Pos (Normalbetrieb)
```

## Dateien

| Datei | Änderung |
|-------|----------|
| `scripts/signal_manager.py` | `check_drawdown()` Rückgabe + 3 Anwendungspunkte in `open_new_positions()` |
| `skills/trading-pipeline/SKILL.md` | Neue Section "Drawdown Protection — Graduierte Reduzierung" |

## Fallstricke

- **Nicht vergessen:** Der `close_all`-Fall (≥25%) setzt `drawdown_close_all_date` in der Config → `_is_drawdown_cooldown_active()` blockiert dann 7 Tage. Der Cooldown-Check wurde aus `open_new_positions()` entfernt, weil er vor dem Drawdown-Check lief und den `no_entry`-Stopp unnötig machte. Aber der Cooldown gilt nur für `close_all` — und in dem Fall wird `_is_drawdown_cooldown_active()` von `_emergency_close_all()` gesetzt.
- **Logging:** Die Drawdown-Parameter werden im Pipeline-Log ausgegeben (z.B. `Drawdown -15.5% → Size 50%, Confidence ≥80%, Max 4 Positionen`). Bei Fehlersuche im Dashboard-Cron-Tab auf diese Zeilen achten.
- **Kein Reset nötig:** Anders als `adapt_strategy()` (das Config-Drift erzeugte) sind die Drawdown-Parameter **nicht persistent** — sie werden jeden Pipeline-Lauf neu aus dem aktuellen MtM-Wert berechnet. Es gibt keine Config-Drift-Gefahr.