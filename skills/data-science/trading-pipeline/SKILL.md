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
| `adapt_strategy()` Regime-Blindheit | `references/adapt-strategy-regime-blindness.md` |
| Sector Blacklist + Probation | `references/sector-blacklist-probation.md` |
| Private Company OTHER-Klassifikation | `references/other-sector-private-companies.md` |
| Canonical-Merge überschreibt Sector | `references/export-watchlist-sector-merge.md` |

### Session-Start-Protokoll: Proaktiver Pipeline-Check

**Regel (aus Martins Korrektur vom 18.06.2026):** Sobald Martin eine Session startet — bevor er irgendwas fragt — den Dashboard- und Cron-Status checken. Nicht warten bis er ein Problem meldet.

```bash
# 1. Dashboard erreichbar?
curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/

# 2. Gelbe/rote Einträge im Cron-Tab?
# Dashboard aufrufen und Cron-Tab visuell checken
# Oder cron.log auf ERROR/Traceback durchsuchen
grep -E "ERROR|Traceback|database is locked" \
  /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10

# 3. Letzter Pipeline-Status
grep "TRADING PIPELINE DONE" \
  /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -3

# 4. eval_metrics aktuell?
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT date, open_positions, win_rate_30d FROM eval_metrics ORDER BY date DESC LIMIT 1;"
```

Bei Abweichung (gelb, rot, Fehler im Log, oder Pipelineschritt fehlt) sofort Fehleranalyse starten — nicht auf Nachfrage warten.

### 🔴 HARD RULE: KEIN `.get()` auf sqlite3.Row

**Dieser Fehler trat am 19.06.2026 ZUM ZWEITEN MAL auf**, obwohl Pitfall 16 dokumentiert war. Signal Manager crashte mit `AttributeError: 'sqlite3.Row' object has no attribute 'get'`.

**Warum passiert das immer wieder:** Du fügst eine neue Spalte via ALTER TABLE hinzu und willst beim Lesen elegant auf None prüfen -> greifst zu `row.get("new_col")`. Das crasht, weil `sqlite3.Row` KEIN dict ist.

**Die Regel (MERKEN, nicht nur lesen):**
```python
# CRASHT IMMER - sqlite3.Row hat kein .get()
pos.get("asset_type", "STANDARD")
row.get("any_column", default)

# FUNKTIONIERT IMMER - Keys-Check + Index-Zugriff
pos["asset_type"] if "asset_type" in pos.keys() else "STANDARD"
```

**Wann passiert das?** Immer wenn du:
- Eine neue Column via ALTER TABLE in `init_db()` hinzufügst
- Dann in `check_open_positions()` oder `open_new_positions()` auf diese Column zugreifst
- Dabei `.get("col", default)` statt `"col" in row.keys() else default` verwendest

**Prävention:**
- Nach JEDEM ALTER TABLE: prüfe ob irgendwo ein `.get()` auf Row-Objekte neu dazugekommen ist
- Besser: direkt Index-Zugriff verwenden, wenn die Spalte existiert (nach Migration sicher)
- NIE `row.get()` schreiben - es gibt kein Szenario wo das auf sqlite3.Row funktioniert

### 🔴 OTHER-Sektor Fallback: Private Companies

Wenn yfinance keinen Sektor liefert (Sektor = "OTHER"), landen private Companies bisher default auf STANDARD. Seit 20.06.2026 gibt es `references/other-sector-private-companies.md` mit einer manuell gepflegten Klassifikation bekannter Private Companies (OpenAI→TECH, SpaceX→STANDARD, Schwarz Gruppe→DEFENSIVE etc.).

**Bei Sektor = "OTHER" immer prüfen:**
1. Ist es eine bekannte Private Company aus der Referenz?
2. Falls ja → korrekten Asset-Type zuweisen
3. Falls nein → STANDARD (Default)

Die Referenz enthält 23 klassifizierte Unternehmen plus Implementierungsvorschlag für `config.py`.

### 🔴 WICHTIG — Proaktive Fehleranalyse (Pflicht)

**Martin hat sich zweimal am 18.06. darüber beschwert, dass auf gelbe Status keine RCA kam.** Diese Regel ist NICHT optional:

1. **Jede Abweichung = sofort analysieren.** Nicht warten bis Martin fragt. Nicht denken "das ist nur ein Ghost Entry". Nicht in andere Tasks abtauchen.
2. **RCA innerhalb derselben Antwort liefern.** Nicht "ich schau mal" und dann später — direkt: Status erfassen → Log lesen → Ursache identifizieren → Fix vorschlagen.
3. **Wenn die Ursache klar ist, sofort fixen.** Ghost Entry → aus descriptions entfernen. `.get()` Bug → patchen. DB Lock → WAL-Checkpoint. Keine "soll ich?"-Rückfrage bei klaren Fehlern.
4. **Wenn die Ursache unklar ist, trotzdem liefern:** "Dashboard zeigt gelb für X. Log zeigt Y. Vermute Z, prüfe gerade A."

**Checkliste beim Session-Start (Pflicht, bevor du irgendwas anderes tust):**
- `curl -s http://localhost:8081/` — Dashboard erreichbar?
- Dashboard Cron-Tab visuell checken: gibt es gelbe/rote Einträge?
- `grep "ERROR\|Traceback\|database is locked" cron.log | tail -10`
- `grep "TRADING PIPELINE DONE" cron.log | tail -3`

**Bekannte Fehlermuster auf einen Blick:**
- Gelber Ghost-Eintrag → Pitfall 14 (Dashboard Ghost Entries)
- `database is locked` → Orphaned Connection (Pitfall 12) oder Timing-Konflikt
- `sqlite3.Row` AttributeError → Pitfall 16
- Pipeline läuft länger als 1h → Watchlist Update zu langsam (Grok/yfinance API)
| `Finnhub 403` → API-Key abgelaufen oder limitiert (siehe `references/finnhub-api-key-management.md`)
| `pos.get("asset_type")` → Pitfall 16 (sqlite3.Row) — `pos["asset_type"] if "asset_type" in pos.keys() else "STANDARD"` verwenden
| **`cron_health.py` ❌ false-positive** → Timing-Konflikt: `cron-health-daily` und `strategy_optimizer` starten beide um 08:00 (Sonntag). Der Optimizer braucht ~2 Min, der Health-Check findet nur START ohne DONE → flagged als crashed. Fix: staggered Schedules (z.B. health um 08:30).
| **Config-Drift (SL=1.0/TP=4.0)** → adapt_strategy() hat SL/TP ohne Regime-Prüfung angepasst. Im Sideways-Markt führte das zu 81% SL_RATE + −358€ P&L. Fix: Regime-Check eingebaut, Config reset auf SL=1.5/TP=2.5. Siehe references/adapt-strategy-regime-blindness.md. |
| **Channel in CHANNELS_FALLBACK aber nicht in source_registry** → yt_channel_monitor.py liest Kanäle aus der source_registry-DB. Die CHANNELS_FALLBACK wird NUR genutzt wenn source_registry komplett leer ist. Fix: INSERT OR IGNORE INTO source_registry.
| **Canonical-Merge überschreibt Sector mit 'Other'** → `export_watchlist.py` merged Aliase (ARMK→ARM) und kopiert blind den Sector des höheren Conviction-Scores. Alias-Ticker haben oft 'Other' weil nicht in `companies`. Fix: Merge-Logik prüft `if w["company_sector"] != 'Other' or existing["company_sector"] == 'Other'`. Details in `references/export-watchlist-sector-merge.md`.

### Manuelles Nachholen eines YouTube-Kanals (außerhalb der Pipeline)

Wenn ein Kanal neu in die `source_registry` aufgenommen wurde, aber die Pipeline
erst morgen früh um 04:00 läuft:

1. **Videos scannen und in DB einfügen:**
   ```python
   from config import db_connect
   from scripts.yt_channel_monitor import get_recent_video_ids, get_video_meta, get_transcript
   
   con = db_connect()
   url = 'https://www.youtube.com/@Handle'
   name = 'Kanalname'
   
   video_ids = get_recent_video_ids(url, 30)
   for vid_id in video_ids:
       existing = con.execute('SELECT video_id FROM videos WHERE video_id=?', (vid_id,)).fetchone()
       if existing:
           print(f'  ⏭ {vid_id} bereits in DB')
           continue
       date_str, title = get_video_meta(vid_id)
       if not date_str or not title:
           print(f'  ⚠ {vid_id} keine Metadaten')
           continue
       transcript = get_transcript(vid_id)
       con.execute('INSERT OR IGNORE INTO videos (video_id, channel, title, upload_date, transcript, status) VALUES (?, ?, ?, ?, ?, ?)',
           (vid_id, name, title, date_str, transcript, 'new'))
       print(f'  📹 {title} ({date_str})')
   con.commit()
   ```

2. **Signal-Extraktion für die neuen Videos triggern:**
   ```python
   from config import db_connect
   from scripts.signal_extractor import analyze
   
   con = db_connect()
   videos = con.execute(
       "SELECT * FROM videos WHERE channel = '<Name>' AND status = 'new' ORDER BY upload_date DESC"
   ).fetchall()
   
   for row in videos:
       if not row['transcript']:
           continue
       result = analyze(row['transcript'], row['channel'], row['title'], row['upload_date'])
       result['source'] = {'channel': row['channel'], 'title': row['title'], 
                           'date': row['upload_date'], 'video_id': row['video_id']}
       con.execute("UPDATE videos SET status='done', analyzed_at=? WHERE video_id=?",
           (datetime.now().isoformat(), row['video_id']))
       con.commit()
       print(f"✓ {len(result.get('companies',[]))} Unternehmen: {[c['name'] for c in result.get('companies',[])]}")
   ```

3. **Channel-Statistik im Dashboard aktualisieren:** Die Source-Seite zeigt
   Mentions aus `watchlist_mentions`. Nach der Signal-Extraktion muss der
   `watchlist_manager` oder `signal_manager` laufen um die neuen Signale in
   die Watchlist zu überführen. Falls das Dashboard noch 0 anzeigt, liegt's
   daran dass dieser Schritt noch aussteht — die Pipeline macht das morgen früh.

**Pitfall `videos`-Tabellen-Schema:** Die `videos`-Tabelle hat KEINE `id`-Spalte.
`video_id` ist der Primärschlüssel (TEXT). Bei `SELECT` immer `WHERE video_id=?`
verwenden, nicht `WHERE id=?`.

⚠ **Kosten:** Die Signal-Extraktion nutzt OpenRouter (DeepSeek, Fallback gpt-4o-mini).
Pro Video fallen 1-2 API-Calls an (je nach Chunk-Anzahl). Bei vielen Videos
lieber die nächste Pipeline abwarten.

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

## Dynamische Exit-Regeln (seit 18.06.2026)

**Konzept:** ATR-Multiplikatoren werden nicht mehr global, sondern abhängig vom **Asset-Typ** vergeben. Der Asset-Typ wird aus dem Sektor abgeleitet (siehe `config.py`).

### Asset-Typ Mapping

| Sektor | Asset-Typ | Begründung |
|--------|-----------|------------|
| Technology, Communication Services | **TECH** | Höhere Vola, mehr Raum nötig |
| Consumer Defensive, Healthcare, Utilities | **DEFENSIVE** | Niedrige Vola, enge Stops |
| Alle anderen | **STANDARD** | Default (1.5× ATR) |

### Multiplikatoren pro Typ

| Parameter | STANDARD | TECH | DEFENSIVE |
|-----------|----------|------|-----------|
| Stop-Loss | 1.5× ATR | 2.0× ATR | 1.0× ATR |
| Take-Profit | 2.5× ATR | 3.5× ATR | 2.0× ATR |
| Partial Exit | +1.5× ATR | +2.0× ATR | +1.0× ATR |
| Breakeven | +2.0× ATR | +2.5× ATR | +1.5× ATR |
| Trailing Step | 0.75× ATR | 0.75× ATR | 0.5× ATR |

> **Trailing Step geändert am 25.06.2026:** von 0.5× auf 0.75× (STANDARD/TECH). Der alte Wert (0.5×) führte dazu, dass ein normaler Pullback von 0.6× ATR den Trailing Stop auslöste bevor der Trade das Take-Profit erreichte. 0.75× gibt mehr Raum im Sideways-Markt.

### Code-Struktur

- **`config.py`** — `SECTOR_TO_ASSET_TYPE`, `ASSET_TYPE_MULTIPLIERS`, `get_asset_type()`, `get_asset_multipliers()`
- **`signal_manager.py`** — Liest asset_type bei Entry (wird in DB gespeichert), nutzt asset_type-spezifische Multiplikatoren für SL/TP und Trailing Stop
- **`active_exit_check.py`** — Nutzt asset_type-spezifische Multiplikatoren für Thesis-BROKEN und Trailing Stop
- **DB:** `positions.asset_type`-Spalte (seit 18.06., per ALTER TABLE migriert)

### 🔴 Strategie-Config-Drift (Critical)

**Problem:** `adapt_strategy()` in `signal_manager.py` passt SL/TP-Multiplikatoren basierend auf Trade-Ergebnissen an — **ohne Marktregime-Prüfung**. Das führte zu einer Config-Drift von 1,5× SL / 2,5× TP → 1,0× SL / 4,0× TP.

**Abwärtsspirale im Sideways:**
```
Sideways → viele SL_HITs (normal) → SL enger → noch mehr SL_HITs → SL 1,0× → 81% SL-Rate
```

**Fix (25.06.2026):**
1. `adapt_strategy()` prüft jetzt Regime aus `regime_history` — im Sideways werden SL/TP NICHT angepasst, nur `min_confidence` erhöht
2. SL-Untergrenze auf 1,2× (war 1,0×) gesetzt
3. TP-Obergrenze auf 3,5× (war 4,0×) gesetzt
4. `consecutive_losses` auf 0 zurückgesetzt
5. Config auf SL=1,5×, TP=2,5× zurückgesetzt
6. `trailing_step` von 0,5× auf 0,75× erhöht

Siehe `references/adapt-strategy-regime-blindness.md`.

### 🔴 Sector Blacklist + Probation (seit 25.06.2026)

Sektoren mit negativer 14d-P&L (≥3 Trades) werden automatisch auf eine Blacklist gesetzt:

| Phase | Dauer | Regel |
|-------|-------|-------|
| **Gesperrt** | 14d Cooldown | Keine Entries in diesem Sektor |
| **Probation** | 1 Trade | 50% Position Size erlaubt |
| **Re-Entry** | Gewinn → frei | Sektor von Blacklist entfernt |
| **Re-Entry** | Verlust → +14d | Erneuter Cooldown |

**Ausgelöst von:** `update_sector_blacklist()` am Start von `open_new_positions()`.
**Geprüft von:** `is_sector_allowed()` vor jedem Entry.
**Config:** `strategy_config.json` → `sector_blacklist {}`, `sector_cooldown_days: 14`, `sector_probation_size_pct: 0.5`.

Siehe `references/sector-blacklist-probation.md`.

### SP500 SMA200 Cron-Job (Amumbo-Exit)

- Cron `sp500-sma200-check` (1bbecc075d3e), Mo–Fr 10:00, no_agent
- Script: `~/.hermes/scripts/sp500_sma200_check.py`
- Prüft ob S&P 500 (Proxy MSCI USA) über/unter SMA200 → Entscheidung für Amumbo (A0X8ZS)
- Output: `🟢 AMUMBO HALTEN` / `🔴 AMUMBO RAUS`
- Doku: `wiki/concepts/Leveraged ETFs.md` (LETF-Exit-Modus)

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

# SP500 SMA200-Check (Amumbo-Exit)
python3 /root/.hermes/scripts/sp500_sma200_check.py
```