---
name: trading-pipeline
description: >-
  Operate and debug the automated market signal pipeline under profile
  hermes_trading. Covers cron-based data collection (YouTube, RSS, Twitter),
  LLM signal extraction, watchlist management, technical analysis, nightly
  evaluation, and dashboard (port 8081). Known failure modes and their fixes
  are documented.
---

# Trading Pipeline

## System Architecture

The pipeline runs under **profile `hermes_trading`** with its own
**system crontab** (not Hermes cron daemon). All scripts live at:

```
/root/.hermes/profiles/hermes_trading/skills/trading/scripts/
```

Database is at:
```
/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db
```

### Cron Schedule (Mo–Fr)

| Time  | Script | Purpose |
|-------|--------|---------|
| 02:00 | `fundamental_data.py` | Macro data, insider trades, put/call ratios, regime detection |
| 03:00 | `social_scanner.py` | RSS feeds (Seeking Alpha, Bloomberg etc.) + Twitter/X (twitterapi.io, 6 accounts) |
| 04:00 | `trading_pipeline.py` | Orchestrator: YouTube scan → KI Analyse → Watchlist Update → Technical Analysis → Signal Manager |
| 04:50 | `llm_validator.py` | LLM-based validation of top watchlist candidates |
| 05:00 | `nightly_eval.py` | Signal metrics + portfolio metrics + source quality → Telegram report |
| 09:30 | `active_exit_check.py` | Mid-day exit checks |
| 13-20:15 | `signal_manager.py check_only` | Intraday signal check (hourly) |
| 15:30 | `active_exit_check.py` | Afternoon exit checks |
| 20:00 (Fr) | `signal_manager.py full` | Weekly signal review |

### Weekend (Sonntag)
| Time | Script | Purpose |
|------|--------|---------|
| 05:30 | `watchlist_dedup.py` | **Weekly watchlist dedup** — merges duplicate entries by ticker (Hermes Cron, job-id `472ace6fe18a`) |
| 06:00 | `nightly_eval.py` | Weekly aggregate (strategy optimizer run at 08:00) |
| 07:00 | `source_lifecycle.py` | Source cleanup & rotation |
| 08:00 | `strategy_optimizer.py` | Strategy parameter optimization |

### Dashboard
- Port **8081**, serves `dashboard.py` (Flask app)
- Reads `eval_metrics` table for signal/portfolio stats

## Data Flow

```
YouTube Channels ──→ yt_channel_monitor.py
    ↓ (8 new videos/night)
transcripts (sqlite: videos table)
    ↓ (KI Analyse — LLM extracts companies + sentiment)
watchlist_mentions
    ↓ (Watchlist Manager — normalizes names, merges duplicates)
watchlist table (778 companies typ.)
    ↓ (Technical Analysis — yfinance price data + indicators)
trading_signals_validated.json + watchlist updated
    ↓ (Signal Manager — entry signals, position sizing)
positions table → portfolio management
    ↓ (Nightly Eval — metrics → eval_metrics table)
Telegram report + Dashboard
```

## Pitfalls & Fixes

### 1. Date-Mismatch in Signal Metrics

**Symptom:** Dashboard and Telegram report show 0 for Neue Unternehmen, Bestätigungen, Ø Conviction despite pipeline running correctly.

**Root Cause:** `watchlist_manager.py` stores `mention_date` using the **video upload date** from YouTube, not the pipeline run date. But `nightly_eval.py` `calc_signal_metrics()` used `datetime.now()` (= pipeline run date) to query `watchlist_mentions`. Result: query found no records for "today" → all metrics = 0.

**Fix:** Override `today`/`yesterday` inside `calc_signal_metrics()` by querying the last two `DISTINCT mention_date` values from the DB:

```python
last_dates = con.execute(
    "SELECT DISTINCT mention_date FROM watchlist_mentions ORDER BY mention_date DESC LIMIT 2"
).fetchall()
if len(last_dates) >= 2:
    today = last_dates[0][0]
    yesterday = last_dates[1][0]
```

### 2. Orphaned-DB-Connection Cascade (Crash → Hours-Long Lock)

**Symptom:** ALLE nachfolgenden Cron-Jobs (social_scanner, YouTube Scan, Watchlist Update, Signal Manager) schlagen fehl mit `sqlite3.OperationalError: database is locked`. Pipeline-Report zeigt ❌ für 3-5 Jobs. Erstes Script (02:00 fundamental_data) failed, die nächsten 4 auch — das ist der Hinweis.

**Log-Muster:**
```
=== Mon Jun  8 02:00:01 CEST 2026 === fundamental_data START ===
📡 Fundamental Data Collector gestartet
Traceback (most recent call last):
  ...
KeyError: 'fred_indicators'
=== Mon Jun  8 03:00:01 CEST 2026 === social_scanner START ===
📡 Social Scanner gestartet
📰 RSS Feeds...
  ✗ Seeking Alpha: database is locked
  ✗ Bloomberg Markets: database is locked
  ...
=== Mon Jun  8 04:00:01 CEST 2026 === trading_pipeline START ===
=== 04:00:03 YouTube Scan START ===
=== 04:00:08 YouTube Scan ERROR (exit 1) ===  ← 5s! kein echter Laufversuch
```

**Root Cause:** Ein frühes Pipeline-Script (meist `fundamental_data.py` um 02:00) crasht mit einer Exception (z.B. `KeyError`, `ImportError`). Die `sqlite3.connect()`-Connection wurde geöffnet aber nie geschlossen (`con.close()` wird nie erreicht). Diese orphaned Connection hält einen Write-Lock auf der WAL-Datei — für Stunden. Der `busy_timeout` hilft nicht, weil die tote Connection nie commit/rollback ausführt.

**Diagnose:**
```bash
grep -E "ERROR|Traceback|database is locked" \
  /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10

# Lock manuell lösen (WAL-Checkpoint)
python3 -c "
import sqlite3
con = sqlite3.connect('/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db')
con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
con.close()
print('WAL checkpoint done')
"
```

**Fix (3 Teile):**
1. Config-Fehler beheben: `grep "KeyError" cron.log` → fehlenden Key in `strategy_config.json` ergänzen
2. `con.close()` im `finally`-Block für ALLE Pipeline-Scripts
3. `PRAGMA busy_timeout=30000` in fundamental_data (war default 5000ms)

**Prävention:** Nach jedem Patch an fundamental_data.py den `finally`-Block prüfen.

### 3. Technical Validator Crash

**Symptom:** `technical_validator.py` crashes at line 287 with `ValueError: Unknown format code 'd' for object of type 'float'`.

**Fix:** Change `{t['score']:+d}` to `{t['score']:+.1f}` or `int(t['score'])`.

### 4. Cross-Profile Edits

Trading scripts live under profile `hermes_trading`. Edits from `default` profile session trigger the **cross-profile soft guard**. Use `cross_profile=True` with explicit user direction.

### 5. Dashboard Staleness

Dashboard reads `eval_metrics` last row. After a `nightly_eval.py` fix, dashboard shows stale data until the next 05:00 cron run. To test: run `TELEGRAM_BOT_TOKEN='***' python3 nightly_eval.py` (masks token to prevent duplicate Telegram dispatch).

### 6. Cron Health Daily meldet "Keine Trading-Jobs" obwohl Pipeline lief

**Symptom:** `cron_health.py` (08:00) meldet "Keine Trading-Jobs für heute geloggt" oder zeigt falsche Status an.

**Root Cause 1 — Leading-Zero vs Unpadded Day:**
```python
today_day = TODAY.strftime("%d")  # "05" (zero-padded)
```
Linux `date` im crontab schreibt `5` (unpadded) für den 5. Juni. String-Vergleich `"05" == "5"` failt → null Treffer.

**Fix:** `int-Vergleich` statt String:
```python
today_day_int = TODAY.day
if m and int(m.group(1)) == today_day_int:
```

**Root Cause 2 — Doppel-Space zwischen Monat und Tag:**
Log: `=== Fri Jun  5 02:00:01 CEST 2026 === ...`
Regex: `=== \w+ \w+ (\d+)` erwartet genau einen Space nach dem Monat, aber `date` padded eintägige Zahlen mit **zwei** Spaces.

**Fix:** `\s+` statt ` `:
```python
r"=== \w+ \w+\s+(\d+) ..."
```

**Root Cause 3 — Pipeline-interne Jobnamen mit Timestamp:**
Phase-2 matched `=== 05:03:16 Technical Analysis DONE ===` und extrahiert `pjob = "05:03:16 Technical Analysis"`, aber Phase-1 hat den Eintrag unter `"Technical Analysis"`.

**Fix:** Timestamp aus pjob entfernen vor Status-Vergleich:
```python
pjob_parts = parts[0].split(" ", 1)
pjob = pjob_parts[1] if len(pjob_parts) > 1 else pjob_parts[0]
```

### 7. Standalone Script Import Failures (system crontab)

**Symptom:** Standalone crontab-Scripts crashen mit `ImportError` oder `NameError`, obwohl die Pipeline (`trading_pipeline.py`) fehlerfrei läuft.

**Root Cause 1 — Doppelt-vorsilbende Importnamen:** AI-generierte Imports enthalten doppelte Prefixe wie `STRATEGY_STRATEGY_CONFIG_PATH` statt `STRATEGY_CONFIG_PATH`, `BACKTEST_BACKTEST_REPORT_PATH` statt `BACKTEST_REPORT_PATH`.

**Root Cause 2 — Fehlende Imports:** Scripts importieren nicht alle benötigten Namen aus `config.py`.

**Root Cause 3 — Kaputte Tuple-Zeile:** `social_scanner.py` hatte `log = get_logger(...), SOURCES_CONFIG_PATH, SIGNALS_PATH` — ein Tuple statt einem Logger.

**Fix:** Imports mit config.py abgleichen:
```bash
grep '=.*os\.path\.join' /root/.hermes/profiles/hermes_trading/skills/trading/scripts/config.py
```

**Prävention:** Regelmäßiger Scan:
```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading/scripts
python3 -c "import config; [print(n) for n in dir(config) if not n.startswith('_')]" > /tmp/actual_names.txt
grep -nP '_[A-Z]+_[A-Z]+_[A-Z]+_PATH' *.py
```

### 8. Watchlist Duplikate wachsen trotz normalize_mentions

**Symptom:** Immer mehr Duplikate in der `watchlist`-Tabelle (Nvidia/NVIDIA, Meta/Meta Platforms). `normalize_mentions()` läuft täglich, aber Duplikate bleiben.

**Root Cause 1 — SQLite Bulk-UPDATE Bug:** `normalize_mentions()` versucht ein `UPDATE watchlist_mentions SET name='NVIDIA' WHERE name='Nvidia'`. Wenn ANY Zeile einen UNIQUE-Konflikt auslöst, schlägt das gesamte UPDATE fehl.

**Fix:** DELETE konfliktierende Zeilen VOR dem UPDATE:
```python
con.execute("DELETE FROM table WHERE name=? AND EXISTS (SELECT 1 FROM table AS w2 WHERE w2.name=? AND w2.video_id=table.video_id)", (orig, canonical))
con.execute("UPDATE table SET name=? WHERE name=?", (canonical, orig))
```

**Root Cause 2 — Watchlist-Table-Level:** Case-Varianten (Nvidia vs NVIDIA) werden als verschiedene Einträge angelegt.

**Fix:** Wöchentlicher `watchlist_dedup.py` (So 05:30) merged über Ticker-Abgleich. Siehe `references/watchlist-table-dedup.md`.

### 9. Watchlist Channels Case-Bug (Quellen-Namen nicht normalisiert)

**Symptom:** Dashboard/Watchlist-Export zeigt `der aktionaer` (44) UND `der Aktionaer` (12) als getrennte Quellen — obwohl es derselbe Kanal ist. Ebenso `urban jäkle` vs `Urban Jäkle`. Verzerrt `GROUP_CONCAT(DISTINCT channel)` und `unique_channels` in der Aggregation.

**Root Cause:** Zwei Probleme:
1. **Alte Daten:** Die `watchlist`-Tabelle speichert `channels` als JSON-Array. Vor der Normalisierung angelegte Einträge haben case-variante Channel-Namen.
2. **Stale UPDATE:** `watchlist_manager.py` aktualisiert `channels` nur für `status IN ('watching', 'dropped')`. Einträge mit `status='bought'` werden nie refreshed.

**Einmaliger Fix (alle Altdaten):**
```python
import sqlite3, json
con = sqlite3.connect(DB_PATH)
for row in con.execute("SELECT id, channels FROM watchlist WHERE channels IS NOT NULL"):
    try:
        chans = json.loads(row["channels"])
    except:
        continue
    norm = sorted(set(c.lower().strip() for c in chans if c and c.strip()))
    con.execute("UPDATE watchlist SET channels=? WHERE id=?", (json.dumps(norm), row["id"]))
con.commit()
```

**Achtung id=NULL:** Die `watchlist`-Tabelle hat ~133 Einträge mit `id=NULL`. Diese werden vom `UPDATE ... WHERE id=?`-Pattern nicht erfasst. Für diese Einträge direkt per `WHERE channels = '[...]'` matchen.

**After-Fix-Check:**
```bash
python3 -c "
import sqlite3
c = sqlite3.connect(DB_PATH)
print(c.execute(\"SELECT COUNT(*) FROM watchlist WHERE channels GLOB '*[A-Z]*'\").fetchone()[0])
"
```

**Prävention (eingebaut seit 08.06.2026):** `watchlist_manager.py` `main()` hat einen normalize-Step direkt nach der `watchlist_mentions`-Normalisierung. Läuft täglich mit der Pipeline.

### 10. Ticker-Korrektur bei UNIQUE-Constraint (Merge + Delete)

**Symptom:** Ein Watchlist-Eintrag hat einen falschen Ticker (z.B. `ARMK` statt `ARM` — ARMK existiert nicht). Der korrekte Ticker `ARM` hat bereits einen anderen Eintrag. `UPDATE ticker='ARM'` schlägt fehl mit `IntegrityError: UNIQUE constraint failed: watchlist.ticker`.

**Root Cause:** `watchlist.ticker` hat einen UNIQUE-Constraint.

**Fix — Merge + Delete:**
```python
con = sqlite3.connect(DB_PATH)
falsch = dict(con.execute("SELECT * FROM watchlist WHERE ticker='ARMK'").fetchone())
con.execute("""
    UPDATE watchlist SET
        mention_count = mention_count + ?,
        bullish_count = bullish_count + ?,
        bearish_count = bearish_count + ?,
        neutral_count = neutral_count + ?
    WHERE ticker='ARM'
""", (falsch["mention_count"] or 0, falsch["bullish_count"] or 0,
      falsch["bearish_count"] or 0, falsch["neutral_count"] or 0))
con.execute("DELETE FROM watchlist WHERE ticker='ARMK'")
con.commit()
```

**Wann nötig:** Bei Phantom-Tickern, Exchange-Ticker-Konfusion (ARMK vs ARM), oder wenn zwei Einträge dieselbe Firma repräsentieren.

**Alternativ:** Wenn der falsche Ticker noch keinem korrekten Eintrag entspricht (kein UNIQUE-Konflikt), reicht `UPDATE ticker='...' WHERE ticker='...'`.

### 11. xsearch_helper Import Collision (Hermes Agent vs Trading utils)

**Symptom:** Signal Manager läuft durch, aber zeigt `x_search Fehler: cannot import name 'base_url_hostname' from 'utils'`. Der Grok-X-Boost (`conviction_boost`, `breaking_news_check`) fällt aus.

**Root Cause:** `xsearch_helper.py` importiert `run_agent.AIAgent` im selben Python-Prozess. Die Trading-Umgebung hat bereits `from utils import get_logger` ausgeführt, also ist `sys.modules['utils']` auf die Trading-`utils.py` gecached — ohne `base_url_hostname`, `safe_json_loads`, etc.

**Symptom-Kaskade:**
1. Erstes fehlendes Symbol: `base_url_hostname`
2. Nach `sys.modules.pop`-Fix: nächstes fehlendes Symbol: `safe_json_loads` — endlos, weil der Import-Cache nie sauber wird

**Fix — Subprozess-Isolation:** AIAgent in einem separaten Python-Subprozess starten:
```python
def _get_agent():
    import subprocess, sys as _sys
    cmd = [_sys.executable, "-c", """
import sys
sys.path.insert(0, '/root/.hermes/hermes-agent')
from run_agent import AIAgent
agent = AIAgent(enabled_toolsets=["x_search"], quiet_mode=True, skip_memory=True)
result = agent.chat(sys.stdin.read())
print(result)
"""]
    return _SubprocessAgent(cmd)
```

**Vorteil:** Null sys.path-Manipulation im Hauptprozess. Keine Nebenwirkungen auf nachfolgende Trading-Imports.

## Quick Debug

See `references/cron-log-format.md` for details on parsing the two log formats.

```bash
# Last pipeline run
tail -100 /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log

# Last eval_metrics row
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT * FROM eval_metrics ORDER BY date DESC LIMIT 1;"

# Last 5 mention dates
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT mention_date, COUNT(*) FROM watchlist_mentions GROUP BY mention_date ORDER BY mention_date DESC LIMIT 5;"

# Dashboard health
curl -s http://localhost:8081/ | grep -o '<title>.*</title>'

# System crontab
crontab -l | grep trading

# Watchlist dedup manually
cd /root/.hermes/profiles/hermes_trading/skills/trading/scripts
python3 watchlist_dedup.py

# Find orphaned connection (fundamental_data crash cascade)
grep -n "ERROR\|Traceback\|database is locked" \
  /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -20
```