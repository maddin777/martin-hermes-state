# Pipeline-Timing-Diagnose: Warum läuft die Pipeline so lange?

## Kern-Lektion (27.08.2026)

Wenn die Pipeline länger als 1h läuft und mit `nightly_eval` (05:00) / `crabel_shadow_eval`
(06:30) kollidiert: **Nimm NIE an, der Bottleneck sei die Watchlist oder der Screener.**
Der reale Kostentreiber ist meist die **LLM-JSON-Fallback-Kaskade in der KI-Analyse**
(`scripts/signal_extractor.py`), nicht das Universe, nicht die Video-Anzahl.

Am 27.08.2026: Pipeline ca. 03:30→07:56 (4,5h), KI-Analyse 03:59→07:29 (3,5h), bei nur
**13 Videos, Ø 1-3 Chunks** (~40 ideale LLM-Calls). Der Screener hingegen war harmlos (165s).
→ Nicht die Menge, sondern die Fallback-Kaskade pro Call.

## Wurzel-Ursache: `_call_cascade` + `timeout=60` + serielle Chunks

In `signal_extractor.py`:
- `_call()` hat `timeout=60` hart + `@retry(max_attempts=3, backoff=2.0)`.
- `_call_cascade()` macht bis zu 3 Stufen pro Chunk: deepseek → "retry mit strengerem
  Prompt" → gpt-4o-mini Fallback. Jede Stufe = neuer 60s-Timeout-Call.
- Bei großen Transkript-Chunks (bis ~50k Zeichen, 6-Chunk-Videos) und trägem Endpoint laufen
  Calls >60s → Timeout → Retry → Kaskade. Ein einzelner Chunk kann so 3-9× neu ausgeführt werden.
- Chunks eines Videos werden seriell verarbeitet (kein ThreadPool).

**Signature-Symptom im Log:**
```
⚠ JSON Fehler deepseek/deepseek-v4-flash-0731, retry mit strengerem Prompt...
⚠ JSON Fehler deepseek/deepseek-v4-flash-0731, versuche gpt-4o-mini...
```
Viele `JSON Fehler ... versuche`-Zeilen = die Kaskade brennt. 20 solche Fehler in einer
Analyse-Periodie hinter ~16 Min/Video.

## Diagnose-Rezept (isolieren, welcher Schritt der Bottleneck ist)

```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading
# 1. Gesamt-Dauer + ob Safety-Jobs kollidieren:
grep -E "TRADING PIPELINE START|TRADING PIPELINE DONE" data/cron.log | tail -4

# 2. Schritt-Zeiten heute isolieren (YouTube → KI Analyse → ... → Signal Manager):
grep -E "\[2026-08-XX (0[3-8]):" data/cron.log | grep -E "START|DONE" | head -50

# 3. JSON-Fehler-Kaskade zählen (der echte Kostentreiber):
awk '/KI Analyse START/,/KI Analyse DONE/' data/cron.log | grep -cE "JSON Fehler|JSON fehlerhaft"

# 4. Screener-Laufzeit messen (schnell: nur ~165s, meist NICHT der Bottleneck):
time python3 scripts/screener_source.py --dry-run
```

**Vergleichswerte (27.08.)**: YouTube Scan 03:30→03:59 (30min) · KI Analyse 03:59→07:29 (3,5h!)
· Screener 07:29→07:31 (2min) · Watchlist 07:31→07:45 (14min) · Technical 07:45→07:55 · Signal 07:55→07:56.
→ Der Screener ist NICHT der Flaschenhals; die KI-Analyse ist es.

## Fix-Richtung (nicht blind anwenden — durch Finn-loop Review)

Der Wurzel-Fix (Task `pipeline-ki-analyse-haertung.md`) adressiert drei Vektoren:
1. **JSON-Parsing härten** (`_try_parse`/`_call_cascade`): sauberes deepseek-Output seltener
   als Falsch-JSON ablehnen (robuste Reparatur, Precise-`{...}`-Extraktion, Markdown-Wrapper
   lenient) → weniger Kaskaden-Läufe.
2. **Timeout angemessen** (hart 60s → konfigurierbar 90-120s), damit große Chunks nicht
   künstlich in Timeout-Retries getrieben werden.
3. **Chunks parallelisieren** (ThreadPool, max_workers 3-4, mit 429/5xx-Backoff), statt seriell.
   Analyst-Call bleibt seriell nach Merge.

**Wichtig:** "Parallelisieren" muss Rate-Limit-Respekt haben — OpenRouter 429/5xx mit Backoff,
damit die Fehlerquote bei gleichzeitigen Requests nicht steigt (AC-4).

## Related

- `Erklaerung.md` im Trading-Verzeichnis (Live-Doku, Datum 27.08.2026).
- Pitfall "Cron Health: Pipeline-Block-Slicing" (`references/cron-health-slicing-bug.md`):
  wenn die KI-Analyse lange läuft, liegt der DONE-Marker ausserhalb des Pipeline-Blocks →
  cron_health false-alarm.
