# Cron Health: Pipeline-Block-Slicing Bug

## Symptom

`cron_health.py` zeigt `⚠️ YouTube Scan` (oder einen anderen Pipeline-internen Schritt), obwohl der Scan **erfolgreich** war und im Log `=== HH:MM YouTube Scan DONE ===` steht.

## Root Cause

Der Health-Check sucht Pipeline-interne Marker nur **innerhalb des Pipeline-Blocks**. Der Pipeline-Block wird von START-Marker bis zum nächsten Cron-Job-Start gesliced:

```python
# Phase 1: Tages-Cron-Jobs finden
# z.B. trading_pipeline startet bei line 260101
#      nightly_eval startet bei line 260303
# → Pipeline-Block = 260101 bis 260303

# Phase 2: Pipeline-interne Marker im Block suchen
# YouTube Scan START (04:00, line 260115) → GEFUNDEN
# YouTube Scan DONE (05:45, line 260525) → AUSSERHALB des Blocks!
```

Wenn die Pipeline länger läuft als bis zum nächsten Cron-Job, liegen die DONE-Marker **ausserhalb** des Pipeline-Blocks.

## Auslöser

- YouTube Scan mit vielen Kanälen (z.B. 28 statt 19) → Scan dauert 1h45min statt 5-15min
- 120s Wartezeit zwischen Transkript-Downloads summiert sich bei vielen Kanälen
- nightly_eval feuert um 05:00, schneidet den Pipeline-Block ab
- YouTube Scan fertigt erst um 05:45 → DONE-Marker liegt im nightly_eval-Block

## Diagnose

```bash
# 1. Prüfe ob der DONE-Marker existiert
grep "YouTube Scan DONE" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -3

# 2. Prüfe wo die Block-Grenzen liegen
grep -n "=== .* START ===" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10

# 3. Vergleich: Liegt DONE-Zeile nach dem nächsten Cron-Job-Start?
# Wenn ja: Slicing-Problem
```

## Fix (implementiert 08.07.2026)

**Phase 3 in cron_health.py:** Nach Phase 2 (Pipeline-interne Jobs im Pipeline-Block) sucht Phase 3 in den **nachfolgenden Blöcken** (bis zum nächsten Pipeline-Start oder Dateiende) nach DONE/ERROR-Markern für unvollständige Pipeline-Jobs.

```python
# Phase 3: Unresolved Pipeline-Internal Jobs in nachfolgenden Blöcken
pipeline_internal_jobs = {"YouTube Scan", "KI Analyse", "Screener Source",
                          "Watchlist Update", "Watchlist Dedup",
                          "Technical Analysis", "Signal Manager"}
unresolved = [(rn, rs) for rn, rs in results
              if rn in pipeline_internal_jobs and rs == "started"]
if unresolved:
    # Suche vom Pipeline-Block-Ende bis zum nächsten Pipeline-Start
    search_end = next_pipeline_start or len(lines)
    extended_block = "".join(lines[pipeline_end:search_end])
    for m in re.finditer(r"=== \d+:\d+:\d+ (.+) ===", extended_block):
        # ... matched DONE/ERROR → aktualisiert den Status
```

**Crontab (03:30 statt 04:00):** trading_pipeline läuft jetzt um 03:30 Mo–Fr, um mehr Puffer vor nightly_eval (05:00) zu haben. Social_scanner (03:00) ist in der Regel durch, bevor die Pipeline startet.

## Fix-Optionen (vor dem Implementierungs-Fix)

| Option | Aufwand | Effekt | Nachteil |
|--------|---------|--------|----------|
| **A: Health-Check fixen** — Pipeline-Block über mehrere Cron-Jobs hinweg slicen (DONE im nächsten Block akzeptieren) | ~30 Min | Korrekte Erkennung | Komplexere Logik |
| **B: Scan-Wartezeit reduzieren** — 120s → 60s | 1 Zeile | Scan wird schneller | Höheres API-Rate-Limit-Risiko |
| **C: YouTube Scan vorziehen** — 03:00 statt 04:00 | 1 Zeile (crontab) | Mehr Zeit | Konflikt mit social_scanner um 03:00 |
| **D: nightly_eval verschieben** — 06:00 statt 05:00 | 1 Zeile (crontab) | Pipeline hat mehr Zeit | Eval läuft später |

## Prävention

- Nach Änderungen an der Anzahl aktiver Quellen (source_registry): Pipeline-Laufzeit im Auge behalten
- Wenn die Pipeline 2+ Stunden läuft und ein Cron-Job um 05:00 feuert → Slicing-Problem vorprogrammiert
- Health-Check-Output täglich prüfen: `⚠️` ohne erkennbaren Grund = Slicing-Bug