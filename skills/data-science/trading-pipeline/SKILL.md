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
| 04:00 | `trading_pipeline.py` | Orchestrator: YouTube scan → KI Analyse → Watchlist Update → Technical Analysis (yfinance) → Signal Manager. **Achtung:** Watchlist Update läuft 2-3h (Grok + yfinance API). llm_validator crasht wenn Pipeline noch läuft — siehe Pitfall 12 |
| 04:50 | `llm_validator.py` | ⚠️ **Noch in crontab** obwohl Pitfall 12 Fix nicht angewendet — crasht regelmäßig mit DB-Lock |
| 05:00 | `nightly_eval.py` | ✅ Läuft sauber seit Pipeline-Optimierung (unter 5s) |
| 09:30 | `active_exit_check.py` | Mid-day exit checks |
| 13-20:15 | `signal_manager.py check_only` | Intraday signal check (hourly) |
| 15:30 | `active_exit_check.py` | Afternoon exit checks |
| 20:00 (Fr) | `signal_manager.py full` | Weekly signal review |

**Achtung Nicht-Selbstständige Scripts (keine eigenen Cron-Jobs):**
- `technical_validator.py` → läuft **innerhalb** von `trading_pipeline.py` als Subprozess-Schritt "Technical Analysis". Nutzt **ausschließlich yfinance** (kein Grok, kein LLM).\n- `signal_extractor.py` → läuft innerhalb von `trading_pipeline.py` als "KI Analyse"\n- `watchlist_manager.py` → läuft innerhalb von `trading_pipeline.py` als "Watchlist Update"\n- `watchlist_dedup.py` → Hermes-Cron So 05:30
- `source_lifecycle.py` → system crontab So 07:00

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
    ↓ (Technical Analysis — yfinance ONLY, no Grok/LLM)
trading_signals_validated.json + watchlist updated
    ↓ (Signal Manager — entry signals, position sizing)
positions table → portfolio management
    ↓ (Nightly Eval — metrics → eval_metrics table)
Telegram report + Dashboard
```

**Grok-Klarstellung:** Nur der Conviction-Boost im Watchlist Update nutzt Grok API (max 20 Calls/Lauf, ≥0.80 Schwelle). Technical Analysis, Signal Manager, Fundamental Data, Social Scanner und Nightly Eval arbeiten **ohne Grok** — dein Grok-Tokenlimit betrifft ausschließlich die Watchlist-Anreicherung, nicht die Pipeline als Ganzes.

## Strukturelle Limitierungen

### LONG-Bias der Signalquellen

**Beobachtung (Stand Juni 2026):** 43 LONG-Trades vs. 1 SHORT-Trade seit Systemstart. 0% Win-Rate auf Shorts (1 Loss).

**Warum:**
1. **YouTube-Kanäle und RSS-Feeds sind bullish** — Finanz-Youtuber, Seeking Alpha, Bloomberg etc. liefern fast ausschließlich LONG-Thesen. Short-Thesen sind selten.
2. **Conviction-Boost verstärkt den Bias** — Grok prüft nur Kandidaten mit ≥0.80 Conviction und boostet nur bullish (kein bearish Boost).
3. **Tech-Scores wurden nur für Bull-Kandidaten aktualisiert** — watchlist_manager berechnete yfinance-Scores nur für Top 20 nach bullish conviction. Short-Kandidaten bekamen nie einen tech_score → nie tech_direction='SHORT' → nie als Short-Kandidat erkannt.

**Short-Strategie Implementierung (11.06.2026) — 4 Änderungen:**
1. **Short-RSS-Feeds:** ZeroHedge, MishTalk, HighShortInterest als Quellen hinzugefügt (sources.json)
2. **Tech-Score-Update für Shorts:** watchlist_manager aktualisiert jetzt auch Top 20 nach `conviction_score_bear` (vorher nur bullish). Short-Kandidaten kriegen yfinance-Daten.
3. **Niedrigere Short-Hürde:** `min_confidence_short` 0.65 → 0.5, neuer Key `min_mentions_short: 1` (strategy_config.json)
4. **Separate Mention-Schwelle:** Signal-Manager nutzt `min_mentions_short` statt `min_mentions` für Short-Query

**Live-Effekt (post-Fix):** 2 Short-Kandidaten sofort qualifiziert: Berkshire Hathaway (BRK-B, bear_conviction=0.643) und Walmart (WMT, bear_conviction=0.514). Pipeline checkt bei jedem Lauf.

**Technische-Analyse Direction-Logik** (in `utils.py` `get_technical_score()`):
- Score ≥ +2 → LONG, Score ≤ -2 → SHORT, sonst NEUTRAL
- RSI >75 (überkauft) gibt -2 (Short-Signal), RSI <25 (stark überverkauft) gibt ebenfalls -2
- Scale: -10 bis +10, aus 7 Indikatoren (EMA Stack, RSI, MACD, Preis/EMA50, Volumen, Weekly Trend, ADX)

## Closed-Loop Architecture (seit 11.06.2026)

Drei Feedback-Loops verbinden Trade-Outcomes mit der Aktien-Selektion. Das System lernt aus jedem Trade-Exit statt nur sonntags per Grid-Search.

### Loop 1: Post-Trade Learner (`nightly_eval.py → update_segment_performance()`)
Aggregiert geschlossene Positionen in `segment_performance`-Tabelle nach (Sektor × Conviction-Tier × Richtung × Regime). Läuft täglich 05:00.

### Loop 2: Conviction Calibration (`nightly_eval.py → calibrate_conviction()`)
Prüft ob HIGH ≥ 70%, NORMAL ≥ 55%, LOW ≥ 40% Win-Rate erreichen. Meldet Fehlkalibrierung im Log.

### Loop 3: Pre-Entry Gate (`signal_manager.py → check_segment_performance()`)
Blockiert Entry wenn Segment WR < 30% (≥5 Trades) oder WR < 35% + PnL < -3%.

**Key Commands:**
```bash
# Segment-Performance prüfen
sqlite3 $DB "SELECT sector, conviction_tier, tech_direction, trades_total, win_rate, avg_pnl_pct FROM segment_performance ORDER BY trades_total DESC LIMIT 15;"

# Calibration im nightly_eval-Log
grep "Conviction-Kalibrierung\\|Tier:" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10
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

### 3. Technical Validator / get_technical_score Crash

**Symptom:** `technical_validator.py` oder `watchlist_manager.py` crasht bei yfinance-Daten mit `ValueError: Unknown format code 'd' for object of type 'float'`.

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

### 12. Pipeline-Timing-Konflikt (llm_validator crasht noch, nightly_eval läuft)

**Symptom:** llm_validator (04:50) scheitert mit `sqlite3.OperationalError: database is locked`, OBWOHL try/finally korrekt eingebaut ist. Dashboard zeigt llm_validator gelb/rot. Nightly_eval (05:00) läuft sauber (<5s).

**Log-Muster:**
```
=== 04:19:50 Watchlist Update START ===
  File ".../llm_validator.py", line 121, in main
    con.execute(
sqlite3.OperationalError: database is locked
=== 07:06:31 Watchlist Update DONE ===  ← erst ~3h später
```

**Root Cause:** Pipeline läuft 04:00–~07:10 (Watchlist Update 2-3h). llm_validator feuert um 04:50 während Pipeline noch aktiv in DB schreibt → DB Lock.

**⚠ Status Juni 2026 - Fix NICHT angewendet:**
- `llm_validator.py` ist **weiterhin** in der crontab bei 04:50
- Pipeline läuft durch (✅ Technical Analysis, ✅ Signal Manager), aber llm_validator crasht regelmäßig
- Sollte aus crontab entfernt und als letzter Schritt in `trading_pipeline.py` orchestriert werden

**Fix — Orchestrierung in trading_pipeline.py:**
1. `llm_validator.py` AUS der system crontab entfernen
2. In `trading_pipeline.py` ALS LETZTER SCHRITT nach Signal Manager einfügen

**Diagnose Timing:**
```bash
grep -E "TRADING PIPELINE DONE|trading_pipeline START" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -2
grep -E "database is locked|ERROR|Traceback" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10
```

### 13. Grok X-Boost API-Call-Limit (Token-Sparmaßnahme)

**Konfiguriert in:** `watchlist_manager.py` in der `main()`-Funktion

**Aktuelle Limits (seit 10.06.2026):**
- **Conviction-Schwelle:** ≥ 0.80 (vorher 0.70)
- **Max Calls pro Lauf:** 20 (vorher unbegrenzt)
- **Counter:** `_grok_counter = 0` wird vor `for m in mentions:` initialisiert

**Grund:** 50-100 API-Calls pro Nacht haben X-Token-Limit erreicht. Reduziert auf 20 Calls bei nur den Top-Kandidaten.

**Bei Bedarf anpassen:** `_grok_counter < 20` und `conviction >= 0.80` in der `if`-Bedingung ändern.

### 14. Dashboard Ghost Entries (Gelbe Status für absorbierte Scripts)

**Symptom:** Ein Eintrag im Dashboard Cron-Tab zeigt gelb/strike (`–`) obwohl der Pipeline-Schritt sauber läuft (✅ im TRADING PIPELINE DONE Report).

**Root Cause:** `dashboard.py` `get_cron_jobs()` iteriert die system crontab und filtert nach fest codierten Script-Namen. Wenn ein Script in `trading_pipeline.py` absorbiert wurde (kein eigener Cron-Job mehr) UND der Eintrag noch in `descriptions` steht, zeigt das Dashboard den Status "–" → gelb (#ffd740).

**Angewendeter Fix (11.06.2026) für technical_validator:**
- `technical_validator` aus `descriptions`-Dict entfernt (durch Kommentar ersetzt)
- `technical_validator` aus dem crontab-Filter-String entfernt (Zeile 164)
- Dashboard neugestartet (kill + restart)

**Bei neuen Absorptionen:** IMMER beide Stellen in `dashboard.py` patchen:
1. `descriptions`-Dict (ca. Zeile 133): Eintrag löschen oder kommentieren
2. Crontab-Filter-String (ca. Zeile 164): Script-Namen entfernen
3. Dashboard neustarten: `kill $(pgrep -f dashboard.py) && cd /root/.hermes/profiles/hermes_trading/skills/trading && venv/bin/python scripts/dashboard.py &`

**Diagnose:** Wenn ein Schritt gelb "–" zeigt, aber die Pipeline ✅ im Report → Ghost Entry.

### 15. xsearch_helper Import Collision (Hermes Agent vs Trading utils)

**Symptom:** Signal Manager läuft durch, aber zeigt `x_search Fehler: cannot import name 'base_url_hostname' from 'utils'`. Der Grok-X-Boost (`conviction_boost`, `breaking_news_check`) fällt aus.

**Root Cause:** `xsearch_helper.py` importiert `run_agent.AIAgent` im selben Python-Prozess. Die Trading-Umgebung hat bereits `from utils import get_logger` ausgeführt, also ist `sys.modules['utils']` auf die Trading-`utils.py` gecached — ohne `base_url_hostname`, `safe_json_loads`, etc.

**Symptom-Kaskade:**
1. Erstes fehlendes Symbol: `base_url_hostname`
2. Nach `sys.modules.pop`-Fix: nächstes fehlendes Symbol: `safe_json_loads` — endlos, weil der Import-Cache nie sauber wird

**Fix — Subprozess-Isolation:** AIAgent in einem separaten Python-Subprozess starten.

**Vorteil:** Null sys.path-Manipulation im Hauptprozess. Keine Nebenwirkungen auf nachfolgende Trading-Imports.

### 15. xsearch_helper Import Collision

## Monitoring & Auto-Diagnose

Bei Abweichung vom Dashboard-Status **grün** (gelb oder rot für Pipeline-Schritte) IMMER automatisch Fehleranalyse durchführen:

1. **Status erfassen:** Dashboard Cron & Logs Tab checken (http://localhost:8081/cron) oder direkt cron.log
2. **Log-Muster erkennen:** `database is locked` → Orphaned-Connection (Pitfall 2) oder Timing-Konflikt (Pitfall 12). `Traceback` + `KeyError`/`ImportError` → Config-Fehler (Pitfall 7).
**Achtung Ghost-Einträge:** Wenn ein Schritt im Dashboard-Cron gelb "–" zeigt, obwohl die Pipeline ✅ meldet → Script wurde absorbiert, Dashboard sucht noch in crontab. Fix in Pitfall 14.
4. **eval_metrics auf Aktualität prüfen:** Letzter Eintrag sollte vom heutigen Datum sein. Stale Daten → nightly_eval läuft nicht sauber.
5. **Pipeline-Laufzeit messen:** `grep TRADING PIPELINE DONE` → wenn > 1h, liegt Timing-Konflikt nahe (Watchlist Update zu langsam).
6. **Short-Kandidaten prüfen:** `sqlite3 $DB \"SELECT name, ticker, conviction_score_bear, mention_count FROM watchlist WHERE tech_direction='SHORT' AND status='watching' ORDER BY conviction_score_bear DESC LIMIT 10;\"` → wenn keine trotz änderungen, check ob tech_score berechnet wurde (Pitfall 14: ghost entry)
7. **Lösungsvorschlag mit Aufwandsschätzung** immer direkt mitsenden — keine Rückfrage ob Analyse erwünscht ist.

## Dokumentation pflegen

Bei JEDER Pipeline-Änderung MÜSSEN beide Dokumentationen aktualisiert werden:

| Datei | Zielgruppe | Pfad |
|-------|-----------|------|
| `trading-pipeline` Skill (diese Datei) | Agent (autonome Sessions) | `~/.hermes/skills/data-science/trading-pipeline/SKILL.md` |
| `Erklaerung.md` | User (Obsidian Vault) | `/root/obsidian-vault/Trading/Erklaerung.md` |

**Checkliste nach Änderungen (seit 11.06.2026):**
- [ ] Pipeline-Struktur geändert? → §2 Tagesablauf + §11 Code-Architektur
- [ ] Neue Konfig-Parameter? → §13 Konfiguration
- [ ] Neue Quellen? → §9 Quellen-Management
- [ ] Neue Strategie-Richtung (Short)? → §3 Step 5 + ggf. neue Subsection
- [ ] Neue Metriken/Indikatoren? → §8 Datenbankstruktur
- [ ] Externe Dienste geändert? → §12 Externe Dienste
- [ ] Datum im Header aktualisiert (`*Stand: ...*`)

**Erklaerung.md-Pflege-Muster:**
```
# Nach Code-Änderung → IMMER auch Erklaerung.md patchen
# Sonst entsteht Dokumentations-Schuld die keiner mehr nachholt
```

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