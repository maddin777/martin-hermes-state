# cron_health.py False-Positive: `factor_ranker` gelb (19.09.2026)

## Symptom
`cron_health.py` (läuft täglich 08:30 als no_agent-Cron `b0b06693e8f9`) meldet
`⚠️ factor_ranker` (gelb), obwohl der Job korrekt läuft.

## Verifizieren dass es ein False-Positive ist (nicht ein echter Ausfall)
`factor_scores` wird von `factor_ranker.py` befüllt. Frisch heisst: heute vergeben:
```sql
SELECT COUNT(*), MAX(date) FROM factor_scores;
```
War das Datum MONATE alt (am 18.09. war es 13.07.), dann ist es ein echter stiller
Ausfall, kein Optik-Problem. Der `dq_alarm.py` (`37d505cbc47b`) nutzt dieselbe Tabelle
und erwartet, dass `factor_ranker.py` sie füllt.

## Root Cause
`cron_health.py` (Zeile ~56) zählt einen Lauf nur als Erfolg, wenn der Log-Block ein
`✅` VOR "DONE" trägt:
```python
has_success = re.search(r"✅\s*.*DONE|✅\s*.*abgeschlossen|✅\s*Fertig\.", block)
```
`factor_ranker.py` loggt sein Done aber OHNE Emoji und ohne `=== ... ===`-Zeitstempel:
```
[Factor Ranker] DONE. Top 5: BNY(86), CPAY(86), NTRS(85), UNH(85), CNC(84)
```
→ `has_success=False`, kein Traceback/ERROR → `unknown` → ⚠️ gelb.

## Zusätzlicher Trigger: Sicher doppelt gelb
`cron_health.py` zählt pro `START`-Zeile einen Eintrag. Stehen am selben Tag zwei
`factor_ranker START`-Zeilen im `cron.log` (z.B. 01:18 + 01:47) und der zweite Lauf
endet am Dateiende OHNE DONE-Zeile, erscheint der Job doppelt gelb. Das ist ein
Kunstprodukt der Log-Slicing-Logik, kein doppelter Fehler.

## Fix-Optionen
1. **Health-Check tolerant machen (bevorzugt):** Success-Regex auf `✅|DONE|abgeschlossen|Fertig`
   erweitern (nicht nur `✅...DONE`), damit `[Factor Ranker] DONE...` ohne Emoji zählt.
2. **Formal sauber:** `factor_ranker.py` (und ggf. andere Thematic-Scripts) ihr Done im
   `=== HH:MM:SS ... DONE ===`-Format mit `✅` loggen (wie die Haupt-Pipeline).

## Job-Ort (wichtig)
`factor_ranker` ist KEIN Hermes-Cron und KEIN Dashboard-Cron-Tab-Eintrag:
- `dashboard.py get_cron_jobs()` Whitelist (Zeile ~211) enthält `factor_ranker` NICHT →
  taucht im Dashboard-Cron-Tab gar nicht auf.
- Es ist ein **system-crontab**-Job (Mo–Fr 05:10) im Trading-Profil:
  `10 5 * * 1-5 echo "=== $(date) === factor_ranker START ===" >> data/cron.log && cd .../thematic && PYTHONPATH=... python3 factor_ranker.py >> data/cron.log`
- Sein Status lebt NUR im `cron_health.py`-Output.
