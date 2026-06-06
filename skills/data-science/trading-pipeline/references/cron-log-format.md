# cron.log Format

Pfad: `/root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log`

## Zwei Log-Formate

### 1. Tages-Cron-Jobs (System-Crontab)

Geschrieben von den Standalone-Skripten (`fundamental_data.py`, `social_scanner.py`, `active_exit_check.py`, `nightly_eval.py`, `trading_pipeline.py`).

```
=== Wochentag Monat  Tag HH:MM:SS TZ YEAR === jobname START ===
=== Fri Jun  5 02:00:01 CEST 2026 === fundamental_data START ===
```

Besonderheiten:
- **Doppel-Space** bei eintägigen Zahlen: `Jun  5` (nicht `Jun 5`)
- **Tag unpadded**: `5` (nicht `05`)
- Zeitzone (CEST, CET) immer present
- `jobname` = Script-Name ohne `.py`

### 2. Pipeline-interne Jobs (trading_pipeline.py)

Geschrieben von der orchestrierten Pipeline für Sub-Schritte:

```
=== HH:MM:SS Jobname STATUS ===
=== 04:00:03 YouTube Scan START ===
=== 04:00:08 KI Analyse START ===
=== 04:04:13 Technical Analysis DONE ===
=== 05:03:16 Signal Manager START ===
```

Besonderheiten:
- **Kein Datum** — nur Uhrzeit
- `STATUS` = `START`, `DONE`, oder `ERROR (exit N)`
- `Jobname` enthält **keinen Timestamp** als Teil des Namens
- Abgeschlossene Jobs werden zusätzlich im Block geloggt: `  ✅ Technical Analysis`

### 3. Fehlerformat

```
Traceback (most recent call last):
  File ".../script.py", line N, in <module>
    ...
NameError: name 'XYZ' is not defined
```

Kein strukturiertes Error-Logging — die Tracebacks stehen direkt im Logfluss.

## Health-Checker Regex

Das Script `/root/.hermes/scripts/cron_health.py` parst beide Formate:

**Phase 1** (Tages-Crons): Sucht `=== \w+ \w+\s+(\d+) \d+:\d+:\d+ \w+ \d{4} === (.+?) START ===`
- Gruppe 1 = Tag (int-Vergleich, nicht String!)
- Gruppe 2 = Jobname

**Phase 2** (Pipeline-intern): Sucht `=== \d+:\d+:\d+ (.+) ===` im Pipeline-Block
- Extrahiert `pjob` + `pstatus` via `rsplit(" ", 1)`
- **Achtung:** `pjob` enthält den Timestamp (`05:03:16 Technical Analysis`) — muss vor Status-Vergleich gestripped werden

## Quick Parse

```bash
# Alle Tages-Cron-Starts von heute
grep -E "^=== \w+ \w+\s+\d+ \d{2}:\d{2}:\d{2} \w+ \d{4} === .+ START ===" cron.log | tail -10

# Alle Pipeline-internen Marker (heute)
grep -E "^=== \d{2}:\d{2}:\d{2} .+ (START|DONE|ERROR)" cron.log | tail -10

# Heute gecrashte Jobs
grep -B1 "Traceback" cron.log | grep -E "^==="

# Letzten Pipeline-Lauf
tac cron.log | grep -m1 -A5 "TRADING PIPELINE START"
```