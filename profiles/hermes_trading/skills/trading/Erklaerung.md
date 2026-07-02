# Hermes Trading Skill – Technische & Fachliche Dokumentation

*Stand: 1. Juli 2026 | System-Version nach Paketen A–D + Sprints 1–7 + Bugfix-Sprint + Screener-Source + Watchlist-Performance-Fix + Sektor-Exposure-Cap (70%) + Dashboard-Fixes + **Security-&-Risk-Hardening-Sprint (19 Punkte)***

---

## 1. Überblick

Hermes Trading ist ein vollautomatisches Paper-Trading-System das täglich auf einem Linux-Server (hermes2nd) läuft. Es scannt deutschsprachige und internationale YouTube-Finanzkanäle sowie Twitter/X-Accounts, extrahiert Aktien-Mentions mit KI, bewertet sie nach Sentiment, Stärke und technischer Analyse und verwaltet ein simuliertes Aktienportfolio.

Das System läuft ohne menschliches Eingreifen, benachrichtigt aber per Telegram über alle Signale und Trades.

**Startkapital:** 10.000 € (simuliert)  
**Märkte:** XETRA (DE), NYSE/NASDAQ (US), SIX (CH), Euronext (EU), London (GB), weitere  
**Handelsrichtungen:** LONG und SHORT  

---

## 2. Tagesablauf (Cron, Mo–Fr)

```
02:00  fundamental_data.py       → Makrodaten (FRED: VIX, Yield Curve, CPI), Regime-Erkennung
02:30  thematic/prediction_market_scanner.py  → Polymarket-Signale
03:00  social_scanner.py          → RSS-Feeds + Twitter/X-Accounts
03:00  thematic/thematic_pipeline.py          → Thematische Signale
04:00  trading_pipeline.py        → Hauptpipeline (7 Scripts sequenziell):
         ├─ yt_channel_monitor.py      → YouTube-Transkripte holen
         ├─ signal_extractor.py        → LLM-Analyse (DeepSeek, GPT-4o-mini Fallback)
         ├─ screener_source.py         → Deterministischer Screener (Momentum+Quality, Regime-Overlay)
         ├─ watchlist_manager.py       → Conviction berechnen + Watchlist aggregieren
         ├─ watchlist_dedup.py         → Duplikate bereinigen
         ├─ technical_validator.py     → Ticker-Auflösung + Tech-Score (NACH watchlist_manager!)
         └─ signal_manager.py          → Portfolio-Management + Positionen
04:50  llm_validator.py           → Kreuzvalidierung High-Conviction Signale
05:00  nightly_eval.py            → Performance-Metriken (Sortino, Calmar, R-Multiple)
08:30  cron-health-daily          → Health-Check aller Cron-Jobs (START/DONE-Abgleich).
                                     Bewusst 08:30 statt 08:00, sonst prüft er den sonntäglichen
                                     strategy_optimizer (08:00, ~2 min Laufzeit) bevor dessen
                                     DONE geschrieben ist → False-Positive "crashed".
09:30  active_exit_check.py       → Technischer Exit-Check (morgens)
10:00–17:00  breaking_news_monitor.py  → Stündliche News-Prüfung für offene Positionen
10:00  thematic/drawdown_monitor.py    → Portfolio-Drawdown-Monitoring
13:00–20:00  signal_manager.py check_only  → Stündliche Positionsprüfung
15:30  active_exit_check.py       → Technischer Exit-Check (nachmittags)
15:30  thematic/thesis_monitor.py → Thesis-Status offener Positionen
20:00  signal_manager.py full     → Freitags: vollständiger Lauf
22:00  DB-Backup
22:05  export_watchlist.py        → Markdown-Export nach Obsidian (≥76% Conviction)
```

**Sonntags zusätzlich:**
```
06:00  nightly_eval.py            → Wochenaggregat
07:00  source_lifecycle.py        → Quellen-Performance + Twitter-Discovery via Grok
08:00  strategy_optimizer.py      → Walk-Forward Parameter-Optimierung
```

---

## 3. Pipeline im Detail

### Step 1: YouTube Channel Monitor (`yt_channel_monitor.py`)

Holt Videos der letzten 5 Tage aus `source_registry`. Nutzt `yt-dlp` + `youtube-transcript-api`. Videos werden als `status='pending'` gespeichert. Bereits analysierte Videos (`status='done'`) werden übersprungen – DB ist primärer Cache.

Transiente API-Fehler werden als `status='error'` mit `error_count` gespeichert. Nach 3 Fehlern wird das Video dauerhaft übersprungen.

### Step 2: Signal Extractor (`signal_extractor.py`)

Analysiert `pending`-Videos mit **DeepSeek v4 Flash** (Fallback: GPT-4o-mini). Für jedes erkannte Unternehmen:

```json
{
  "name": "NVIDIA Corporation",
  "sentiment": "bullish",
  "strength": "strong",
  "reason": "Starke Datacenter-Nachfrage",
  "action_hint": "buy"
}
```

**LLM-Prompt-Regeln:** Vollständige Firmennamen, Mindestlänge 4 Zeichen, keine Ticker-Symbole im name-Feld. API-Calls haben Retry mit exponentiellem Backoff.

**JSON-Rolling:** Die Signaldatei hält nur Einträge der letzten 30 Tage (verhindert unbegrenztes Wachstum).

### Step 2b: Screener Source (`screener_source.py`)

Zusätzliche, deterministische Kandidaten-Quelle **parallel zu YouTube/Twitter** — komplett kostenlos (nur yfinance). Läuft VOR dem Watchlist Manager und schreibt seine Treffer als Mentions einer eigenen Quelle (`channel='screener'`) in `watchlist_mentions`. Dadurch durchlaufen die Kandidaten dieselbe Conviction-Berechnung, das Tech-Scoring und den Signal Manager wie jede andere Quelle; die Quelle bekommt im `source_registry` ein eigenes Gewicht + Lifecycle-Tracking.

**Ansatz** = Momentum + Trendstruktur + Katalysator, gehärtet für „best für dieses Setup":

- **Technik-Gate (DRY):** nutzt `utils.get_technical_score()` (EMA-Stack, RSI, MACD, ADX, Volumen, Weekly Trend) — keine doppelte Indikator-Logik. Long verlangt `direction=LONG` + Confidence ≥ Schwelle, Short spiegelbildlich.
- **52W-Distanz + relative Stärke:** Long nur ≤15 % unter 52W-Hoch und Outperformance vs. SPY (63d); Short spiegelbildlich nahe 52W-Tief.
- **Quality-Gate (gegen Momentum-auf-Junk):** `quality_check()` aus yfinance-Fundamentals (ROE, Marge, Debt/Equity, Umsatzwachstum). `junk` (unprofitabel UND schrumpfend bzw. hoch verschuldet + Verlust) wird bei Longs verworfen; fehlende Daten (`unknown`, dünn gecoverte DE-Titel) ohne Penalty.
- **Short-Seite QmJ-konform:** Spiegelbild der Long-Seite. Junk bestätigt den Short (+Bonus), hochwertige Namen bekommen einen Malus und werden ab `SHORT_MAX_QUALITY_BONUS` (Standard 1.0) ganz vom Shorten ausgeschlossen — genau die Titel, die die Long-Seite kauft. Zusätzlich werden Shorts nicht direkt am 52W-Tief eröffnet (`SHORT_MIN_PCT_ABOVE_LOW`, Standard 5 %; Squeeze-/Boden-Fishing-Schutz).
- **Börsen-Filter:** nur handelbare Aktien (US + XETRA + West-EU via `ALLOWED_SUFFIXES`); Index-/Fonds-/Asia-Ticker aus der `companies`-Tabelle werden verworfen.
- **Regime/Vol-Overlay (reuse):** liest das bestehende Regime aus `regime_history` (Fallback `macro_signal.json`). `bear`/High-VIX (>25) → weniger & strengere Longs, mehr Shorts; VIX >30 → Longs stark gedrosselt. Adressiert den Momentum-Crash als Hauptschwäche des Faktors.

Treffer werden nach Composite-Score sortiert und auf `max_long`/`max_short` (regime-abhängig) gekappt; `strength` (strong/moderate/weak) steuert die Stärke-Gewichtung im Watchlist Manager. Ticker werden idempotent in `companies`/`company_aliases` registriert (gleiche Konvention wie `company_validator`), damit der Watchlist Manager sie wieder auflöst. Test: `python3 screener_source.py --dry-run`.

### Step 3: Watchlist Manager (`watchlist_manager.py`)

Aggregiert Mentions der letzten **14 Tage** mit Stärke-Gewichtung:

```
effective_bullish = Σ(strength_weight × mention)
  strong=1.0 | moderate=0.6 | weak=0.3

sentiment_score  = effective_bullish / (mention_count × 0.6)
mention_weight   = log(mention_count + 1) / log(11)
channel_bonus    = min(unique_channels / 3, 1.0) × 0.2

conviction = (sentiment_score × 0.6 + mention_weight × 0.4) × (1 + channel_bonus)
```

Zusätzlich:
- **Thesis-Boost:** +8% bei aktiver, intakter Thesis + bullishem Momentum; +5% bei intact; +2% bei kein Check; 0% bei broken
- **conviction_aged:** Bayesian-Ansatz mit Halbwertszeit (konfigurierbar via `CONVICTION_HALF_LIFE_DAYS` in config.py, Standard 14d)

#### Performance: Negativ-Cache + geteilte Connection (Laufzeit 122 min → ~8 min)

Die nächtliche Validierung von ~1800 unique Namen lief über `validate_and_register()` → `company_validator`. Zwei kombinierte Probleme hatten die Laufzeit auf ~2 h getrieben:

1. **Lang gehaltene äußere Transaktion (Root Cause):** `db_connect()` nutzt deferred Transactions; der Watchlist-Loop hält ab dem ersten `INSERT INTO watchlist` eine offene Schreibtransaktion bis zum `commit()` nach der Schleife. In WAL blockiert das jede *separate* Schreib-Connection. `validate_and_register` öffnete (wie der Negativ-Cache) eine eigene Connection → lief 30 s in den `busy_timeout` und scheiterte still im `except`. Diese 30-s-Stalls waren der Großteil der Laufzeit (CPU-Zeit blieb konstant bei ~3 min — es wurde fast nur gewartet). **Fix:** Die äußere Connection wird durch die ganze Validierungskette durchgereicht (`validate_and_register(name, con=con)` → `validate(con=con)` → `_cache_reject/_check_reject_cache(con=con)`); alle Writes laufen auf *einer* Connection, kein Lock-Konflikt. Bei `con=None` bleibt die alte Standalone-Semantik.

2. **Kein Negativ-Cache:** Abgelehnte Namen (Tippfehler, nicht-börsennotierte Entitäten) wurden nur in eine Logdatei geschrieben, nie gemerkt — also jede Nacht erneut durch den yfinance-Gauntlet (`yf.Search` + bis zu 5× `.info`) geschickt. **Fix:** Tabelle `validation_rejects` (Migration `migrate_add_reject_cache.py`) cached deterministische Rejects (`unknown/not_equity/name_mismatch/low_liquidity`) mit TTL `REJECT_CACHE_TTL_DAYS=21`. Transiente Fehler (`yf_error`) werden **nicht** gecacht (sonst blockiert ein einmaliger Netzwerkfehler einen validen Namen 21 Tage). Bei erfolgreichem Accept wird ein alter Reject-Eintrag entfernt.

Steady-State: bekannte Firmen werden über `companies` aufgelöst, bekannter Müll über den Reject-Cache — nur *neue* Namen pro Nacht zahlen noch den Yahoo-Preis. Diagnose-Probe: `python3 test_lock_fix.py 15`.

### Step 4: Watchlist Dedup (`watchlist_dedup.py`)

Drei Phasen in fachlich korrekter Reihenfolge:
1. **Ticker-basiert** — gleicher Ticker → merge (zuerst)
2. **Name-basiert mit verschiedenen Tickern** — Ticker-Priorität: US > EU > London > Strukturierte Produkte
3. **Name-basiert ohne Ticker** — Normalisierung über `company_normalizer.py`

### Step 5: Technical Validator (`technical_validator.py`)

Läuft **nach** `watchlist_manager`, damit `tech_score` und `tech_direction` für die nachfolgende Entry-Entscheidung im signal_manager frisch und vollständig sind.

Löst Firmennamen über `company_validator.py` in Ticker auf. 5-stufige Pipeline: Cache → yf.Search → Equity-Check → Namens-Ähnlichkeit → Liquidität. Berechnet dann Confluence Score über 7 Indikatoren.

| Indikator | Gewicht | Logik |
|-----------|---------|-------|
| EMA Stack (20>50>200) | ±1 | Trend-Richtung |
| RSI (14) | ±2 | 50–60 ideal (+2), 40–70 (+1), >75 überkauft (−2), <25 überverkauft (−2) |
| MACD Histogram | ±2 | Vorzeichen + Richtung |
| Preis vs. EMA50 | ±1 | Abstand in % |
| Volumen-Trend | +1.5 | 5d vs. 20d Average |
| Weekly Trend | ±1 | Preis > EMA20 wöchentlich (lokal resampled aus Tagesdaten zur API-Schonung) |
| ADX (14) | ±1 | Trendstärke |

Normalisierung: `confidence = (score + 10) / 20`

### Step 6: Signal Manager (`signal_manager.py`)

**Entry-Hierarchie:**
```
0. Drawdown-Cooldown: 7 Tage nach close_all-Event gesperrt
1. Drawdown-Notbremse: –15% ATH → kein Entry | –25% ATH → alles schließen + Telegram
2. Makro-Filter: bearish + bear-Regime → keine LONGs
3. VIX > 30 → Position Size halbieren (aus macro_data DB, konfigurierbar)
4. Cash-Reserve: min(1.500€, 15% Portfolio) – wird auch intra-Loop pro Iteration geprüft
5. Budget-Limit: max 70% investiert
6. Max 8 offene Positionen
7. **Sektor-Exposure-Cap:** max 70% des Portfolios pro Sektor (via `strategy_config.json: max_sector_exposure_pct`, geprüft NACH Sizing mit tatsächlicher Positionsgröße)
8. Short-Thesis Score: mind. 2 von 4 Kriterien (Sentiment + P/E + Analyst + Tech)
9. Re-Entry-Sperre: exakt 24h (datetime-basiert, nicht mehr tagesbasiert)
10. Krypto-Filter: -USD/-USDT-Ticker geblockt
11. Liquiditätsfilter: Tagesvolumen ≥ 500.000€ (FX-konvertiert)
12. Earnings-Blackout: 5 Tage vor Earnings (korrekte date/datetime Normalisierung)
```

**Position Sizing (Vola-bereinigt / Risk-Parity):**
Das Sizing erfolgt über ein **volatilitätsbereinigtes Risk-Parity-Modell**:
- **Zielrisiko pro Trade:** Konfigurierbar über `risk_pct_per_trade` in strategy_config.json (Standard 1,5 %)
- **VIX-Halving:** Bei VIX > 30 wird `pct`-Cap halbiert (aus `macro_data`-Tabelle)
- **FX-korrekt:** ATR und Preis werden via `utils.price_to_eur()` in EUR umgerechnet bevor Stückzahl berechnet wird
- **Formel:** `vol_size = (portfolio_value × risk_pct) / (ATR_EUR × sl_mult)`; gedeckelt durch pct-Limit, Cash, Budget
- **Stückzahl:** `shares = position_eur / price_eur` (FX-aware via `position_size_in_shares()`)

**Exit-Management:**
- SL: 1.5×ATR | TP: 2.5×ATR
- Partial Exit bei +1.5×ATR (50%) — kein Doppelbuchungs-Bug mehr durch `original_position_size`-Snapshot
- Trailing Stop alle 0.5×ATR
- Breakeven bei +2.0×ATR

---

## 4. FX-Umrechnung (utils.py)

**Wichtig:** yfinance liefert Preise in der Heimwährung des Tickers:
- US-Ticker (kein Suffix) → **USD**
- `.DE`, `.PA`, `.AS`, `.F`, `.MU` etc. → **EUR** (kein Umrechnungsbedarf)
- `.L`, `.IL` (London) → **GBp (Pence!)** — Preise müssen durch 100 geteilt werden, dann GBP→EUR

Hilfsfunktionen in `utils.py`:

| Funktion | Zweck |
|----------|-------|
| `ticker_to_currency(ticker)` | Leitet Währung aus Börsensuffix ab |
| `price_to_eur(price, ticker)` | Preis → EUR (inkl. GBp-Handling) |
| `position_size_in_shares(eur, price, ticker)` | EUR-Betrag → Stückzahl FX-korrekt |
| `turnover_to_eur(price, volume, ticker)` | Tagesumsatz → EUR (für Liquiditätsfilter) |
| `get_fx_rate_to_eur(currency)` | ECB-Kurs via Frankfurter API (tages-cached) |

---

## 5. Twitter/X Integration

### Aktive Quellen-Nutzung (social_scanner.py)

Holt Tweets von registrierten Accounts in `source_registry` über twitterapi.io. Jeder Account wird täglich geprüft (Mo–Fr). Tweets durchlaufen die gleiche LLM-Analyse wie YouTube-Transkripte.

### Grok-Integration (xsearch_helper.py)

Über das Hermes AIAgent mit GrokLite-OAuth stehen vier Funktionen zur Verfügung:

| Funktion | Zweck | Aufruf |
|----------|-------|--------|
| `conviction_boost()` | +10% bei bullishem X-Signal für high-conviction Aktien | watchlist_manager |
| `contradiction_check()` | Gegencheck bei widersprüchlichen YouTube-Signalen | watchlist_manager |
| `breaking_news_check()` | Breaking News vor Kauf prüfen | signal_manager |
| `watchlist_expansion()` | Top-10 meistdiskutierte Aktien auf X | nightly_eval |
| `discover_finance_accounts()` | Aktive Finanz-Accounts via Grok-Suche finden | source_lifecycle |

**Grok-Integration im Trading-Flow:**
- `watchlist_manager.py`: Für Ticker mit conviction ≥ 70% wird Grok nach aktuellem X-Sentiment gefragt. Bullishes X-Signal → +10% Boost. Bearishes X-Signal → −15% Penalty.
- `signal_manager.py`: Vor jedem HIGH-Conviction-Entry (≥ 80%) prüft Grok ob in den letzten 6h negative Breaking News auf X kursieren. Bei Treffer: Entry abgebrochen.

### Automatische Twitter-Quellen-Verwaltung (source_lifecycle.py)

**Discovery (sonntags):**
1. `discover_new_sources()`: LLM (DeepSeek via OpenRouter) schlägt YouTube-Kanäle und RSS-Feeds vor basierend auf Coverage-Lücken. Slot-Zähler wird pro hinzugefügter Quelle korrekt dekrementiert.
2. `discover_twitter_via_grok()`: Grok-basierte Twitter-Discovery (exklusiver Kanal – LLM-Discovery für Twitter deaktiviert, da halluzinationsanfällig).

---

## 6. Makro-Regime (fundamental_data.py)

`signal_manager.py` liest das kombinierte Regime und wendet Conviction-Anpassungen an.

**VIX > 30:** Position-Size wird auf die Hälfte reduziert. VIX-Wert wird aus der `macro_data`-Tabelle gelesen (kein Hardcode mehr – konfigurierbar über `strategy_config.json`).

---

## 7. Thesis-System (thematic/)

Jede Position kann mit einer Investment-These (`thesis_text`) und einem Theme (`thesis_theme_id`) verknüpft werden. `thesis_monitor.py` prüft täglich ob die These noch intakt ist:

**Status-Logik:**
- `no_thesis`: kein `thesis_theme_id` und kein `thesis_text` → kein LLM-Call, kein Alert
- `intact`: These bestätigt
- `weakening`: leichte Verschlechterung (3× in Folge → Telegram: 50%-Reduktions-Empfehlung)
- `broken`: klare Gegenbeweise (confidence ≥ 70%) → SL auf 0.5×ATR enger ziehen + Alert

**Conviction-Boost durch Thesis:**
Wenn ein Ticker in `theme_beneficiaries` eingetragen und das Theme aktiv ist:
- +8% bei intact + bullishem Momentum
- +5% bei intact
- +2% bei noch kein Check
- 0% bei broken/degraded

---

## 8. Breaking News Monitor (breaking_news_monitor.py)

Läuft stündlich 10–17 Uhr. Für jede offene Position:
1. Tavily: aktuelle News der letzten 24h holen
2. LLM: Sentiment-Score 0.0 (positiv) – 1.0 (negativ)
3. Bei Score ≥ 0.65: SL auf 0.5×ATR enger ziehen + Telegram-Alert
4. Bei Pre/After-Hours-Bewegung > 5%: sofortiger Alert

---

## 9. Datenbankstruktur (Auswahl)

| Tabelle | Zweck |
|---------|-------|
| `videos` | YouTube-Videos mit Status (pending/done/error), error_count |
| `watchlist_mentions` | Mentions (name, sentiment, strength, channel, date) |
| `watchlist` | Aggregiert (conviction, tech_score, direction) |
| `positions` | Trades (offen + geschlossen, thesis_status) |
| `portfolio` | Cash, Total Value, ATH-Wert |
| `companies` | Knowledge Base: 863 Firmen (Ticker, Sektor, ISIN) |
| `company_aliases` | Alias-Mapping: "nvidia corp." → NVDA |
| `source_registry` | YouTube + RSS + Twitter-Quellen mit Performance |
| `macro_data` | FRED-Daten: VIX, Yield Curve, Fed Rate, CPI |
| `regime_history` | Tägliches Regime (inkl. US/EU separat, VIX, Overlay) |
| `thesis_status_log` | LLM-Thesis-Checks pro Position |
| `theme_definitions` | Investmentthesen |
| `theme_beneficiaries` | Welche Ticker profitieren von welcher These |
| `canonical_tickers` | Ticker-Mappings (z.B. YDX.MU → NBIS) |

---

## 10. Quellen-Management

```
Quellen-Typen: YouTube | RSS | Twitter/X
Lifecycle: candidate → probation → active → suspended → removed
```

**Discovery:**
- LLM-basiert (OpenRouter): schlägt neue Quellen vor basierend auf Coverage-Lücken (YouTube + RSS)
- Grok-basiert (Twitter only): findet echte aktive Accounts aus aktuellen Tweets

**Performance-Tracking (wöchentlich):**
- Win-Rate (90d), avg PnL pro Trade, consecutive Losses
- Gewicht-Anpassung: 0.3× bis 2.5× (fließt in Conviction Score ein)
- Inaktivitäts-Check: Twitter 14d/30d, YouTube/RSS 90d

---

## 11. Code-Architektur

```
scripts/
├── config.py              ← Alle Pfade + Konstanten (single source of truth)
│                             Telegram: TELEGRAM_HOME_CHANNEL mit TELEGRAM_CHAT_ID-Fallback
├── utils.py               ← get_technical_score(), prefetch_prices(), get_price_data_cached(),
│                             retry(), get_logger()
│                             FX: ticker_to_currency(), price_to_eur(), position_size_in_shares(),
│                             turnover_to_eur(), get_fx_rate_to_eur() [Frankfurter ECB API]
├── company_normalizer.py  ← 203 Aliases, Legal-Suffix-Strip
├── company_validator.py   ← 5-stufige Validierungspipeline + ISIN-Mapping + Negativ-Cache (validation_rejects)
├── xsearch_helper.py      ← Grok/X-Integration: conviction_boost, discover_finance_accounts
├── fx_rates.py            ← Legacy-Modul (ersetzt durch utils.py FX-Funktionen)
│
├── yt_channel_monitor.py  ← Step 1: YouTube
├── signal_extractor.py    ← Step 2: LLM (DeepSeek + Retry, Rolling JSON 30d)
├── screener_source.py     ← Step 2b: Deterministischer Screener (Momentum+Quality+Regime),
│                             schreibt Mentions als channel='screener'
├── watchlist_manager.py   ← Step 3: Conviction, Thesis-Boost, Stärke-Gewichtung
├── watchlist_dedup.py     ← Step 4: Dedup (Reihenfolge: Ticker → Name+Ticker → Name)
├── technical_validator.py ← Step 5: Tech-Score (NACH watchlist_manager)
├── signal_manager.py      ← Step 6: Portfolio, Entry/Exit, Drawdown, Sektor-Cap
│                             VIX-Halving aus macro_data; risk_pct_per_trade konfigurierbar;
│                             Drawdown-Cooldown 7 Tage; FX-korrektes Sizing; 24h re-entry fix
├── trading_pipeline.py    ← Orchestrierung (Logger korrekt, kein def log() Shadow)
│
├── active_exit_check.py   ← 2× täglich: Tech-Exit + Thesis-broken SL-Tightening
│                             BUGFIX: Cash & Portfolio-Value bei jedem Exit aktualisiert
├── breaking_news_monitor.py ← Stündlich: Tavily-News + Pre/AH-Alert
├── fundamental_data.py    ← FRED + erweitertes Regime-Modell (VIX/HYG/DXY)
├── social_scanner.py      ← RSS + Twitter/X-Accounts
├── source_lifecycle.py    ← Quellen-Lifecycle + Grok-Twitter-Discovery
├── llm_validator.py       ← Kreuzvalidierung High-Conviction (Update per ticker+name)
├── nightly_eval.py        ← Tägliche Metriken
├── strategy_optimizer.py  ← Walk-Forward Optimierung
├── export_watchlist.py    ← Obsidian-Export (≥76% Conviction)
└── export_companies_yaml.py ← YAML-Export für git

thematic/
├── thesis_monitor.py      ← Thesis-Status-Prüfung (täglich 15:30)
├── thematic_pipeline.py   ← Thematische Signale
├── drawdown_monitor.py    ← Portfolio-Drawdown
├── briefing.py            ← Tägliches Markdown-Briefing
└── weekly_review.py       ← Wochenrückblick
```

**Wichtige Design-Entscheidungen:**
- `companies`-Tabelle = Single Source of Truth für Ticker + Sektor
- `UNIQUE(ticker)` in watchlist verhindert strukturelle Duplikate
- Preis-TTL-Cache (5 min) + Batch-Download verhindert 20+ Einzelabfragen
- SQLite WAL-Modus (Write-Ahead-Logging) und 30.000 ms Busy-Timeout standardmäßig aktiviert
- DB `videos.status='done'` als primärer LLM-Cache (robust gegen JSON-Verlust)
- `@retry()` auf alle externen API-Calls (FRED, twitterapi.io, yfinance)
- `get_logger()` in allen Haupt-Modulen, RotatingFileHandler
- **Alle `except:` → `except Exception:`** (verhindert Verschlucken von SystemExit/KeyboardInterrupt)
- **FX-Umrechnung:** Alle Preisberechnungen (Sizing, Liquidity, P&L) nutzen `utils.price_to_eur()` inkl. GBp-Handling für Londoner Titel

---

## 12. Bekannte Einschränkungen / Design-Entscheidungen

- **conviction_score_raw:** `watchlist_manager` schreibt bei jedem Lauf den rohen kanalbasierten Conviction-Wert in `conviction_score_raw`. `llm_validator` verändert nur `conviction_score` + `llm_verdict` + `llm_verdict_at`. Das ermöglicht im Dashboard und Optimizer eine saubere Trennung zwischen Quellen-Signal und LLM-Aufwertung.
- **trading_pipeline.py nutzt sys.path.insert():** Wie alle anderen Module. Migration zu einem installierbaren Paket via `pip install -e .` oder PYTHONPATH-Wrapper ist als mittelfristige Architekturmaßnahme vorgesehen.
- **Paper-Trading:** Alle Positionen sind simuliert. SHORT-Positionen werden als Knockout-Zertifikat 1×Hebel behandelt.
- **Telegram-Startup-Check:** `signal_manager` ruft beim Start `getMe` auf dem Telegram-Bot auf und loggt eine Warnung wenn der Token ungültig ist oder die API nicht erreichbar ist. Alle Module nutzen den zentralen Fallback `TELEGRAM_HOME_CHANNEL or TELEGRAM_CHAT_ID`.

---

## 13. LLM-Konfiguration

| Rolle | Modell | Anbieter |
|-------|--------|----------|
| signal_extractor | deepseek/deepseek-v4-flash | OpenRouter |
| signal_extractor Fallback | openai/gpt-4o-mini | OpenRouter |
| llm_validator | deepseek/deepseek-v4-flash | OpenRouter |
| theme_discovery | deepseek/deepseek-v4-flash | OpenRouter |
| beneficiary_b | deepseek/deepseek-v4-flash | OpenRouter |
| pm_classifier | deepseek/deepseek-v4-flash | OpenRouter |
| thesis_monitor | google/gemini-2.5-flash-lite | OpenRouter |
| beneficiary_a (Grok) | grok-lite | xAI OAuth direkt |
| beneficiary_c | qwen/qwen3.5-flash-02-23 | OpenRouter |

---

## 14. Datenbankmigrationen (auto)

Alle Migrationen laufen beim ersten Start des jeweiligen Scripts automatisch via `PRAGMA table_info` + `ALTER TABLE`. Kein manuelles DB-Setup nötig:

| Script | Tabelle | Neue Spalten |
|--------|---------|-------------|
| `signal_manager.py` | `positions` | `highest_price`, `lowest_price`, `partial_exit_done`, `thesis_current_status`, `thesis_theme_id` |
| `signal_manager.py` | `portfolio` | `ath_value` (mit Backfill aus `total_value`) |
| `signal_manager.py` | `watchlist` | `conviction_score_raw`, `llm_verdict`, `llm_verdict_at` |
| `yt_channel_monitor.py` | `videos` | `error_count` (für Retry-Limit) |
| `watchlist_manager.py` | `watchlist` | `weekly_trend` |
| `signal_manager.py` | `canonical_tickers` | neue Tabelle (Ticker-Mappings) |

---

## 15. Changelog

### 29.06.2026 — Dashboard-Fixes Batch

1. **Urban Jäkle kein letzter Eintrag** — Case-Mismatch zwischen `watchlist_mentions` (speichert `"urban jäkle"`) und CHANNELS_FALLBACK (`"Urban Jäkle"`). Dashboard matcht jetzt case-insensitive via `stats_ci`-Dict.
2. **Thematic Dashboard DB-Fehler** — `dashboard_thematic.py` hatte einen `os.path.dirname()` zu viel → DB-Pfad zeigte auf nicht-existentes `skills/data/trading.db`. Fix: ein `os.path.dirname()` entfernt.
3. **Finnhub 403 Rate-Limits** — `finnhub_client.py`: Sliding-Window Rate Limiter (max 50 Calls/60s, ~17% Puffer zum Free-Tier-Limit) statt festem Interval. Blockiert automatisch wenn Limit erreicht + wartet bis Fenster frei. Plus Retry (2 Versuche, 3s/6s Backoff) bei 403/429. Log-Level von "Fehler" auf "⚠️" reduziert.

### Frühere Änderungen

(Siehe Git-Historie und vorherige Versionen dieses Dokuments.)

---

## Security-&-Risk-Hardening-Sprint (1. Juli 2026)

Vollständige Schwachstellen-Analyse (fachlich + technisch) mit 19 umgesetzten Fixes.
Betroffene Dateien: `dashboard.py`, `signal_manager.py`, `utils.py`,
`active_exit_check.py`, `strategy_optimizer.py`, `nightly_eval.py`,
`drawdown_monitor.py`, `xsearch_helper.py`.

### 🔴 Sicherheit

**#1 – Unauth. RCE über das Dashboard (dashboard.py).**
`POST /sources/yt/add` schrieb `name`/`url` unsaniert per String-Interpolation in
den Python-Quelltext von `yt_channel_monitor.py`, den Cron um 04:00 als root
ausführt → beliebige Code-Ausführung, zusätzlich CSRF-fähig (simple Form-POSTs).
**Fix:** YouTube-Kanäle leben jetzt in `source_registry` (DB), exakt wie RSS/Twitter
(`get_yt_channels/add_yt_channel/remove_yt_channel` schreiben DB statt Quellcode).
Strenge Eingabe-Validierung (`_YT_NAME_RE`, `_YT_URL_RE`). Dashboard bindet
standardmäßig auf `127.0.0.1` (LAN nur bewusst über `DASHBOARD_BIND=0.0.0.0`).
Alle POST-Mutationen erfordern einen Token, sobald `DASHBOARD_TOKEN` gesetzt ist
(Header `X-Dashboard-Token` oder Formfeld `_token`).

**#2 – Stored XSS (dashboard.py).** Firmennamen/Reasons aus der LLM-Extraktion
externer Inhalte (YouTube-Transkripte!) wurden ungeescapt gerendert.
**Fix:** `html.escape()` auf alle DB/LLM-Felder in den serverseitigen Tabellen;
`</script>`-Breakout im eingebetteten Watchlist-JSON geschlossen
(`<`,`>`,`&` → `\u00xx`); JS-`esc()`-Helfer für das clientseitige `innerHTML`-Rendering.

### 🔴 Risiko-Kern

**#3 – Drawdown-Bremse war blind für offene Verluste (signal_manager.py,
drawdown_monitor.py, utils.py).** `portfolio.total_value` ist Buchwert
(`cash + Σ position_size` = Einstand); unrealisierte Verluste waren unsichtbar,
die −15%/−25%-Notbremse feuerte erst NACH den Einzel-SL-Hits.
**Fix:** Neue Helfer `utils.position_current_value_eur()` +
`utils.open_positions_market_value_eur()`. `check_drawdown()` und
`drawdown_monitor` rechnen jetzt Mark-to-Market (`cash + Σ MtM`), inkl.
Fortschreibung von `total_value`/`ath_value`.

**#4 – Strategy Optimizer speicherte cfg fast nie (strategy_optimizer.py).**
Der v2-`main()` schrieb `strategy_config.json` nur im `<10-Trades`-Zweig. Walk-Forward-
und Eval-Metrics-Anpassungen blieben nur im Speicher → sonntäglicher Lauf de-facto
No-Op auf Platte. **Fix:** cfg-Dump (a) VOR der Parameter-Optimierung
(damit `_original_main` die eval-/source-Anpassungen sieht), (b) direkt nach
WF-Übernahme, (c) finaler Safety-Dump am Funktionsende.

**#5 – Cash-Doppelbuchung bei TP-Gap (signal_manager.py).** `hit_tp` wurde vor dem
Partial-TP-Block berechnet; ein Overnight-Gap über den TP (≥2.5×ATR ⇒ auch
≥1.5×ATR) ließ Partial UND Full-Close im selben Tick feuern → ~150% Cash zurück.
**Fix:** Partial-TP nur wenn `not hit_sl and not hit_tp`.

### 🟠 Short-Seite

**#6 – Shorts wurden mit Long-Metriken bewertet (signal_manager.py).** Ranking,
Sizing-Tier und Grok-News-Gate nutzten durchgängig `conviction_score` (bullish),
und der Priority-Score rankte `tech_score` aufsteigend gut (für Shorts ist niedriger
tech_score aber das stärkere Signal). **Fix:** Helfer `_dir_conviction(c, direction)`
(LONG=`conviction_score`, SHORT=`conviction_score_bear`); im Priority-Score wird der
Tech-Beitrag für Shorts invertiert (`1 - tech_score`). Gespeicherte
`positions.confidence` und Telegram zeigen jetzt die richtungsrichtige Conviction.

**#7 – Short-Thesis-Gate (2/4) war ein No-Op (signal_manager.py).** Kriterien 1
(bear-Conviction ≥ Schwelle) und 4 (`tech_direction='SHORT'`) sind per Kandidaten-
Query ohnehin erfüllt → jeder Kandidat startete mit 2/4. **Fix:** Kriterium 1 zählt
nur bei conviction_bear ≥ Schwelle + 0.10; Kriterium 4 nur bei zusätzlich
tech_score < 0.40. Für 2/4 müssen jetzt echte unabhängige Belege
(Bewertung/Analyst) dazukommen.

**#8 – active_exit_check behandelte Shorts falsch (active_exit_check.py).**
`TECH_BROKEN` basierte auf einem Bullish-Count – „broken" ist für einen SHORT aber
gut. **Fix:** Richtungsabhängig: LONG schließt bei `broken`, SHORT bei `intact`
(Setup gegen uns). Zusätzlich fehlte der Trailing-Stop-Zweig für SHORT komplett →
ergänzt (gespiegelt).

**#9 – Sizing-Risiko ≠ realer Stop (signal_manager.py).** Risk-Parity rechnete mit
`cfg["atr_sl_multiplier"]` (1.5), der reale SL kommt aber aus den Asset-Type-
Multiplikatoren (TECH 2.0×, DEFENSIVE 1.0×) → Ist-Risiko wich um ±33% ab.
**Fix:** Sizing nutzt `get_asset_multipliers(get_asset_type(sector))["atr_sl"]`.

### 🟠 Optimizer / Metriken

**#10 – Optimizer optimierte entkoppelte/mehrdeutige Parameter
(strategy_optimizer.py).** `atr_sl/tp` steuern live keine Exits mehr (Asset-Type tut
das); `min_confidence` filtert im Backtest gegen `positions.confidence` (=Conviction),
live aber gegen `tech_score`; ohne Intraday-Pfad kann ein weiterer TP nie „getroffen"
werden (Bias Richtung enger Parameter). **Fix:** Als bekannte Grenzen klar
dokumentiert; Auto-Übernahme bleibt an `IMPROVEMENT_THRESHOLD` (10%) und WF ab
30 Trades gekoppelt.

**#11 – Slippage-Inkonsistenz zwischen den Exit-Engines
(utils.py, signal_manager.py, active_exit_check.py).** `signal_manager`-Close hatte
KEINE Exit-Slippage; `active_exit_check` schlug die Entry-Slippage DOPPELT auf
(`entry_price` in der DB ist bereits effektiv). **Fix:** gemeinsamer Helfer
`utils.realized_pnl_from_effective_entry()` – nur Exit-Slippage + Commission,
in beiden Engines verwendet.

**#12 – Sektor-Probation kaputt (signal_manager.py).** `probation_done` wurde nie
auf `True` gesetzt → beliebig viele 50%-Probation-Trades, Removal-/Auswertungspfad
toter Code. **Fix:** nach erfolgreichem Probation-Entry `probation_done=True` +
`save_config`.

**#13 – min_confidence-Ratchet (signal_manager.py).** `adapt_strategy` hob
`min_confidence` nur an (VIX/Loss-Serien), senkte nie → Drift Richtung 0.80 →
Entry-Starvation. **Fix:** Recovery-Pfad – bei VIX < 20, Win-Rate ≥ 55% und keiner
Verlustserie schrittweise −0.02 Richtung Floor (`min_confidence_floor`, Std. 0.60).

**#16 – nightly_eval-Metriken verzerrt (nightly_eval.py).** Sortino/Calmar/MaxDD
behandelten Positions-`pnl_pct` als Portfolio-Rendite (−10%-Position ≈ −1,5%
Portfolio) → stark überzeichnet. **Fix:** Portfolio-gewichtete Renditen
(`pnl_eur / total_value`) via `_portfolio_returns_pct()`.

### 🟡 Robustheit

**#14 – Nebenläufigkeit / Lost Updates (utils.py, signal_manager.py,
active_exit_check.py, drawdown_monitor.py).** `breaking_news_monitor` (10–17),
`signal_manager check_only` (13–20), `active_exit_check`+`thesis_monitor` (15:30)
liefen überlappend; Read-Modify-Write auf `portfolio.cash` über getrennte
Connections → Lost-Update-Risiko. `drawdown_monitor` umging zudem
`config.db_connect()` (kein WAL/busy_timeout). **Fix:** gemeinsames
`utils.portfolio_lock()` (flock auf `data/portfolio.lock`); `active_exit_check`
kapselt `main()` darin; `signal_manager` nutzt jetzt DASSELBE Lock-File
(`portfolio.lock` statt `signal_manager.lock`) → alle Cash-Writer schließen sich
gegenseitig aus. `drawdown_monitor` nutzt `config.db_connect` (nur Reader auf
`portfolio`, daher ohne Lock) + Mark-to-Market.

**#15 – Stiller FX-Faktor 1.0 (utils.py).** Unbekannte Währung gab kommentarlos 1.0
zurück. **Fix:** erst Fallback-Tabelle, sonst WARN-Log (Ticker sollte verworfen
werden).

**#17 – _price_cache wuchs unbegrenzt (utils.py).** Volle 2y-DataFrames pro Ticker
ohne Eviction. **Fix:** `_cache_store()` mit TTL-Eviction + harter Obergrenze
(`_PRICE_CACHE_MAX=400`, ältester Eintrag wird verdrängt).

**#18 – x_search JSON-Parsing (xsearch_helper.py).** Greedy `r'\{.*\}'` fasste bei
mehreren JSON-Blöcken die falsche Spanne. **Fix:** `_extract_first_json()` via
`JSONDecoder.raw_decode` – erstes sauber dekodierbares Objekt.

**#19 – Quellen-Attribution + Telegram-HTML (nightly_eval.py, signal_manager.py).**
`source_channel LIKE '%channel%'` konnte Quellen mit Teilstring-Namen
quer-attribuieren → Whole-Token-Match gegen die kommagetrennte Liste. Firmennamen
mit `<`/`&` brachen `parse_mode=HTML` (Nachricht ging still verloren) →
`send_telegram` sendet bei HTTP 400 automatisch ohne `parse_mode` erneut.

### Nicht umgesetzt (bewusst)
- `SLIPPAGE_PCT`/`COMMISSION_EUR` sind weiterhin in `config.py` UND `utils.py`
  definiert (identische Werte). Konsolidierung wäre wünschenswert, birgt aber
  Divergenz-Risiko bei falscher Migration → separat behandeln.

### Konfigurations-Hinweise (neu)
- `DASHBOARD_BIND` (Std. `127.0.0.1`), `DASHBOARD_TOKEN` (Pflicht bei LAN-Bind)
- `min_confidence_floor` in `strategy_config.json` (Std. 0.60, für #13)
- Neues Lock-File: `data/portfolio.lock` (ersetzt `signal_manager.lock`)
