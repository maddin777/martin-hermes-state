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
| **Pipeline-Takt** | Pipeline läuft 1x täglich morgens (03:30). Kein Markt-Daemon. |
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

**Bekannte Tabellen:** `companies`, `company_aliases`, `source_registry`, `watchlist_mentions`, `watchlist`, `positions`, `portfolio`, `macro_data`, `regime_history`, `thesis_status_log`, `theme_definitions`, `theme_beneficiaries`, `canonical_tickers`, `validation_rejects`, `pead_cache` (6h TTL).

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

### Cron Schedule

**Grundsatz:** Pipeline-Jobs (Analyse/Screening) laufen Mo–Fr. Safety-Jobs (Exit-Checks, SL/TP-Management, Breaking News) laufen **täglich** — seit 07.07.2026. Samstag war vorher eine tote Zone (kein `6` in der Crontab).

| Zeit | Script | Tage | Purpose |
|------|--------|------|---------|
| 01:30 | `fundamental_data.py` | Mo–Fr | Macro data, insider trades, put/call ratios, regime detection |
| 02:00 | `social_scanner.py` | Mo–Fr | RSS feeds (Seeking Alpha, Bloomberg etc.) + Twitter/X (twitterapi.io, 6 accounts) |
| 03:30 | `trading_pipeline.py` | Mo–Fr | Orchestrator: YouTube scan → KI Analyse → Watchlist Update → Technical Analysis (yfinance) → Signal Manager. Watchlist Update 2-3h (Grok + yfinance). Um 03:30 (statt 04:00) um mehr Puffer vor nightly_eval (05:00) zu haben. Social_scanner (03:00) läuft vorher durch. |
| 04:50 | `llm_validator.py` | Mo–Fr | ⚠️ Noch in crontab obwohl Fix aussteht (DB-Lock) |
| 05:00 | `nightly_eval.py` | Mo–Fr | ✅ Sauber (<5s) |
| 09:30 | `active_exit_check.py` | **täglich** | Mid-day exit checks |
| 10-17h | `breaking_news_monitor.py` | **täglich** | Stündlicher Breaking-News-Scan |
| 13-20h | `signal_manager.py check_only` | **täglich** | Intraday SL/TP check |
| 15:30 | `active_exit_check.py` | **täglich** | Afternoon exit checks |
| 20:00 (Fr) | `signal_manager.py full` | Fr | Weekly signal review |

**Wochenend-Crontab-Änderung (07.07.2026):** `active_exit_check`, `signal_manager check_only`, `breaking_news_monitor` wurden von `* 1-5` auf `* *` (täglich) umgestellt. Die Pipeline-Jobs blieben Mo–Fr. Samstag (`6`) war vorher in keiner Crontab-Regel definiert — absolute tote Zone.

**Nicht-Selbstständige Scripts:** technical_validator, signal_extractor, watchlist_manager laufen innerhalb von trading_pipeline.py.

### Source Lifecycle — Quelle verwalten (seit 07.07.2026)

Quellen (YouTube-Kanäle, RSS-Feeds, Twitter-Accounts) werden in `source_registry` verwaltet. Der `source_lifecycle.py` läuft sonntags und bewertet die Performance pro Quelle.

**Pipeline:** `candidate → probation → active → penalized (weight=0.3)`

| Phase | Status | Scannt? | Weight | Auslöser |
|-------|--------|---------|--------|----------|
| Neu | `candidate` | ✅ Ja | 1.0 | Manuell hinzugefügt oder automatisch entdeckt |
| Test | `probation` | ✅ Ja | 0.5 | Nach manueller Promotion aus candidate |
| Aktiv | `active` | ✅ Ja | 1.0 (dynamisch 0.3–2.5) | Probation bestanden (≥5 Trades, WR≥40%) |
| **Penalisiert** | `active` **mit weight=0.3** | ✅ **Ja** | **0.3** | Schlechte Performance (WR<35%, avg_pnl negativ, ≥3 Verluste) |
| Entfernt | `removed` | ❌ Nein | – | Sehr schlecht (WR<20%) ODER seit 60+ Tagen keine Mentions |

**Wichtige Änderung (07.07.2026):** Früher wurden schlechte Quellen auf `status='suspended', enabled=0` gesetzt → Scan komplett gestoppt. Martin fand das nicht gut ("solche Quellen komplett rausschmeissen finde ich nicht gut"). **Neue Logik:** Statt suspendieren wird das Weight auf `penalize_min_weight` (0.3) gesetzt und `enabled=1` bleibt. Die Quelle wird weiter gescannt, aber ihre Signale haben kaum Einfluss. 10 vorher suspendierte Kanäle wurden am 07.07. reaktiviert.

**Gewichtsanpassung (`adjust_weights()`):** Läuft sonntags im `source_lifecycle.py`. **Seit 15.07.2026 basierend auf `avg_pnl_per_trade` statt `win_rate_90d`** (Post-Mortem-Ergebnis: Quellen mit hoher WR aber negativem P&L, z.B. beating beta 67% WR / -18€/Trade, wurden überbewertet). Quellen mit P&L ≥ +10€ bekommen +15% Gewicht (max 2.5). Quellen mit P&L ≤ -10€ bekommen -20% Gewicht (min 0.3). Quellen mit <5 Trades bleiben unverändert.

**Dashboard:** Im Quellen-Tab siehst du pro Channel:
- **Status-Badge**: 🟢 Aktiv, 🧪 Probation, 🆕 Kandidat, ⏸ Deaktiviert
- **Win Rate**: farbig (grün ≥50%, gelb ≥30%, rot <30%)
- **Ø PnL**: farbig (grün positiv, rot negativ)
- **Weight**: farbig (grün ≥1.0, gelb ≥0.5, orange <0.5)
- **Grund**: Warum penalisiert (z.B. "WR=0%; avg_pnl=-54.7€")

### Dashboard
- Port **8081**, Python HTTP server in `skills/trading/scripts/dashboard.py`
- Läuft **unter systemd** (`trading-dashboard.service`), nicht als Background-Prozess. Restart: `systemctl restart trading-dashboard.service`
- **override.conf** beim systemd-Service setzt `DASHBOARD_BIND=0.0.0.0` und `DASHBOARD_TOKEN`
- **Live copy**: `/root/.hermes/profiles/hermes_trading/skills/trading/scripts/dashboard.py`
- **State backup**: `/root/martin-hermes-state/profiles/hermes_trading/skills/trading/scripts/dashboard.py`
  - ⚠️ Beim Editieren: Die Live-Datei unter `.hermes` läuft im Dashboard-Prozess (systemd). Die `martin-hermes-state`-Kopie ist ein git-backup. Immer BEIDE editieren, ODER die `.hermes`-Kopie direkt editieren und dann `cp` in den State.
- **`load_dotenv()` seit 07.07.2026:** Der `__main__`-Block lädt `.env` aus dem Trading-Profil (`load_dotenv(os.path.join(SCRIPTS_DIR, "..", ".env"))`), damit `DASHBOARD_BIND=0.0.0.0` immer gesetzt ist — auch ohne den Watchdog-Workaround.
- Dashboard-Watchdog: Cron d1c92b5337c5, no_agent alle 15min, Script `~/.hermes/scripts/dashboard-watchdog.sh`
  - ⚠️ Watchdog lädt seit 07.07.2026 die `.env` vor dem Restart (`export $(grep -v '^#' .env | xargs)`), damit `DASHBOARD_BIND=0.0.0.0` gesetzt ist. Ohne diesen Fix bindet der Neustart auf `127.0.0.1` → Dashboard ist nur noch lokal erreichbar.
- **Dashboard starten mit LAN-Zugriff:** Immer `.env` exportieren, sonst Default `127.0.0.1`:
  ```bash
  cd /root/.hermes/profiles/hermes_trading/skills/trading
  export $(grep -v '^#' /root/.hermes/profiles/hermes_trading/.env | xargs)
  venv/bin/python scripts/dashboard.py
  ```
  Die `.env` enthält `DASHBOARD_BIND=0.0.0.0` und `DASHBOARD_TOKEN=***`. Der Token wird für POST-Mutationen (Buttons im Dashboard) benötigt.
- **start_dashboard.sh** (Wrapper): `/root/.hermes/scripts/start_dashboard.sh` — sourced .env und startet dashboard.py. Der Watchdog ruft dieses Script nicht auf (hat eigenes `export`-Inline). Bei manuellen Neustarts das Script verwenden.

#### Dashboard-Architektur

Das Dashboard ist ein **Single-File Python HTTP Server** mit inline HTML/CSS/JS. Kein Framework, keine Templates.

**Neue Section hinzufügen (Pattern):**
1. **Tab-Button** in `tab-nav` (Zeile ~954):
   ```html
   <button class="tab-btn" onclick="showTab('exits')" style="color:#ff9800">🚪 Exits</button>
   ```
2. **Tab-Content** nach dem letzten Tab-Container:
   ```html
   <!-- Tab: Exits -->
   <div id="tab-exits" class="tab-content">
       {build_exits_section(data)}
   </div>
   ```
3. **`build_*_section(data)`-Funktion** vor `build_thematic_section()`:
   - Bekommt `data`-Dict (open_pos, closed, watchlist, cfg, stats etc.)
   - Gibt HTML-String zurück (inline SVG, Tabellen, etc.)
   - SVG-Visualisierungen sind selbst-gerendert (kein externes JS/SVG-Lib)

**Bestehende Tabs:** portfolio, watchlist, sources, quality, cron, thematic, **exits**

**Quellen-Tab (Sources):** Zeigt seit 07.07.2026 pro YouTube-Kanal:
- Name + Status-Badge (🟢 Aktiv, 🧪 Probation, 🆕 Kandidat, ⏸ Deaktiviert)
- 30-Tage Mentions
- Win Rate (farbig nach Qualität)
- Ø PnL pro Trade
- Weight (farbig)
- Grund für Penalty (falls vorhanden)
- Datenquelle: `source_registry`-Tabelle + `watchlist_mentions`-Aggregat

#### Exit Management — Stairway to Heaven (🚪 Exits-Tab, seit 06.07.2026)

Visuelle Step-Out-Planung für offene Positionen:

**Standard-Stairway-Levels:** 25% @ 1× ATR → 25% @ 2× ATR → 50% @ 3× ATR

**Pro Position:**
- **SVG-Stairway-Chart** (200×160px): Entry → TP1 → TP2 → TP3 → TP als Treppe
  - Gitterlinien bei 1×, 2×, 3× ATR (horizontal)
  - 🟢 Punkt = aktueller Preis (grün/rot je P&L)
  - 🔻 Rot = Stop-Loss, 🔺 Orange = Trailing, ◆ Grün = Take-Profit
  - — Blau = Entry-Preis
  - ✅ Grün = Step erreicht, ⏳ Orange = Step noch aktiv
- **Key-Values-Tabelle**: Entry, SL, TP, Aktuell, Trailing, ATR, Größe, Trail-Status, Step-out-Fortschritt
- **Step-Out-Badges**: zB `TP1: 25% @ 135.20 ✅` / `TP3: 50% @ 148.30 ⏳`

**Datenquellen:**
- `data["open_pos"]` aus `get_data()` → Positionen mit entry, sl, tp, trailing_sl, atr_at_entry
- `yfinance.Ticker().fast_info['last_price']` für aktuelle Kurse (live pro Request)
- ATR-Fallback: `abs(tp - entry) / 3.0` wenn `atr_at_entry` fehlt

**Funktion:** `build_exits_section(data)` in `dashboard.py`

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
| **Dashboard Ghost Entries** | `references/dashboard-cron-ghost-entries.md` |
| **Dashboard Two Copies** (live vs state) | `references/live-vs-state-backup.md` |
| **Dashboard Sortable Table Pattern** | `references/dashboard-sortable-table-pattern.md` |
| `adapt_strategy()` Regime-Blindheit | `references/adapt-strategy-regime-blindness.md` |
| Sector Blacklist + Probation | `references/sector-blacklist-probation.md` |
| Private Company OTHER-Klassifikation | `references/other-sector-private-companies.md` |
| Canonical-Merge überschreibt Sector | `references/export-watchlist-sector-merge.md` |
| yfinance Date-Parsing (unconverted data) | `references/yfinance-date-parsing-fix.md` |
| Sektor-Exposure-Cap (70%) | `references/sector-exposure-cap.md` |
| **LLM API `content: null` — NoneType Crash** | `references/llm-api-content-none-pattern.md` |
| **DB Lock: Transaction-in-Loop mit API-Calls** | `references/db-lock-short-transactions.md` |
| **YouTube Scan DB Lock: Inter-Cron-Job Kaskade** | `references/yt-cleanup-db-lock.md` |
| **Cron Health: Pipeline-Block-Slicing** | `references/cron-health-slicing-bug.md` |
| **PEAD Signal (Post-Earnings Drift)** | `references/pead-signal.md` |

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

### 🔴 PYTHONPATH — Subprozesse finden Module nicht

**Problem:** Die `run()`-Funktion in `trading_pipeline.py` startet Subprozesse via `subprocess.run()`. Diese **erben kein PYTHONPATH** von der Crontab-Umgebung. Folge: `ModuleNotFoundError: No module named 'config'` (YouTube Scan) oder `ImportError` aus falschem `utils` (Hermes-eigenes statt Trading-utils).

**Symptome:**
- YouTube Scan ❌: `No module named 'config'`
- Mehrere Pipeline-Schritte ❌: `ImportError: cannot import name 'get_technical_score' from 'utils' (/root/.hermes/hermes-agent/utils.py)`
- **KEIN** DB-Lock (WAL-Checkpoint im Log zeigt ✅) — das ist das Unterscheidungsmerkmal zum DB-Lock-Kaskaden-Fehler

**Fix:** In `trading_pipeline.py` `run()`-Funktion: `env = os.environ.copy()` + `env["PYTHONPATH"] = TRADING_ROOT` an `subprocess.run(cmd, env=env)` übergeben.

**Prävention:** Bei jedem neuen Script das per `trading_pipeline.py` gestartet wird: prüfe dass es `from config import ...` verwendet (kein `sys.path.insert`).

### 🔴 CRON HEALTH — Pipeline zeigt ⚠️ unknown (gelb)

**Problem:** Der `cron_health.py` sucht nach `✅ ... DONE` im Pipeline-Block. Die Pipeline schrieb `TRADING PIPELINE DONE: HH:MM` ohne ✅ → `⚠️ unknown` (gelb) im Health-Check.

**Symptom:** Alle Pipeline-Schritte sind ✅, aber `cron_health.py` zeigt `⚠️ trading_pipeline`.

**Fix:** `_print(f"✅ TRADING PIPELINE DONE: ...")` — der ✅-Prefix ist notwendig für den Health-Check-Regex `✅\s*.*DONE`.

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
- `database is locked` → Transaction-in-Loop-Pattern (API-Call zwischen execute und commit) oder **Inter-Cron-Job Kaskade** (vorgelagerter Job hält Lock, crasht, und lässt offene Transaktion). Siehe `references/db-lock-short-transactions.md` und `references/yt-cleanup-db-lock.md`. **Cascading Lock erkennen:** Wenn 4 Pipeline-Schritte ❌ sind (YouTube + Screener + Watchlist + Signal Manager), ist der YouTube Scan INSERT-Crash die Ursache — nicht einzeln debuggen.
- `sqlite3.Row` AttributeError → Pitfall 16
- Pipeline läuft länger als 1h → Watchlist Update zu langsam (Grok/yfinance API)
| `Finnhub 403` → API-Key abgelaufen oder limitiert (siehe `references/finnhub-api-key-management.md`)
| `pos.get("asset_type")` → Pitfall 16 (sqlite3.Row) — `pos["asset_type"] if "asset_type" in pos.keys() else "STANDARD"` verwenden
| **`cron_health.py` ❌ false-positive** → Timing-Konflikt: `cron-health-daily` und `strategy_optimizer` starten beide um 08:00 (Sonntag). Der Optimizer braucht ~2 Min, der Health-Check findet nur START ohne DONE → flagged als crashed. Fix: staggered Schedules (z.B. health um 08:30).
| **`cron_health.py` ⚠️ trading_pipeline unknown (gelb)** → Pipeline schrieb `TRADING PIPELINE DONE` ohne ✅-Prefix. Der Health-Check-Regex `✅\s*.*DONE` matched nicht. **Fix:** `_print(f"✅ TRADING PIPELINE DONE: ...")`. Siehe `references/cron-health-slicing-bug.md`. |
| **`ModuleNotFoundError: No module named 'config'`** → Subprozess findet Trading-Verzeichnis nicht. **Fix:** PYTHONPATH in `subprocess.run(env=...)` setzen. Kein DB-Lock — WAL-Checkpoint läuft sauber. |
| **`ImportError: cannot import name 'get_technical_score' from 'utils'`** → Lädt Hermes-eigenes `utils.py` statt Trading-utils. Gleiche Ursache wie ModuleNotFoundError — PYTHONPATH fehlt. **Fix:** PYTHONPATH in `subprocess.run(env=...)` setzen. |
| **`cron_health.py` false-negative "Keine Jobs"** → Regex `(\\d+)` scheiterte an eintstelligen Tagen (`Jul  7` = double space zwischen Monat und Tag). **Fix (07.07.2026):** `\\s+(\\d+)` im Datums-Regex. Betrifft Tage 1-9 jedes Monats. Alle 6 Tage im Monat wurden fälschlich als "keine Jobs" gemeldet. |
| **`cron_health.py` ⚠️ Pipeline-interne Jobs ausserhalb des Blocks** → Pipeline-interne Marker (YouTube Scan DONE, KI Analyse DONE) werden vom Health-Check nur im Pipeline-Block gesucht. Wenn die Pipeline länger läuft als bis zum nächsten Cron-Job (z.B. YouTube Scan 04:00→05:45, nightly_eval feuert um 05:00), liegt der DONE-Marker **ausserhalb** des Pipeline-Blocks. Der Health-Check findet nur START ohne DONE → ⚠️. **Symptom:** `cron_health.py` zeigt ⚠️ für einen Pipeline-Schritt, obwohl der Scan erfolgreich war. **Diagnose:** Prüfe ob die DONE-Zeile (z.B. `=== HH:MM YouTube Scan DONE ===`) nach dem START-Marker des nächsten Cron-Jobs liegt. **Fix:** Entweder Pipeline-Block-Slicing erweitern (DONE-Marker auch im folgenden Block akzeptieren) oder Scan-Wartezeiten reduzieren (z.B. YouTube 120s→60s) damit er vor dem nächsten Cron-Job fertig ist. Siehe `references/cron-health-slicing-bug.md`.
| **PM Scanner: `result["content"] is None` → AttributeError** → `llm_client.parse_json_response()` crasht wenn OpenRouter `content: null` liefert. Fix: None-Check in `parse_json_response()` vor `.strip()`.
| **Theme Discovery: `database is locked`** → Kaskade von PM Scanner-Crash (offene Transaktion) + fehlender `busy_timeout` in `theme_discovery.py` nutzt raw `sqlite3.connect()` statt `config.db_connect()`. Fix: `config.db_connect()` verwenden (WAL + busy_timeout).
| **Config-Drift (SL=1.0/TP=4.0)** → adapt_strategy() hat SL/TP ohne Regime-Prüfung angepasst. Im Sideways-Markt führte das zu 81% SL_RATE + −358€ P&L. Fix: Regime-Check eingebaut, Config reset auf SL=1.5/TP=2.5. Siehe references/adapt-strategy-regime-blindness.md. |
| **Channel in CHANNELS_FALLBACK aber nicht in source_registry** → yt_channel_monitor.py liest Kanäle aus der source_registry-DB. Die CHANNELS_FALLBACK wird NUR genutzt wenn source_registry komplett leer ist. Fix: INSERT OR IGNORE INTO source_registry.
| **Canonical-Merge überschreibt Sector mit 'Other'** → `export_watchlist.py` merged Aliase (ARMK→ARM) und kopiert blind den Sector des höheren Conviction-Scores. Alias-Ticker haben oft 'Other' weil nicht in `companies`. Fix: Merge-Logik prüft `if w["company_sector"] != 'Other' or existing["company_sector"] == 'Other'`. Details in `references/export-watchlist-sector-merge.md`. |
| **yfinance "unconverted data remains"** → yfinance/pandas wirft ValueError bei Datums-Strings mit TZ-Suffix (z.B. `2026-06-28 00:00:00+00:00`). Killt alle `yf.download()`-Calls. Fix in fundamental_data.py: Monkey-Patch auf `_strptime._strptime` mit `dateutil.parser`-Fallback. Siehe `references/yfinance-date-parsing-fix.md`. |
| **Sektor-Exposure-Cap (seit 28.06.2026)** → max 70% Portfolio-Exposure pro Sektor, nicht mehr max 2 Positionen. Prüfung in signal_manager.py **nach** Sizing mit tatsächlicher position_size. Config: `strategy_config.json: max_sector_exposure_pct: 0.70`. Grund: Quellen sind tech-lastig — ein Sektor soll dominieren können. Siehe `references/sector-exposure-cap.md`. |
| **Dashboard Sources Tab — Channel case-mismatch** → Quellen-Tab zeigt für YouTube-Kanäle `–` als letzten Eintrag, obwohl 190+ Mentions existieren. Ursache: `watchlist_mentions.channel` speichert lowercase (`"urban jäkle"`), CHANNELS_FALLBACK in `yt_channel_monitor.py` hat `"Urban Jäkle"`. Dashboard matcht case-sensitive → kein Treffer. Fix: `stats_ci = {k.lower(): v for k, v in stats.items()}` in `build_sources_section()`. |
| **Thematic Dashboard — unable to open database file** → Thematic-Tab zeigt Fehler statt Inhalt. `dashboard_thematic.py` berechnet `DB_PATH_ABS` mit einem `os.path.dirname()` zu viel → zeigt auf `skills/data/trading.db` (existiert nicht) statt `skills/trading/data/trading.db`. Fix: ein `os.path.dirname()` entfernen, sodass nur `os.path.dirname(os.path.abspath(__file__))` + `data/trading.db` verwendet wird. |
| **`signal_manager.py check_only` crashed (seit ~03.07.2026)** → `NameError: name 'realized_pnl_from_effective_entry' is not defined` in `check_open_positions()` line 637. **Root Cause (gefunden 07.07.2026):** Die Funktion wurde in `utils.py` definiert, aber in `signal_manager.py` nie importiert — der Import fehlte. **Zusätzlich:** OpenRouter API liefert gelegentlich `content: null` → blindes `["content"].strip()` crasht in 6 Files. **Fix:** `realized_pnl_from_effective_entry` zum Import hinzugefügt. NoneType-Fix in 6 weiteren Files (siehe `references/llm-api-content-none-pattern.md`). |
| **`fundamental_data.py` KeyError: `config["fred_indicators"]` (seit ~03.07.2026)** → `load_config()` lädt aus `STRATEGY_CONFIG_PATH` (= `strategy_config.json`), aber `fred_indicators` lebt in `SOURCES_CONFIG_PATH` (= `sources.json`). **Fix:** `SOURCES_CONFIG_PATH` importieren, `sources.json` laden, `sources_cfg.get("fred_indicators", [])` verwenden. |
| **Source Lifecycle: Kanäle wurden suspended statt penalisiert** → Alte Logik (vor 07.07.2026) setzte `status='suspended', enabled=0` bei schlechter Performance. Neue Logik: `weight=0.3, enabled=1` (Scan läuft weiter, Signale haben kaum Gewicht). 10 Kanäle wurden am 07.07. reaktiviert. |
| **DB Lock: Transaction-in-Loop mit API-Calls** → `con.execute("INSERT...")` im Loop, `con.commit()` erst nach allen API-Calls. Die Transaction blockiert andere Writer für Minuten. **Fix:** `commit()` nach jedem Item im Loop. Betrifft `fetch_fred_data`, `fetch_insider_trades`, `fetch_pcr` (fundamental_data.py) und `fetch_rss_feeds`, `fetch_twitter` (social_scanner.py). Siehe `references/db-lock-short-transactions.md`. |
| **YouTube Scan DB Lock: Inter-Cron-Job Kaskade** → `yt_channel_monitor.py` crasht (in `cleanup_db()` oder im INSERT bei Zeile 218) mit `database is locked`. **Zwei Szenarien:** (1) Nur YouTube Scan ❌ → Crash in `cleanup_db()`, 3 Retries reichen nicht. (2) 4 Pipeline-Schritte ❌ (YouTube + Screener + Watchlist + Signal Manager) → Crash im INSERT (Zeile 218), Cascading Lock. **4-Ebenen-Fix:** (a) `busy_timeout=120s` in `init_db()`, (b) Schedule-Puffer 90min, (c) WAL-Checkpoint(TRUNCATE) am Pipeline-Start, (d) `finally: con.rollback()` in allen DB-Scripts. Siehe `references/yt-cleanup-db-lock.md` und `references/trading-post-mortem-juli-2026.md`. |

### Manuelles Nachholen eines YouTube-Kanals (außerhalb der Pipeline)

Wenn ein Kanal neu in die `source_registry` aufgenommen wurde, aber die Pipeline\nerst morgen früh um 03:30 läuft:

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

> **Trailing-Delay seit 15.07.2026:** Trailing wird **erst ab +2x ATR im Plus** aktiviert (`profit_lock_atr` in `strategy_config.json`). Bis dahin läuft der Trade ungestört mit initialem SL. Grund: Post-Mortem-Analyse ergab 75% SL_HIT, 0% TP_HIT — das Trailing triggert bei jedem normalen Pullback bevor der Trade laufen kann. Implementiert in `active_exit_check.py` AKTION 3: `if pnl_atr >= profit_lock_threshold:`.

### Code-Struktur

- **`config.py`** — `SECTOR_TO_ASSET_TYPE`, `ASSET_TYPE_MULTIPLIERS`, `get_asset_type()`, `get_asset_multipliers()`
- **`signal_manager.py`** — Liest asset_type bei Entry (wird in DB gespeichert), nutzt asset_type-spezifische Multiplikatoren für SL/TP und Trailing Stop
- **`active_exit_check.py`** — Nutzt asset_type-spezifische Multiplikatoren für Thesis-BROKEN und Trailing Stop
- **DB:** `positions.asset_type`-Spalte (seit 18.06., per ALTER TABLE migriert)

### 🔴 Strategie-Config-Drift (Critical) + Regime-Adaptive Parameter (15.07.2026)

**Problem (25.06.):** `adapt_strategy()` in `signal_manager.py` passte SL/TP-Multiplikatoren basierend auf Trade-Ergebnissen an — **ohne Marktregime-Prüfung**. Das führte zu einer Config-Drift von 1,5× SL / 2,5× TP → 1,0× SL / 4,0× TP.

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

**Regime-Adaptive Parameter (15.07.2026):** `adapt_strategy()` setzt jetzt **vor** den Trade-Anpassungen eine Regime-Basis. Die Default-Werte aus `strategy_config.json` werden pro Regime überschrieben:

| Regime | SL Multi | TP Multi | Trailing ab | Min. Confidence |
|--------|----------|----------|-------------|-----------------|
| **Bull** | 1.5x | 3.5x | +1.5x ATR | 0.65 |
| **Sideways** | 1.5x | 2.5x | +2.0x ATR | 0.70 |
| **Bear** | 2.0x | 3.0x | +2.5x ATR | 0.75 |

**Auslöser:** Post-Mortem-Analyse der 69 geschlossenen Trades: Mai (Bull) +1.179€ / 70.8% WR vs Juni (Sideways) -1.480€ / 31.3% WR. Die Strategie erkannte das Regime nicht und lief mit Bull-Parametern in den Sideways — fatal für die Performance.

**Regime-Erkennung:** Läuft in `fundamental_data.py` (60% US-Indikatoren + 40% EU-Indikatoren), gespeichert in `regime_history`-Tabelle. `get_current_regime()` in `signal_manager.py` liest den letzten Eintrag.

Siehe `references/adapt-strategy-regime-blindness.md` und `Erklaerung.md` im Skill-Verzeichnis.

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

### 🔴 Drawdown Protection — Graduierte Reduzierung (seit 10.07.2026)

**Problem (alt):** Ein Binary-Stopp bei ≥15% Drawdown (`no_entry`) verhinderte neue Trades komplett. Wenn der laufende Trade im SL endete, konnte der Drawdown nie wieder abgebaut werden — das System war in einer **Heilungsfalle** gefangen.

**Neue Logik:** Statt komplettem Stopp werden Position Size, Confidence-Schwelle und Max-Positionen graduiert reduziert. Das System bleibt handlungsfähig, aber mit geringerem Risiko.

| Drawdown | Size-Faktor | Min. Confidence | Max Positionen | Effekt |
|----------|-------------|-----------------|----------------|--------|
| **< 12%** | 100% | 70% | 8 | Normalbetrieb |
| **12–15%** | 75% | 75% | 6 | Warnzone: reduzierte Size |
| **15–25%** | 50% | 80% | 4 | Bremszone: halbe Size, höhere Qualität |
| **≥ 25%** | close_all + 7d Cooldown | — | 0 | Notbremse (wie gehabt) |

**Heilungsmechanismus:** Bei 50% Size + 80% Confidence reichen 1-2 solide Trades mit +3-4% Gewinn, um den Drawdown von 15% auf unter 12% zu drücken → volle Size wieder frei.

**Code-Struktur:**
- **`check_drawdown()`** in `signal_manager.py` — Gibt `(drawdown_pct, action, params)` zurück mit `size_factor`, `min_confidence`, `max_positions`
- **`open_new_positions()`** — Wendet die drei Parameter an:
  1. `dd_max_positions` ersetzt `cfg["max_positions"]` als Basis für Regime-Caps
  2. `dd_min_confidence` überschreibt `cfg.get("min_confidence", 0.60)` in der DB-Query
  3. `dd_size_factor` wird nach VIX- und Probation-Faktor auf `pct` angewendet
- **Config:** `strategy_config.json` → `drawdown_cooldown_days: 7` (nur für ≥25%-Fall)

**Alter `no_entry`-Stopp wurde entfernt.** Der `_is_drawdown_cooldown_active()`-Check existiert noch als Funktion, wird aber nur noch vom `close_all`-Fall genutzt.

Siehe `references/graduated-drawdown-reduction.md`.

### SP500 SMA200 Cron-Job (Amumbo-Exit)

- Cron `sp500-sma200-check` (1bbecc075d3e), Mo–Fr 10:00, no_agent
- Script: `~/.hermes/scripts/sp500_sma200_check.py`
- Prüft ob S&P 500 (Proxy MSCI USA) über/unter SMA200 → Entscheidung für Amumbo (A0X8ZS)
- Output: `🟢 AMUMBO HALTEN` / `🔴 AMUMBO RAUS`
- Doku: `wiki/concepts/Leveraged ETFs.md` (LETF-Exit-Modus)

## PEAD Signal Integration (seit 11.07.2026)

Post-Earnings-Announcement Drift als zusätzlicher Conviction-Boost im
Watchlist Manager. Funktioniert komplett über yfinance (KEINE Paid-API).

### Komponenten

| Datei | Zweck |
|-------|-------|
| `scripts/pead_signal.py` | `get_pead_boost(ticker)`, `get_pead_boost_cached(ticker, con)`, `ensure_pead_cache_table(con)` |
| `scripts/watchlist_manager.py` | Ruft PEAD-Boost nach Thesis-Boost, vor Grok-Boost auf |

### Funktionsweise

1. `get_pead_boost(ticker)` holt yfinance earnings_dates
2. Berechnet BEAT/MISS aus `Reported EPS - EPS Estimate`
3. Nur innerhalb von 4 Tagen nach Filing (konfigurierbar via `PEAD_SIGNAL_WINDOW_DAYS`)
4. 45-Day-Retrospective-Filter: alte Daten werden verworfen

### Boost-Werte

| Ergebnis | Effekt | Betroffene Conviction |
|----------|--------|----------------------|
| BEAT (EPS > Estimate) | `+0.05` | `conviction_score` (Long) |
| MISS (EPS < Estimate) | `+0.05` | `conviction_score_bear` (Short) |
| Kein Event / zu alt | `0.0` | Kein Effekt |

### Cache

- Tabelle: `pead_cache` in trading.db
- TTL: 6 Stunden (konfigurierbar via `PEAD_CACHE_TTL_HOURS`)
- Schlüssel: ticker
- Ein Ticker kostet nur 1x yfinance-Call pro 6h

### Watchlist-Manager-Integration

```python
# In watchlist_manager.py, nach Thesis-Boost, vor Grok-Boost:
pead_long, pead_short, pead_info = get_pead_boost_cached(ticker, con)
if pead_long > 0:
    conviction = min(1.0, conviction + pead_long)
if pead_short > 0:
    conviction_bear = min(1.0, conviction_bear + pead_short)
```

## Backtesting Engine (`backtesting/`)

Seit 11.07.2026 gibt es eine Backtesting-Engine im Trading-Skill-Verzeichnis.
Extrahiert und adaptiert aus virattt/ai-hedge-fund v2 (MIT License). Ermöglicht
historische Validierung von Signalen bevor sie im Paper-Trading laufen.

**Pfad:** `/root/.hermes/profiles/hermes_trading/skills/trading/backtesting/`

**Komponenten:**

| Modul | Zweck |
|-------|-------|
| `backtesting/__init__.py` | Public API: `BacktestEngine`, `BacktestResult`, `PerformanceMetrics`, `Trade` |
| `backtesting/engine.py` | `BacktestEngine` — Trade-Simulation, Equity-Kurve, Sharpe/MaxDD/WinRate |
| `backtesting/models.py` | Pydantic: `Signal`, `Trade`, `PerformanceMetrics`, `BacktestResult` |
| `backtesting/alpha_model.py` | `AlphaModel` (ABC), `QuantModel` (Base), `DataClient` (Protocol) |
| `backtesting/data_client.py` | `YFinanceDataClient` (yfinance-Adapter) — inkl. Monkey-Patch |
| `backtesting/signals/pead.py` | `PEADModel` — Post-Earnings-Announcement Drift |
| `backtesting/signals/signal_extractor.py` | `SignalExtractorModel` — Wrapper um Pipeline-Signale (YouTube/RSS/Twitter/Screener) |

**Usage (SignalExtractorModel):**

```python
from backtesting import BacktestEngine
from backtesting.data_client import YFinanceDataClient
from backtesting.signals import SignalExtractorModel

client = YFinanceDataClient()
engine = BacktestEngine(capital=100_000, per_trade=10_000)
model = SignalExtractorModel()
result = engine.run_alpha(
    model, ["AAPL", "MSFT", "GOOGL"], client,
    "2026-04-01", "2026-07-01",
    threshold=0.5, holding_days=5,
)
print(f"Sharpe: {result.metrics.sharpe_ratio:.2f}")
```

**Hinweise zum SignalExtractorModel:**
- Liest `conviction_score + first_seen` aus der `watchlist`-Tabelle
- Signale verfallen nach 60 Tagen (Gedächtnisverlust)
- Approximiert Point-in-Time durch `first_seen` als Entry-Datum
- 1.447 Signale von 1.447 Tippern geladen (Stand: 15.07.2026)
- Equal-Dollar-Sizing (10.000€/Trade) — bewusst einfach. Testet das
Signal, nicht die Portfolio-Konstruktion. Detaillierte Doku in der `Erklaerung.md`
unter Section 16.

## Quick Debug

```bash
# Last pipeline run
tail -100 /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log

# Last eval_metrics
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT * FROM eval_metrics ORDER BY date DESC LIMIT 1;"

# Dashboard health
curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/

# Cron-Health-Check (läuft täglich 08:30 als no_agent cron b0b06693e8f9)
# Script: ~/.hermes/scripts/cron_health.py — prüft ob alle Trading-Jobs HEUTE geloggt sind
# Bei false-negative: Regex `(\d+)` scheitert an eintstelligen Tagen → fix: `\s+(\d+)`
python3 /root/.hermes/scripts/cron_health.py

# System crontab
crontab -l | grep trading

# Finnhub test
curl -s "https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token=$(grep FINNHUB_API_KEY /root/.hermes/profiles/hermes_trading/.env | cut -d= -f2)"

# SP500 SMA200-Check (Amumbo-Exit)
python3 /root/.hermes/scripts/sp500_sma200_check.py
```