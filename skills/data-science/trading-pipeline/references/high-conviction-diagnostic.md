# High-Conviction-Crash Diagnose

## Symptom

Die Anzahl der Watchlist-Einträge mit ≥76% Conviction sinkt dramatisch, während die Gesamtanzahl der Watchlist-Einträge steigt. Typisch: −44% in 16 Tagen (93→52), während Gesamt+13% (428→484).

## Mögliche Ursachen (in Prüf-Reihenfolge)

### 1. Halbwertszeit-Effekt (wahrscheinlichste Ursache)

`watchlist_manager.py` wendet eine 14-Tage-Halbwertszeit auf `conviction_score` an. Einträge ohne frische Mentions verlieren exponentiell an Conviction.

**Diagnose:**
```sql
SELECT 
    CASE 
        WHEN last_seen >= date('now', '-7 days') THEN 'neu (≤7d)'
        WHEN last_seen >= date('now', '-14 days') THEN 'mittel (8-14d)'
        WHEN last_seen >= date('now', '-21 days') THEN 'alt (15-21d)'
        ELSE 'sehr alt (>21d)'
    END as age_group,
    COUNT(*) as count,
    ROUND(AVG(conviction_score), 4) as avg_conv,
    ROUND(AVG(conviction_score_raw), 4) as avg_raw
FROM watchlist
WHERE status = 'watching' AND conviction_score >= 0.76
GROUP BY age_group
ORDER BY age_group;
```

**Befund (29.07.2026):** 64 alte Einträge (>21d, Ø 0.81) zerfallen durch Halbwertszeit. Gleichzeitig 283 neue Einträge (≤7d, Ø 0.32) verdünnen den Pool. → **Normaler Reinigungszyklus, kein Bug.**

### 2. Quellen-Gewicht-Anpassung

`source_lifecycle.py` passt sonntags die Quellen-Gewichte an. Wenn viele Quellen runtergestuft wurden (z.B. durch `adjust_weights()`), sinkt der Channel-Bonus für viele Einträge.

**Diagnose:** Prüfe `source_registry` ob viele Quellen auf `weight < 1.0` gesetzt wurden.

### 3. `adapt_strategy()` hat `min_confidence` erhöht

`signal_manager.py` → `adapt_strategy()` erhöht `min_confidence` bei Sideways-Regime oder 3× Verlust in Folge. Der Export zählt ≥76% als High-Conviction, aber der signal_manager arbeitet mit `min_confidence` (Standard 0.80).

**Diagnose:**
```sql
SELECT metric_key, metric_value, computed_at 
FROM eval_metrics 
WHERE metric_key LIKE '%confidence%' OR metric_key LIKE '%conviction%'
ORDER BY computed_at DESC LIMIT 10;
```

### 4. Bug im Conviction-Scoring

Selten, aber möglich nach Code-Änderungen im `watchlist_manager.py`.

**Diagnose:** Vergleiche `conviction_score` vs `conviction_score_raw` für einzelne Ticker:
```sql
SELECT ticker, conviction_score, conviction_score_raw, tech_score
FROM watchlist 
WHERE status = 'watching' 
ORDER BY conviction_score DESC LIMIT 20;
```

Wenn `conviction_score_raw` sauber aussieht aber `conviction_score` massiv abweicht → Aging-Funktion oder Channel-Bonus defekt.

## Historie

| Datum | Vorher | Nachher | Δ | Ursache |
|-------|--------|---------|---|---------|
| 29.07.2026 | 93 | 52 | −44% | Halbwertszeit (16d ohne starke Signale) |