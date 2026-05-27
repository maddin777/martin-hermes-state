# Trading Pipeline Diagnostics

*Diagnosing why the trading pipeline shows 0, failed scripts, or stale data*

---

## Signal-Pipeline zeigt 0 — Warum?

Der Tages-Report (05:00) zeigt die Signal-Pipeline-Sektion:

```
Signal-Pipeline:
  Neue Unternehmen: 0
  Bestätigungen: 0
  Widersprüche: 0
  Ø Conviction: 0.0%
```

### Ab 27.05.2026: Verarbeitungsdatum (Fixed)

**Früher:** Die Pipeline schrieb Mentions mit dem Original-Publikationsdatum (`social_scanner.py` verwendete `m[3][:10]`, `watchlist_manager.py` verwendete das YouTube-Video-Datum). Morgens um 05:00 gab's dann 0 Treffer weil noch nichts für "heute" publiziert wurde.

**Jetzt:** Beide Schreibstellen (`social_scanner.py` + `watchlist_manager.py`) verwenden `datetime.now().strftime("%Y-%m-%d")` — das Verarbeitungsdatum. Die Signal-Pipeline zeigt jetzt korrekt was heute früh verarbeitet wurde.

**Prüfen ob Daten da sind (falls immer noch 0):**

```bash
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT mention_date, COUNT(*) FROM watchlist_mentions GROUP BY mention_date ORDER BY mention_date DESC LIMIT 7"
```

### Wann es ein echter Fehler ist

Wenn **alle** der folgenden Bedingungen zutreffen:
1. Es ist kein Wochenende (Mo–Fr)
2. Es sind keine Mentions für **die letzten 2+ Tage** in der DB
3. Die Pipeline-Logs zeigen Script-Crashes

---

## Pipeline-Logs lesen

Die Trading-Pipeline loggt in eine einzige Datei:

```
/root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log
```

### Cron-Job-Timing

| Zeit | Script | Log-Signatur |
|------|--------|-------------|
| 02:00 Mo–Fr | `fundamental_data.py` | `=== ... fundamental_data START ===` |
| 03:00 Mo–Fr | `social_scanner.py` | `=== ... social_scanner START ===` |
| 04:00 Mo–Fr | `trading_pipeline.py` | `=== ... TRADING PIPELINE START ===` |
| 05:00 Mo–Fr | `nightly_eval.py` | `=== ... nightly_eval START ===` |
| 08:00 tägl. | `cron_health.py` (Hermes Cron) | Telegram-Health-Report |
| 09:30 Mo–Fr | `active_exit_check.py` | `=== ... active_exit_check START ===` |

### Automatisierter Health Check (08:00)

Seit 26.05.2026 läuft täglich um 08:00 `cron_health.py` als Telegram-Report:

```bash
python3 /root/.hermes/scripts/cron_health.py
```

Output:
```
📋 Cron-Job Health
Heute: 9 Jobs | ✅ 8 | ❌ 1

  ✅ fundamental_data
  ✅ social_scanner
  ✅ YouTube Scan
  ✅ KI Analyse
  ✅ Watchlist Update
  ❌ Technical Analysis
  ✅ Signal Manager
  ✅ nightly_eval
  ✅ trading_pipeline
```

Erkennt Pipeline-interne Jobs (YouTube Scan, KI Analyse, etc.) und Tages-Crons aus dem `cron.log`. Gibt es im Hermes Cron `cron-health-daily` (b0b06693e8f9) um 08:00 als Telegram.

### Schnell-Check ob heute lief

```bash
# Hat die Pipeline heute früh durchgelaufen?
grep "TRADING PIPELINE DONE" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -3

# Gab es Fehler?
grep -E "ERROR|Traceback|exit 1|CRITICAL" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -20

# Welche Schritte hatten welchen Status?
grep -E "=== \d\d:\d\d:\d\d (START|DONE|ERROR)" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10
```

---

## Häufige Fehler und Ursachen

### "database is locked"

**Symptom:** RSS-Feeds (03:00) schlagen mit `✗ <Quelle>: database is locked` fehl, Twitter/X läuft durch.
**Log:** `✗ Seeking Alpha: database is locked`

**Ursache:** SQLite erlaubt nur einen Writer gleichzeitig. Vor Fix: `journal_mode=delete` + `busy_timeout=0`.

**Fix (26.05.2026):**
1. **WAL mode** auf der DB aktiviert: `PRAGMA journal_mode=WAL;` — erlaubt gleichzeitige Reads
2. **`PRAGMA busy_timeout=5000`** in **allen 16 Scripts** nach jedem `sqlite3.connect()` eingebaut
3. WAL mode persistiert in der DB-Datei; busy_timeout ist per-connection

**Diagnose ob Fix aktiv ist:**
```bash
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db "PRAGMA journal_mode;"
# Soll 'wal' zurückgeben
```

### Technical Validator Crash

**Symptom:** `Technical Analysis ERROR (exit 1)` im Pipeline-Log.
**Log:** `ValueError: Unknown format code 'd' for object of type 'float'`

**Ursache:** Format-String in `technical_validator.py` Zeile 282 verwendet `f"{t['score']:+d}"` für einen Float-Wert.

**Fix (26.05.2026):** `:+d` → `:+.0f`

**Pipeline-Verhalten:** Der Crash killt nur die Technical Analysis, die Pipeline läuft weiter — Signal Manager checkt trotzdem. Kein Totalausfall, aber Tech-Scores fehlen für den Tag.

**Prüfen ob Tech-Scores fehlen:**
```bash
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT COUNT(*) FROM watchlist WHERE tech_score IS NULL AND last_seen > date('now','-2 days')"
```

### Pipeline läuft gar nicht

**Symptom:** Kein `=== ... trading_pipeline START ===` im Log für heute.

**Ursachen:**
1. Weekend (Cron läuft nur Mo–Fr laut crontab `* * * * 1-5`)
2. Cron-Daemon nicht aktiv: `systemctl status cron`
3. Python-Umgebung kaputt: `/usr/bin/python3` nicht gefunden
4. Speicher voll: `df -h /`

---

## Pipeline Recovery

Wenn die Nacht-Pipeline ausgefallen ist:

1. **Pipeline manuell nachholen:** Scripte nacheinander ausführen:
```bash
cd /root/.hermes/profiles/hermes_trading
/usr/bin/python3 scripts/social_scanner.py
/usr/bin/python3 scripts/trading_pipeline.py
/usr/bin/python3 scripts/nightly_eval.py
```

2. **Technical Analysis fixen:** Wenn nur TA gefailed ist, kann sie einzeln nachgeholt werden ohne den Rest zu wiederholen.

3. **DB Backup einspielen:** Falls Daten korrupt sind:
```bash
cp /root/.hermes/profiles/hermes_trading/skills/trading/data/trading_db_backup_*.db \
   /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db
```
Aktuellstes Backup im Obsidian Vault unter `Projekte/` suchen.

---

## Verwandte Referenzen

- `references/ticker-resolution-protocol.md` — wenn die "?"-Ticker Probleme machen
- `references/cron-prompt-2026-05-26.md` — aktueller vault-insights-daily Prompt
- Trading Pipeline Architecture im Vault: `wiki/concepts/Trading Pipeline Architecture.md`
- Exit Management Logik: `wiki/concepts/Exit Management.md`