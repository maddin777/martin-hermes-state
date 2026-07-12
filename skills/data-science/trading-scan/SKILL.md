---
name: trading-scan
description: "Run the complete Hermes Trading pipeline — macro data, social/RSS/YouTube scan, LLM signal extraction, watchlist management, technical analysis, signal management, nightly evaluation. Use as a single entry point for the daily trading workflow."
version: 1.0.0
author: Hermes
license: MIT
metadata:
  hermes:
    tags: [trading, pipeline, scan, watchlist, signals]
    related_skills: [trading-pipeline]
---

# Trading Scan Bundle

## Overview

Führt die komplette nächtliche Trading-Pipeline aus dem Profil `hermes_trading` aus. Bündelt alle Einzelschritte in einem konsistenten Workflow.

## Pipeline-Schritte (Reihenfolge)

| Schritt | Script | Zeit | Zweck |
|---------|--------|------|-------|
| 1. Fundamental Data | `fundamental_data.py` | 02:00 | FRED Makro, SEC Insider, Put/Call Ratio, Regime-Detection |
| 2. Social Scanner | `social_scanner.py` | 03:00 | RSS Feeds (Seeking Alpha, Bloomberg etc.) + Twitter/X |
| 3. YouTube Scan | `yt_channel_monitor.py` | 04:00 | 23 YouTube-Kanäle scannen |
| 4. KI Analyse | via trading_pipeline | 04:00 | LLM-Extraktion von Unternehmen + Sentiment aus Transkripten |
| 5. Watchlist Update | `watchlist_manager.py` | 04:00 | Watchlist + Conviction Score berechnen |
| 6. Technical Analysis | `technical_validator.py` | 04:00 | EMA/RSI/MACD für Watchlist-Kandidaten |
| 7. Signal Manager | `signal_manager.py` | 04:00 | Entry-Signale, Position-Sizing, Portfolio-Management |
| 8. LLM Validation | `llm_validator.py` | 04:50 | Kreuzvalidierung der Top-Kandidaten |
| 9. Nightly Eval | `nightly_eval.py` | 05:00 | Metriken, Quellen-Qualität, Telegram-Report |
| 10. Watchlist Export | `export_watchlist.py` | 22:05 | Export nach Obsidian |

## Verwendung

### Manueller Durchlauf (alle Schritte)
Startet die Pipeline im Profil hermes_trading und führt alle Schritte nacheinander aus:
```
cd /root/.hermes/profiles/hermes_trading/skills/trading/scripts
python3 trading_pipeline.py
```

### Einzelschritte ausführen
Jedes Script kann einzeln gestartet werden:

**Nacht-Pipeline (02:00-05:00, Mo-Fr):**
```
# Profil-Umgebung laden
source /root/.hermes/profiles/hermes_trading/.env

# Schritt 1-2
python3 fundamental_data.py    # Makro + Insider + PCR
python3 social_scanner.py      # RSS + Twitter

# Schritt 3-7 (Orchestriert)
python3 trading_pipeline.py    # YouTube → Analyse → Watchlist → Technisch → Signale

# Schritt 8-9
python3 llm_validator.py       # Kreuzvalidierung
python3 nightly_eval.py        # Metriken + Report
```

**Intraday (09:00-20:00, täglich):**
```
python3 signal_manager.py check_only  # SL/TP prüfen
python3 active_exit_check.py          # Tech-Check + Profit-Sicherung
```

**Wöchentlich (Sonntag):**
```
# Hermes Cron jobs (automatisiert):
# - 05:30 watchlist_dedup.py (Cron: 472ace6fe18a)
# - 06:00 nightly_eval.py (weekly mode)
# - 07:00 source_lifecycle.py (Quellen-Cleanup)
# - 08:00 strategy_optimizer.py (Parameter-Optimierung)
```

## Status-Check

### Dashboard
```bash
curl -s http://localhost:8081/ | head -50
```

### Letzter Pipeline-Lauf
```bash
tail -30 /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log
```

### Letzte Metriken
```bash
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT date, new_companies, confirmed, avg_conviction, open_positions, win_rate_30d \
   FROM eval_metrics ORDER BY date DESC LIMIT 5;"
```

## Bekannte Probleme

### DB-Lock Cascade
Wenn fundamental_data oder watchlist_manager mit offener SQLite-Connection crasht, blockiert es alle nachfolgenden Jobs („database is locked“).

**Fix:** `PRAGMA busy_timeout=30000` in allen Pipeline-Scripts + `con.close()` im finally-Block.

### Watchlist-Log-Alias
Der Dashboard-Cron-Status für „Watchlist Update“ sucht nach „watchlist_manager“ im Log, aber die Pipeline loggt als „Watchlist Update“. Gelber Status = String-Mismatch.

**Fix:** `LOG_ALIASES = {"watchlist_manager": "Watchlist Update"}` in `get_last_run()` des Dashboards.

## Cron-Jobs (Hermes Daemon)
| Job | Zeit | Zweck |
|-----|------|-------|
| ttwo-catalyst-alarm | So 10:00 | TTWO/GTA6-Katalysator-Check |
| watchlist-dedup | So 05:30 | Watchlist-Deduplizierung |
| vault-insights-daily | 02:45 tägl. | Wiki-Pflege |
| cron-health-daily | 08:00 tägl. | System-Health |

## System-Crontab (Profil hermes_trading)
Alle Pipeline-Jobs laufen über die System-Crontab des Profils. Anzeigen mit:
```bash
crontab -l | grep trading
```

## Backtesting

Seit 11.07.2026 gibt es eine Backtesting-Engine im Trading-Skill-Verzeichnis.
Ermöglicht historische Validierung von Signalen bevor sie im Paper-Trading laufen.

**Pfad:** `/root/.hermes/profiles/hermes_trading/skills/trading/backtesting/`

**Quickstart:**
```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading
python3 -c "
from backtesting import BacktestEngine
from backtesting.alpha_model import AlphaModel
from backtesting.models import Signal
from backtesting.data_client import YFinanceDataClient

class AlwaysBullish(AlphaModel):
    @property
    def name(self): return 'bullish'
    def predict(self, ticker, date, client):
        return Signal(model_name=self.name, ticker=ticker, date=date, value=0.5)

client = YFinanceDataClient()
engine = BacktestEngine(capital=100_000, per_trade=10_000)
result = engine.run_alpha(AlwaysBullish(), ['AAPL'], client,
                          '2025-06-01', '2025-07-01', holding_days=5)
if result.metrics:
    m = result.metrics
    print(f'Trades: {m.n_trades}, Sharpe: {m.sharpe_ratio:.2f}, WR: {m.win_rate:.0%}')
"
```

**Detaillierte Doku:** `Erklaerung.md` Section 16 (im Skill-Verzeichnis und Obsidian).