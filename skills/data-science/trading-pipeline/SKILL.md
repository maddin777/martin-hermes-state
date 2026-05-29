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

### 2. SQLite "database is locked"

**Symptom:** `social_scanner.py` RSS feeds fail with "database is locked".

**Root Cause:** Multiple cron scripts hitting the same `trading.db` with overlapping execution windows. RSS is non-critical (Twitter data still loads).

### 3. Technical Validator Crash

**Symptom:** `technical_validator.py` crashes at line 287 with `ValueError: Unknown format code 'd' for object of type 'float'`. Pipeline logs "Technical Analysis fehlgeschlagen" but continues.

**Fix:** Change `{t['score']:+d}` to `{t['score']:+.1f}` or `int(t['score'])`.

### 4. Cross-Profile Edits

Trading scripts live under profile `hermes_trading`. Edits from `default` profile session trigger the **cross-profile soft guard**. Use `cross_profile=True` with explicit user direction.

### 5. Dashboard Staleness

Dashboard reads `eval_metrics` last row. After a `nightly_eval.py` fix, dashboard shows stale data until the next 05:00 cron run. To test: run `TELEGRAM_BOT_TOKEN='***' python3 nightly_eval.py` (masks token to prevent duplicate Telegram dispatch).

### 6. Watchlist Duplikate wachsen trotz normalize_mentions

**Symptom:** Immer mehr Duplikate in der `watchlist`-Tabelle (Nvidia/NVIDIA, Meta/Meta Platforms, Take-Two-Varianten). `normalize_mentions()` läuft täglich, aber Duplikate bleiben.

**Root Cause 1 — SQLite Bulk-UPDATE Bug:** `normalize_mentions()` versucht ein `UPDATE watchlist_mentions SET name='NVIDIA' WHERE name='Nvidia'`. Wenn ANY dieser 92 Zeilen einen UNIQUE-Konflikt auslöst (weil es bereits ein "NVIDIA" mit derselben `video_id` gibt), schlägt das gesamte UPDATE fehl — ALLE 92 Zeilen bleiben unverändert. Der try/except IntegrityError-Fang-Lösch-Zweig wird zwar ausgeführt, aber nur die konfliktierenden Zeilen werden gelöscht — die restlichen 80 bleiben als "Nvidia" erhalten.

**Fix:** DELETE konfliktierende Zeilen VOR dem UPDATE, nicht nachträglich als Catch:
```python
# DO THIS: Delete conflicts first, then update the rest
con.execute("DELETE FROM table WHERE name=? AND EXISTS (SELECT 1 FROM table AS w2 WHERE w2.name=? AND w2.video_id=table.video_id)", (orig, canonical))
con.execute("UPDATE table SET name=? WHERE name=?", (canonical, orig))
```

**Root Cause 2 — Watchlist-Table-Level:** Selbst wenn Mentions korrekt gemerged wurden, bleiben in `watchlist`-Tabelle alte Einträge mit `ON CONFLICT(name) DO NOTHING` bestehen. Case-Varianten ("Nvidia" vs "NVIDIA") werden als verschiedene Einträge angelegt.

**Fix:** Wöchentlicher `watchlist_dedup.py` (So 05:30) merged diese über Ticker-Abgleich und droppt Duplikate.

## Quick Debug

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
```