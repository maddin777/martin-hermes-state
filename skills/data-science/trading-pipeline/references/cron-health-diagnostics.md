# Cron-Health & cron.log-Diagnose

Topic-Referenz für `cron_health.py` (`b0b06693e8f9`, täglich 08:30) und das Format von
`data/cron.log`.

## Log-Formate

**Tages-Cron-Jobs (System-Crontab, Standalone-Scripts):**

```
=== Fri Jun  5 02:00:01 CEST 2026 === fundamental_data START ===
```

Doppel-Space bei einstelligen Tagen (`Jun  5`), Tag unpadded, Zeitzone immer vorhanden,
`jobname` ohne `.py`.

**Pipeline-interne Jobs (`trading_pipeline.py`):**

```
=== 04:00:03 YouTube Scan START ===
=== 04:04:13 Technical Analysis DONE ===
```

Kein Datum, nur Uhrzeit; Status `START` | `DONE` | `ERROR (exit N)`; abgeschlossene Jobs
zusätzlich als `  ✅ Technical Analysis` im Block.

**Fehler:** rohe Tracebacks im Logfluss, kein strukturiertes Error-Logging.

## Health-Checker-Regexe

- Phase 1 (Tages-Crons): `=== \w+ \w+\s+(\d+) \d+:\d+:\d+ \w+ \d{4} === (.+?) START ===`
  — Tag als int vergleichen, **nicht** als String. Das alte `(\d+)` statt `\s+(\d+)` scheiterte
  an einstelligen Tagen und meldete "keine Jobs".
- Phase 2 (Pipeline-intern): `=== \d+:\d+:\d+ (.+) ===`, Status per `rsplit(" ", 1)`;
  `pjob` enthält den Timestamp und muss vor dem Status-Vergleich gestrippt werden.
- Success-Erkennung: `✅\s*.*DONE|✅\s*.*abgeschlossen|✅\s*Fertig\.` — ein Job ohne ✅ vor
  "DONE" gilt als `⚠️ unknown`.

## Falsch-Gelb 1: Pipeline-Block-Slicing

**Symptom:** `⚠️ YouTube Scan` (oder anderer Pipeline-Schritt) obwohl `DONE` im Log steht.
**Ursache:** Der Block wird von START bis zum nächsten Cron-Job geschnitten; läuft der Scan
über den nächsten Job-Start hinaus (z. B. 05:00 `nightly_eval`), liegt sein DONE-Marker
ausserhalb. **Diagnose:** `grep -n "=== .* START ===" data/cron.log | tail -10` und prüfen, ob
DONE nach dem nächsten Start liegt. **Fix:** Phase 3 im Health-Check akzeptiert DONE/ERROR auch
in den nachfolgenden Blöcken (bis zum nächsten Pipeline-Start); zusätzlich Puffer über die
Crontab (Pipeline 03:30 statt 04:00, Scan-Wartezeit nicht unnötig hoch).

**Prävention:** Nach Änderungen an der Zahl aktiver Quellen die Pipeline-Laufzeit beobachten —
2+ Stunden Laufzeit vor einem 05:00-Job bedeutet Slicing-Alarm.

## Falsch-Gelb 2: Job loggt ohne ✅ (z. B. `factor_ranker`)

**Symptom:** `⚠️ factor_ranker`, obwohl der Job läuft. **Ursache:** Das Script loggt
`[Factor Ranker] DONE. Top 5: …` ohne Emoji und ohne `===`-Zeitstempel → `unknown`.

**Erst verifizieren, dass es kein echter Ausfall ist:**

```sql
SELECT COUNT(*), MAX(date) FROM factor_scores;   -- heute = ok, Monate alt = echter Ausfall
```

`factor_ranker` ist ein **system-crontab**-Job (Mo–Fr 05:10) und steht nicht in der
`get_cron_jobs()`-Whitelist des Dashboards — sein Status lebt nur im Health-Output. Fix:
Success-Regex toleranter (`✅|DONE|abgeschlossen|Fertig`) **oder** das Script im
`=== HH:MM:SS … DONE ===`-Format mit ✅ loggen. Zweimal `START` am selben Tag plus fehlendes
DONE am Dateiende erzeugt doppeltes Gelb — Kunstprodukt der Slicing-Logik, kein zweiter Fehler.

## Quick Parse

```bash
grep -E "^=== \w+ \w+\s+\d+ \d{2}:\d{2}:\d{2} \w+ \d{4} === .+ START ===" data/cron.log | tail -10
grep -E "^=== \d{2}:\d{2}:\d{2} .+ (START|DONE|ERROR)" data/cron.log | tail -10
grep -B1 "Traceback" data/cron.log | grep -E "^==="
tac data/cron.log | grep -m1 -A5 "TRADING PIPELINE START"
```

**Grundregel für alle Crons:** jeder Job schreibt `✅ ... DONE` — sonst meldet der Health-Check
`⚠️ unknown`, und ein echter Dauerfehler bleibt zwischen falschen Gelb-Meldungen unsichtbar.
