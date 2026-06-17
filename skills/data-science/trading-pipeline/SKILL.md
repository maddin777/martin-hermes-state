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

## Allgemeine Prinzipien

### Vorschläge immer am System-Kontext messen

Bevor du eine Änderung am Trading-System vorschlägst, prüfe ob sie zu unserem tatsächlichen Betrieb passt:

| Prüfpunkt | Fragen |
|-----------|--------|
| **Haltedauer** | Wir halten 5-14 Tage. Passt der Vorschlag zu multi-day, nicht intraday? |
| **Pipeline-Takt** | Pipeline läuft 1x täglich morgens (04:00). Kein Markt-Daemon. |
| **Hebel** | Paper-Trading mit 1x Hebel + TR-Gebühren (1€/Trade). Intraday-Edge wird killt. |
| **Datenquellen** | yfinance (täglich), YouTube/RSS/Twitter (morgens). Kein Echtzeit-Feed. |
| **Modell-Kosten** | Grok nur für Conviction-Boost (max 20 Calls). Rest via yfinance. |

### DB-First-Prinzip

Martin lehnt hardgecodete Mappings in Python-Code ab. ALLE Konfigurationen, Mappings und Lookup-Tabellen gehören in die SQLite-Datenbank:

| Hardcode (abgelehnt) | DB (gewünscht) |
|----------------------|----------------|
| `KNOWN_TICKERS`-Dict in `technical_validator.py` | `company_aliases`-Tabelle |
| `ISIN_TICKER_MAP` in `company_validator.py` | `canonical_tickers`-Tabelle |
| Ticker-Merge-Map in `export_watchlist.py` | `canonical_tickers`-Tabelle |
| ARM→ARMK Korrektur im Code | `canonical_tickers` mit ARMK→ARM |

**Migration-Pattern:** Neue Tabellen in `watchlist_manager.py` oder `signal_manager.py` anlegen (beide haben Migration-Blöcke mit `PRAGMA table_info` + `CREATE TABLE IF NOT EXISTS`). Seed-Daten im selben Block per `COUNT(*) = 0`-Check, nur bei leerer Tabelle.

**Nicht vergessen:** n8n läuft auf dem Server (Python-Prozesse + n8n-Workflows parallel möglich). YouTube-Faceless-Pipelines etc. sind infra-seitig möglich.

**Faustregel:** Wenn der Vorschlag klingt wie ein HFT- Intraday- oder Hebel-Strategie → nein. Wenn er den daily/weekly Trendfilter verbessert oder bessere Entry-Qualität bei gleicher Haltedauer bringt → ja.

### DB-Connection: Immer `config.db_connect()` statt raw sqlite3

Seit 12.06.2026 gibt es `config.db_connect()` — eine zentrale Funktion die WAL mode + busy_timeout + row_factory setzt. Alle 25 Pipeline-Scripts wurden umgestellt. Prüfung ob ein neues Script korrekt ist: `grep -c \"sqlite3.connect\" scripts/*.py` sollte 0 ergeben.

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
| 04:00 | `trading_pipeline.py` | Orchestrator: YouTube scan → KI Analyse → Watchlist Update → Technical Analysis (yfinance) → Signal Manager. Watchlist Update 2-3h (Grok + yfinance). |
| 04:50 | `llm_validator.py` | ⚠️ Noch in crontab obwohl Fix aussteht (DB-Lock) |
| 05:00 | `nightly_eval.py` | ✅ Sauber (<5s) |
| 09:30 | `active_exit_check.py` | Mid-day exit checks |
| 13-20:15 | `signal_manager.py check_only` | Intraday signal check |
| 15:30 | `active_exit_check.py` | Afternoon exit checks |
| 20:00 (Fr) | `signal_manager.py full` | Weekly signal review |

**Nicht-Selbstständige Scripts:** technical_validator, signal_extractor, watchlist_manager laufen innerhalb von trading_pipeline.py.

### Dashboard
- Port **8081**, Flask app in `skills/trading/dashboard.py`
- Dashboard-Watchdog: Cron d1c92b5337c5, no_agent alle 15min, Script `~/.hermes/scripts/dashboard-watchdog.sh`

### Thematic Pipeline
- Läuft via **eigener system crontab** (nicht orchestriert von trading_pipeline.py):
  - `30 2 * * 1-5` — prediction_market_scanner.py (PM Scanner)
  - `0 3 * * 1-5` — thematic_pipeline.py (Haupt-Pipeline)
  - `0 10 * * 1-5` — drawdown_monitor.py
  - `30 15 * * 1-5` — thesis_monitor.py
  - `0 8 * * 0` — weekly_review.py
  - `0 4 * * 0` — news_cleanup.py
- Scripts: `skills/trading/thematic/`
- Externe APIs: Finnhub, Polymarket
- Finnhub-Key in `~/.hermes/profiles/hermes_trading/.env` — bei 403 siehe `references/finnhub-api-key-management.md`
- PM Scanner Fehler: `NameError: name 'db_connect' is not defined` → `from config import db_connect` fehlt in `prediction_market_scanner.py` (siehe `references/thematic-pipeline-pitfalls.md`)

## Data Flow & Pitfalls

Details siehe `references/` im Skill-Verzeichnis sowie die Erläuterung.md im Obsidian Vault (`/root/obsidian-vault/Trading/Erklaerung.md`).

### Wichtige Pitfall-Referenzen

| Pitfall | Referenz |
|---------|----------|
| Dashboard Watchdog | `scripts/dashboard-watchdog.sh` |
| Finnhub API 403 | `references/finnhub-api-key-management.md` |
| Cron-Log-Format | `references/cron-log-format.md` |
| Short-Strategy | `references/short-strategy-setup.md` |
| Correlation Filter | `references/correlation-filter.md` |
| Weekly Trend Filter | `references/weekly-trend-filter.md` |
| sqlite3.Row .get() Falle | `references/sqlite3-row-get-pitfall.md` |
| Watchlist Dedup | `references/watchlist-table-dedup.md` |
| Closed-Loop Architecture | `references/closed-loop-architecture.md` |
| Dashboard Ghost Entries | `references/dashboard-cron-ghost-entries.md` |

### Diagnose: Pipeline läuft nicht

**Erster Check bei Pipeline-Ausfall:**
```bash
# 1. Läuft trading_pipeline.py überhaupt?
ls /root/.hermes/profiles/hermes_trading/skills/trading/scripts/trading_pipeline.py
# Falls nicht da → in trading/ suchen und zurück ins scripts/ verschieben

# 2. Letzte Pipeline-Logs
grep "TRADING PIPELINE START\\|DONE\\|can't open file\|❌" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10

# 3. Signal Manager crasht mit sqlite3.Row.get()?
grep -B3 "AttributeError\|'sqlite3.Row' object has no attribute 'get'" \
  /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -20
# → Fix in references/sqlite3-row-get-pitfall.md, dann manuell neu starten:
cd /root/.hermes/profiles/hermes_trading/skills/trading && \
  PYTHONPATH=. python3 scripts/signal_manager.py full
```

## Quick Debug

```bash
# Last pipeline run
tail -100 /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log

# Last eval_metrics
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT * FROM eval_metrics ORDER BY date DESC LIMIT 1;"

# Dashboard health
curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/

# System crontab
crontab -l | grep trading

# Finnhub test
curl -s "https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token=$(grep FINNHUB_API_KEY /root/.hermes/profiles/hermes_trading/.env | cut -d= -f2)"
```