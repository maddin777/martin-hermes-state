---
name: trading-pipeline
description: "hermes_trading pipeline: cron, watchlist, exits, debug."
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [trading, pipeline, sqlite, cron, exits, watchlist, equity]
    related_skills: [name-normalization-dedup, forex-paper-bot, hermes-profile-ops, last30days]
---

# Trading Pipeline

Equity signal pipeline under profile `hermes_trading`: daily cron chain (macro → social scan
→ LLM signals → watchlist → technicals → signals), exit management, dashboard, evaluation.

## When to Use

- "Was sagt die Pipeline" / watchlist, signals, exits, PnL, drawdown, sector gates
- A pipeline step failed, `cron.log` shows ❌, dashboard shows gelb/rot
- Changing exit rules, scoring, sources, cron jobs or the dashboard
- Reviewing system fitness (win rate, payoff, regime fit) — not reading the docs, using live DB

Not here: FX pairs (own skill `forex-paper-bot`), entity/ticker cleanup as a technique
(`name-normalization-dedup`), profile/gateway infrastructure (`hermes-profile-ops`).

## Scope & Grundprinzipien

1. **Trading = Geldanlage only.** Watchlist, Signale, Exit-Matrix, Backtests. Lebensplanung,
   Auswanderung, Nebengewerbe, Grundstück gehören weder in diesen Skill noch nach `Trading/`
   im Vault; solche Clippings sind kein Trading-Input.
2. **Vorschläge am System-Kontext messen**, bevor du eins machst: Haltedauer 5–14 Tage
   (multi-day, kein Intraday), Takt 1× täglich 03:30 (kein Markt-Daemon), Paper-Trading 1×
   Hebel + 1 €/Trade bei TR, Daten yfinance täglich + RSS/YouTube/Twitter morgens, Modelle
   via OpenRouter (DeepSeek, Gemini), Twitter über twitterapi.io. Klingt der Vorschlag nach
   HFT/Intraday/Hebel-Strategie → nein; verbessert er Trendfilter oder Entry-Qualität bei
   gleicher Haltedauer → ja.
3. **DB-First.** Keine hardgecodeten Mappings in Python. Ticker-Maps, Aliasse, Sektor- und
   Quellen-Konfiguration gehören in SQLite (`company_aliases`, `canonical_tickers`,
   `source_registry`, `theme_*`), nicht in Dicts. Migration: Tabelle in `watchlist_manager.py`
   oder `signal_manager.py` anlegen (`PRAGMA table_info` + `CREATE TABLE IF NOT EXISTS`),
   Seed nur bei `COUNT(*) = 0`.
4. **Immer `config.db_connect()`**, nie raw `sqlite3.connect()` — zentrale WAL +
   `busy_timeout` + `row_factory`. Prüfung: `grep -c "sqlite3.connect" scripts/*.py` → 0.
5. **Modell-IDs stehen hardcodiert** in `MODEL`/`VALIDATION_MODEL`/`DS_MODEL`-Konstanten,
   Inline-`model`-Feldern und `thematic/config/thematic_config.json`. Vor jedem Swap alle
   Stellen erfassen (`grep -rn '<alte-id>' scripts/ thematic/config/`), fixe Version ohne
   `-latest`, Ablauf siehe `hermes-profile-management` / `model-migration-config-blocker.md`.

## Architecture & Cron

```
scripts:  /root/.hermes/profiles/hermes_trading/skills/trading/scripts/
thematik: .../skills/trading/thematic/
DB:       .../skills/trading/data/trading.db
Log:      .../skills/trading/data/cron.log
```

System crontab (nicht Hermes-Cron), Zeiten Mo–Fr; **Safety-Jobs (Exits, SL/TP, Breaking
News) laufen täglich**, Analyse-Jobs nur werktags.

| Zeit | Job | Zweck |
|------|-----|-------|
| 01:30 | `fundamental_data.py` | Makro, Insider, Put/Call, Regime (+ Sektor-Regimes) |
| 02:00 | `social_scanner.py` | RSS + Twitter (twitterapi.io) |
| 03:30 | `trading_pipeline.py` | YouTube → KI-Analyse → Watchlist → Technik → Signale |
| 05:00 | `nightly_eval.py` | Metriken + Telegram-Report |
| 06:30 | `crabel_shadow_eval.py` | Crabel-Shadow (21d) |
| 09:30 / 15:30 | `active_exit_check.py` | täglich, Exit-Checks |
| 10–17 h | `breaking_news_monitor.py` | täglich, stündlich |
| 13–20 h | `signal_manager.py check_only` | täglich, Intraday-SL/TP |
| 22:15 | `export_watchlist.py` | Hermes-Cron no_agent `446aad622784` |
| 22:20 | `watchlist_marker_check.py` | `53e28fdb66d4` (🛒-Gap) |
| 22:30 | `watchlist_cleanup.py` | `7e364ce47b69` (stale >60d, `.L`-DQ) |
| 22:40 | `dq_alarm.py` | `37d505cbc47b` (DQ-Regression ≥76 %) |
| 23:15 | `refresh_tech_scores.py` | Tech-Scores neu berechnen |
| 09:30 | `sector_probation_check.py` | `dda431ae4b55` Probation-Alert |
| Fr 20:00 | `signal_manager.py full` | Wochen-Review |

Thematic (eigene Crontab, nicht von `trading_pipeline.py` orchestriert): 02:30
`prediction_market_scanner.py`, 03:00 `thematic_pipeline.py`, 10:00 `drawdown_monitor.py`,
15:30 `thesis_monitor.py`, So 08:00 `weekly_review.py`, So 04:00 `news_cleanup.py`.
Pitfalls: `thematic-pipeline-pitfalls.md`, Finnhub-Key: `finnhub-api-key-management.md`.

Wochenende: So 05:30 `watchlist_dedup.py`, So 06:00 `nightly_eval.py` (weekly), So 07:00
`weekly_exit_review.py` (`310dfa0df1a6`, Drift-Check), So 07:00 `source_lifecycle.py`,
So 07:30 `watchlist_cleanup.py`, Mo–Fr 08:00 `ki-blase-alert-daily` (`9f4e3cc91675`),
So 08:00 `last30days-trading-weekly`, So 10:00 `ttwo-catalyst-alarm`, So 10:00
`agent-reach-watchdog.sh`. Dazu: `cron_health.py` 08:30 (`b0b06693e8f9`),
`dashboard-watchdog.sh` 15 min (`d1c92b5337c5`), `sp500-sma200-check` 10:00
(`1bbecc075d3e`, Amumbo-Exit, Output 🟢 HALTEN / 🔴 RAUS).

### 🔴 no_agent-Crons: Script + Wrapper-Regeln

- **no_agent-Scripts liegen immer in `~/.hermes/scripts/`**, nie im Profil. Relative
  `script`-Pfade werden unter `~/.hermes/scripts/` aufgelöst; ein Job, der auf
  `scripts/foo.py` im Profil zeigt, findet nichts.
- **Immer ein `.sh`-Wrapper**, der `PYTHONPATH`, `cd` ins Profil und
  `export $(grep -v '^#' .env | xargs)` setzt und dann
  `exec <profil>/venv/bin/python3 scripts/<name>.py` ausführt. Ohne Wrapper startet der
  no_agent-Harness mit dem Hermes-venv-Python → `ModuleNotFoundError: yfinance`; Markt-Scripts
  brauchen den pyenv-Interpreter (`/root/.pyenv/versions/3.12.13/bin/python3`).
- Cron auf den Wrapper zeigen lassen, nicht auf das Profil-Script (Beispiele:
  `dq_alarm.sh`, `weekly_exit_review.sh`, `export_watchlist.sh`, `sp500_sma200_check.sh`).
- Jeder Cron-Job muss `✅ ... DONE` loggen — `=== ... DONE ===` ohne ✅ gilt als
  `⚠️ unknown` im Health-Check.

## Session-Start-Protokoll (Pflicht, nicht optional)

Sobald eine Session startet, **vor** der ersten Frage prüfen:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/        # Dashboard
# Cron-Tab visuell: gelbe/rote Einträge?
grep -E "ERROR|Traceback|database is locked" data/cron.log | tail -10
grep "TRADING PIPELINE DONE" data/cron.log | tail -3
sqlite3 data/trading.db "SELECT date,open_positions,win_rate_30d FROM eval_metrics ORDER BY date DESC LIMIT 1;"
```

Jede Abweichung sofort analysieren und die RCA **in derselben Antwort** liefern (Status →
Log → Ursache → Fix). Bei klarer Ursache direkt fixen, keine "soll ich?"-Rückfrage.
**Vor der RCA den Schedule prüfen:** Analyse-Jobs laufen Mo–Fr; ein Log, das Freitagabend
endet, ist am Samstag kein Ausfall. Die Crontab ist die Zeitquelle, nicht Notizen.

## Exit-Konfiguration — eine Quelle

`get_exit_config(asset_type, regime)` in `config.py` ist die **einzige** Quelle für
SL/TP/Partial/profit_lock/step. `_EXIT_CONFIG_MATRIX` deckt 9 Kombinationen
(STANDARD/TECH/DEFENSIVE × bull/sideways/bear) deterministisch ab.

| Parameter | STANDARD | TECH | DEFENSIVE |
|-----------|----------|------|-----------|
| Stop-Loss | 1.5× ATR | 2.0× ATR | 1.0× ATR |
| Take-Profit | 2.5× ATR | 3.5× ATR | 2.0× ATR |
| Partial Exit | +1.5× ATR | +2.0× ATR | +1.0× ATR |
| Breakeven | +2.0× ATR | +2.5× ATR | +1.5× ATR |
| Trailing ab (profit_lock) | 1.0× ATR | 1.0× ATR | 1.0× ATR |
| Trailing Step | 0.75× ATR | 0.75× ATR | 0.5× ATR |

Asset-Typ aus Sektor: Technology/Communication → TECH; Consumer Defensive/Healthcare/
Utilities → DEFENSIVE; sonst STANDARD.

**Regeln:**
- Alle drei Pfade lesen die Matrix: `signal_manager.py` (Entry-SL/TP, Sizing, Partial-TP,
  `check_open_positions`), `active_exit_check.py` (09:30/15:30), `crabel_shadow_eval.py`
  (Shadow-Sim). Kein `get_asset_multipliers(`-Aufruf mehr — Drift-Check prüft genau das
  (echte Aufrufe mit Klammer, nicht Docstring-Erwähnungen).
- `adapt_strategy()` darf einzelne Keys **nicht** nachträglich übersteuern; sekundäre
  Schreiber entfernen. Entry-SL/TP sind regime-abhängig.
- `profit_lock_atr` bleibt konstant 1.0 (0.5 war Intraday-Noise auf Daily-Daten).
- Nach Partial-TP im Donchian-Primary-Modus SL **nicht** auf Breakeven ziehen — würgt den
  Winner ab, der Donchian-Trail übernimmt.
- Ein Fix in einem Exit-Pfad ist kein Fix: `grep -n "<config_key>" scripts/*.py` und jeden
  Leser konsistent patchen.

Details: `exit-config-consolidation.md`, `adapt-strategy-regime-blindness.md`,
`weekly-trend-filter.md`, `correlation-filter.md`, `short-strategy-setup.md`.

## Drawdown, Sektoren, Regime

**Graduierte Drawdown-Bremse** (`check_drawdown()` in `signal_manager.py`, hardcodiert):

| Drawdown | Size | Min. Confidence | Max Positionen |
|----------|------|-----------------|----------------|
| < 12 % | 100 % | 70 % | 8 |
| 12–15 % | 75 % | 75 % | 6 |
| 15–25 % | 65 % | 75 % | 6 |
| ≥ 25 % | close_all + 7d Cooldown | — | 0 |

Kein `no_entry`-Stopp mehr (Heilungsfalle). Hohe Cashquote ist meist die Drawdown-Zone, nicht
`max_portfolio_allocation` (das ist eine Obergrenze, kein Ziel): erst
`grep -E "Drawdown .*Size|Max. Positionen" data/cron.log` prüfen, dann Positionen zählen.

**Sektor-Regime** (`sector_regimes`, `SECTOR_TO_ETF`, Gold/Silber-Minen über GDX): bull →
volle LONG-Größe, kein Short; sideways → 50 % Size; bear → kein Long, Short erlaubt. Entry,
Sizing und Exit eines Titels nutzen das **Sektor**-Regime, nicht das globale. Das Makro-Overlay
(VIX/HYG/DXY) darf nicht von `regimes.iloc[-1]` überschrieben werden.

**Sektor-Blacklist + Probation** (DB-Tabelle `sector_blacklist`, Single Source of Truth):
NULL + Cooldown > 0 = gesperrt; Cooldown ≤ 0 = genau ein Probation-Trade; `active` = Trade
läuft; `success` = frei; `failed` = neuer Cooldown. Alte JSON-Logik in `signal_manager.py`
(`update_sector_blacklist`, `is_sector_allowed`) ist noch nicht migriert.

**Sektor-Exposure-Cap:** max 70 % Portfolio pro Sektor (`max_sector_exposure_pct`), geprüft
nach dem Sizing. Details: `graduated-drawdown-reduction.md`, `sector-regimes.md`,
`sector-blacklist-probation.md`, `sector-exposure-cap.md`, `sector-probation-check.md`.

## Entry-Qualität & Signale

**Quellen-Lifecycle** (`source_registry`, `source_lifecycle.py` So 07:00):
`candidate` (1.0) → `probation` (0.5, ≥5 Trades WR ≥40 %) → `active` (dynamisch 0.3–2.5) →
`active` mit `weight=0.3` bei schlechter Performance (WR <35 %, neg. PnL, ≥3 Verluste) →
`removed` (WR <20 % oder 60+ Tage keine Mentions). Schlechte Quellen werden **penalisiert,
nicht deaktiviert** (`enabled=1`, Gewicht 0.3). `adjust_weights()` basiert auf
`avg_pnl_per_trade` (≥ +10 € → +15 %, ≤ −10 € → −20 %, <5 Trades unverändert).

**Kalibrierung:** `get_channel_calibration()` skaliert das Channel-Weight nach
`avg_pnl_per_trade` (≥ +50 € 1.5× … < −20 € 0.3×); gilt für alle drei
Conviction-Funktionen. Siehe `signal-calibration.md`.

**PEAD-Boost:** `scripts/pead_signal.py` (`get_pead_boost[_cached]`), +0.05 auf Long- bzw.
Bear-Conviction innerhalb von 4 Tagen nach Filing, 45-Tage-Retro-Filter, `pead_cache` 6 h TTL.
Siehe `pead-signal.md`.

**Ausgabe:** `nightly_eval.py` Tages- (05:00) und Wochen-Report (So 06:00) enthalten den
🎯-Top-Signale-Block aus `calc_top_signals()` — sortiert nach `conviction_score_aged`, nicht
roher Conviction (1-Mention-Zufallstreffer). `calc_top_band_metrics()` validiert Top 3/5/10
separat (nur das Top-Band wird je gehandelt). Siehe `top-band-validation.md`.

**Gates vor dem Entry:**
- **`.L`-DQ:** `get_technical_score()` verlangt ≥200 Bars **und** ≥500k € 20-Tage-Ø-Turnover;
  sonst `None` → kein `tech_score` → nie Entry-Kandidat. `refresh_tech_scores.py` muss alte
  Scores clearen (kein `if tech:`-Guard). Export isoliert `.L`-Microcaps ohne Score in einen
  `## ⚠️ DQ`-Block; `watchlist_cleanup.py` Stufe 1b droppt sie, Stufe 1c droppt `.L` aus
  deaktivierten Quellen. Siehe `uk-microcap-liquidity-gate.md`,
  `dq-source-deactivation-check.md`, `source-deactivation-verification.md`.
- **Last30days-Gate:** `scripts/last30days_gate.py` (Google-News-RSS, keyword-basiert,
  nur HIGH-Conviction ≥0.80, Stufen ok/warning/block, Fail-Open). Braucht `lxml` im
  Trading-venv. Siehe `last30days-gate.md`.
- **Pre-Delivery-Gate:** `scripts/pre_delivery_gate.py` prüft die Shortlist gegen die festen
  Entry-Kriterien und zeigt ✅/⚠️/🚫 pro Kandidat; blockiert die Zustellung **nie**
  (graceful degradation). Siehe `pre-delivery-gate.md`.

## DB & Datenpflege

- **Nie `.get()` auf `sqlite3.Row`** — `AttributeError` bei jedem ALTER TABLE danach:
  `row["col"] if "col" in row.keys() else default`. Siehe `sqlite3-row-get-pitfall.md`.
- **`WHERE id=?` greift nicht, wenn `id` NULL ist** (watchlist-Zeilen aus fehlgeschlagenen
  `ON CONFLICT DO NOTHING`-Inserts) → immer `rowid` verwenden, `SELECT rowid, *`.
- **Duplikate:** `watchlist_dedup.py` existiert ZWEIMAL (`~/.hermes/scripts/` für den
  Wochen-Cron und die Skill-Kopie für die Nacht-Pipeline) — beide patchen. Bekannte Fallen:
  Dedup nur bei `ticker IS NULL`, UPDATE per `id`, hardcodetes `status='watching'`,
  case-/`&`-sensibler Namensvergleich, Conviction summieren statt MAX. Siehe
  `watchlist-table-dedup.md`, `watchlist-dedup-ticker-priority.md`.
- **Ticker-Kanonisierung:** US > .DE > sonstige > Nebenboersen (nie `.SG`/`.MU`/`.F`-Mirror
  für US-Werte, sonst Pseudo-Shorts), `canonical_tickers` + `company_aliases`,
  `scripts/canonicalize_watchlist.py --auto`. Siehe `canonical-ticker-mirrors-attribution.md`,
  `export-watchlist-sector-merge.md`, `other-sector-private-companies.md`.
- **Datumsformat:** in `watchlist_mentions` immer `YYYY-MM-DD`; `upload_date` aus YouTube ist
  `YYYYMMDD` und muss normalisiert werden, sonst sortiert `MAX(mention_date)` als String
  falsch. Siehe `date-normalization-pattern.md`.
- **Quellen-Kennzahlen:** `watchlist.name` ist nicht eindeutig — ein Join
  `watchlist_mentions ⋈ watchlist` über den Namen vervielfacht Zeilen (Quoten > 100 %). Pro
  Mention deduplizieren, Mentions ohne Watchlist-Zeile zuerst über `company_aliases`
  auflösen, Quoten auf 0–100 % prüfen, Schwellen an eine Mindestmenge koppeln (≈15 Mentions/7
  Tage).
- **Stale-Status nach Exit:** `bought` wird erst im nächsten Pipeline-Lauf (03:30) über
  `reactivate_closed_bought()` auf `watching` zurückgesetzt — bis dahin sind `Gekauft N`
  überhöht. Verlässlich für offene Positionen ist nur `positions WHERE status='open'`
  (und dort nie `SELECT *`: JSON-Spalten blähen den Output auf).
- **Dry-Run nur gegen eine DB-Kopie** (`cp data/trading.db <scratch>`); ganze Pipeline-Läufe
  sind nicht kopiersicher (Pfade hart kodiert, LLM-Calls, Alerts). Einzelne Funktion per
  Regex aus dem Quelltext laden und gegen die Kopie laufen lassen.
- **Patch-Sicherheit:** das `patch`-Tool trifft bei fast identischen Blöcken den falschen
  (zweimal passiert: `nightly_eval.py`-Reports, `watchlist_cleanup.py`-UPDATEs). Immer eine
  eindeutige Kontextzeile (`WHERE status='bought'`) mitnehmen, danach den Diff lesen,
  `python3 -c "import ast; ast.parse(open(f).read())"` als Gate. `write_file` ersetzt IMMER
  die ganze Datei — für Block-Edits `patch`; Recovery aus
  `/root/martin-hermes-state/profiles/hermes_trading/...` nach `wc -l`-Vergleich.

## Entity-Normalisierung & Ticker-Resolution (SQLite)

Vier Layer, in dieser Reihenfolge — jede Ebene fixt, was die vorige nicht kann:

0. **DB-Config:** WAL + `busy_timeout` (in diesem Profil über `config.db_connect()`);
   Sonderfälle/Diagnose: `references/sqlite-concurrent-access.md`.
1. **Alias-Map** `lowercase → kanonischer Name`: fängt LLM-Typos (`Palantier`,
   `Reinmetall`, `Enhropic`), Varianten (`meta platforms inc.`), Case (`nvidia`).
2. **Regex-Pipeline**, in dieser Reihenfolge: Bracket-Notes entfernen → Legal-Suffixe
   **iterativ** strippen (`DWS Group GmbH & Co. KGaA` braucht mehrere Pässe) → `The `-Präfix →
   Whitespace → Alias. Konkrete Muster + 130 Alias-Einträge:
   `references/entity-name-normalization.md`.
3. **SQL-Merge:** konfliktfrei heißt **vor** dem UPDATE löschen. Ein Massen-`UPDATE` schlägt
   bei einem einzigen UNIQUE-Verstoß komplett fehl und ändert dann gar keine Zeile — der
   `try/except → DELETE`-Ansatz danach ist zu spät.

**Regeln:**
- Kanonischen Namen einmal wählen (exakter Normalform-Treffer, sonst kürzester) und **nicht**
  danach überschreiben (`canonical = min(originals, key=len)` war genau dieser Bug).
- Zeilen ohne gültige `id` (NULL) nur über `rowid` anfassen, nicht über `id`.
- Mentions-Datum = **Verarbeitungsdatum** (`datetime.now()`), nicht das Publikationsdatum —
  sonst melden Tages-Reports 0 neue Firmen, wenn nur alte Inhalte verarbeitet wurden.
- Nach der Mentions-Normalisierung bleiben Duplikate in der aggregierten `watchlist`; die
  räumt der nächste Aggregations-Lauf bzw. `watchlist_dedup.py` (siehe `watchlist-table-dedup.md`).
- Ticker-Bulk-Auflösung (`NULL`/`'?'`): Hard Map → `yf.Search(...).search()` → Drop als
  Halluzination. Details, Beispiel-Maps und Pitfalls: `references/ticker-resolution.md`.

## Fehlermuster (Kurzindex)

| Symptom | Ursache / Fix | Referenz |
|---------|---------------|----------|
| `database is locked` | Transaction im Loop mit API-Calls (commit pro Item) oder Inter-Cron-Kaskade; 120 s busy_timeout, WAL-Checkpoint, `finally: rollback()` | `sqlite-concurrent-access.md` |
| 4 Pipeline-Schritte ❌ | YouTube-INSERT-Crash hält Lock und kaskadiert — nicht einzeln debuggen | `sqlite-concurrent-access.md`, `trading-post-mortem-juli-2026.md` |
| `ModuleNotFoundError: config` / falsches `utils` | Subprozess erbt kein PYTHONPATH — `env["PYTHONPATH"]=TRADING_ROOT` in `run()` | `subprocess-pythonpath.md` |
| `content: null` → AttributeError | OpenRouter liefert None, `["content"].strip()` crasht | `llm-api-content-none-pattern.md` |
| `cron_health` ⚠️ unknown / gelb | fehlendes ✅ vor DONE, Pipeline-Block-Slicing, Timing-Overlap, Datums-Regex bei 1-stelligen Tagen | `cron-health-diagnostics.md` |
| Pipeline hängt / läuft > 1 h | yfinance-Update zu langsam | `pipeline-timing-diagnostics.md` |
| yfinance `unconverted data remains` | TZ-Suffix im Datum, Monkey-Patch `_strptime` | `yfinance-date-parsing-fix.md` |
| Finnhub 403 | Key abgelaufen/limitiert | `finnhub-api-key-management.md` |
| Dashboard leer/Geisterzeilen | Cron-Ghost-Entries, Sources-case-mismatch, thematic DB-Pfad, zwei Kopien | `dashboard-cron-ghost-entries.md`, `live-vs-state-backup.md` |
| Drawdown/PnL-Zahlen unplausibel | Payoff statt Winrate prüfen; Winrate nie aus TARGET_HIT ableiten; ATR plausibilisieren | `loss-analysis-and-exit-review.md`, `atr-plausibility-check.md`, `high-conviction-diagnostic.md` |
| Fremdmodell-Review | Reviewer-Mathematik gegen Roh-DB verifizieren | `cross-model-review.md` |
| Backtest-Entscheidung | nur gegen `get_exit_config` + Partial-TP validieren | `backtest-methodology.md`, `backtest-variants-selection-vs-exit.md`, `selection-exit-rebuild-2026-08.md`, `alternative-momentum-swing-backtest.md` |

## Dashboard, Backtesting, Twitter

- **Dashboard:** Port 8081, systemd `trading-dashboard.service`, Tabs portfolio … exits.
  Architektur, Tab-Pattern und Exit-Stairway: `dashboard-architecture.md`;
  Betrieb/Kopien: `live-vs-state-backup.md`; sortierbare Tabellen:
  `dashboard-sortable-table-pattern.md`.
- **Backtesting:** Engine unter `skills/trading/backtesting/`; jede Config-Änderung erst
  durch `scripts/backtest_gate.py` (GO/GEDULD/NO-GO, Fail-Open). Details:
  `backtesting-engine.md`.
- **Twitter/X:** nur twitterapi.io, kein Grok-Fallback, nur Account-Scans:
  `twitter-api-integration.md`.
- **Manuelle Eingriffe** (Kanal nachziehen, einzelnen Ticker forcieren, manuell eingefügte
  Ticker, nordische Suffixe): `manual-operations.md`.

## Quick Debug

```bash
tail -100 data/cron.log
tail -30 data/cron.log | grep -E "❌|ERROR|Traceback"
sqlite3 data/trading.db "SELECT * FROM eval_metrics ORDER BY date DESC LIMIT 1;"
curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/
python3 /root/.hermes/scripts/cron_health.py
crontab -l | grep trading
```

System-Review ("ist das System gut"): Pipeline-Log → Exit-Statistik
(`GROUP BY exit_reason`: Alarm wenn SL_HIT ≫ TARGET_HIT, Payoff = Ø TARGET / Ø SL) →
Eval-Metriken → Regime-Historie → Watchlist-Verteilung → Source-Qualität → bei Auffälligkeiten
den Exit-Code selbst lesen. Vor jeder Query `PRAGMA table_info(<tabelle>)` — Spaltennamen
weichen von der Doku ab und sehen sonst wie Bugs aus.

## Dokumentationspflicht (User-Präferenz)

Jede Code-Änderung wird in `/root/.hermes/profiles/hermes_trading/skills/trading/Erklaerung.md`
dokumentiert (Datum, Problem, Fix, Erwartung) — das ist die Live-Doku, kein Wiki-Eintrag. Ist
eine Wiki-Seite (`wiki/concepts/...`) neuer als die Quelle, wird die Quelle nachgezogen, nicht
umgekehrt. Nach jeder Änderung an der Exit-Doku einen Changelog-Eintrag in der Wiki-Seite
ergänzen, sonst meldet der `vault-insights-daily`-Cron (02:45) fälschlich einen Exit-Refresh.
