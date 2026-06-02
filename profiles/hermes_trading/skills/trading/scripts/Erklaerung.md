# Hermes Trading Skill – Technische & Fachliche Dokumentation

*Stand: Juni 2026 | System-Version nach Paketen A–D + Sprints 1–7*

---

## 1. Überblick

Hermes Trading ist ein vollautomatisches Paper-Trading-System das täglich auf einem Linux-Server (hermes2nd) läuft. Es scannt deutschsprachige und internationale YouTube-Finanzkanäle sowie Twitter/X-Accounts, extrahiert Aktien-Mentions mit KI, bewertet sie nach Sentiment, Stärke und technischer Analyse und verwaltet ein simuliertes Aktienportfolio.

Das System läuft ohne menschliches Eingreifen, benachrichtigt aber per Telegram über alle Signale und Trades.

**Startkapital:** 10.000 € (simuliert)  
**Märkte:** XETRA (DE), NYSE/NASDAQ (US), SIX (CH), Euronext (EU), weitere  
**Handelsrichtungen:** LONG und SHORT  

---

## 2. Tagesablauf (Cron, Mo–Fr)

```
02:00  fundamental_data.py       → Makrodaten (FRED: VIX, Yield Curve, CPI), Regime-Erkennung
02:30  thematic/prediction_market_scanner.py  → Polymarket-Signale
03:00  social_scanner.py          → RSS-Feeds + Twitter/X-Accounts
03:00  thematic/thematic_pipeline.py          → Thematische Signale
04:00  trading_pipeline.py        → Hauptpipeline (5 Scripts sequenziell):
         ├─ yt_channel_monitor.py      → YouTube-Transkripte holen
         ├─ signal_extractor.py        → LLM-Analyse (DeepSeek, GPT-4o-mini Fallback)
         ├─ technical_validator.py     → Ticker-Auflösung + Tech-Score
         ├─ watchlist_manager.py       → Conviction berechnen + Watchlist aggregieren
         └─ signal_manager.py          → Portfolio-Management + Positionen
04:50  llm_validator.py           → Kreuzvalidierung High-Conviction Signale
05:00  nightly_eval.py            → Performance-Metriken (Sortino, Calmar, R-Multiple)
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

### Step 3: Technical Validator (`technical_validator.py`)

Löst Firmennamen über `company_validator.py` in Ticker auf. 5-stufige Pipeline: Cache → yf.Search → Equity-Check → Namens-Ähnlichkeit → Liquidität. Berechnet dann Confluence Score über 7 Indikatoren.

| Indikator | Gewicht | Logik |
|-----------|---------|-------|
| EMA Stack (20>50>200) | ±1 | Trend-Richtung |
| RSI (14) | ±2 | 50–60 ideal, >75 überkauft |
| MACD Histogram | ±2 | Vorzeichen + Richtung |
| Preis vs. EMA50 | ±1 | Abstand in % |
| Volumen-Trend | +1.5 | 5d vs. 20d Average |
| Weekly Trend | ±1 | Preis > EMA20 wöchentlich (lokal resampled aus Tagesdaten zur API-Schonung) |
| ADX (14) | ±1 | Trendstärke |

Normalisierung: `confidence = (score + 10) / 20`

### Step 4: Watchlist Manager (`watchlist_manager.py`)

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

### Step 5: Signal Manager (`signal_manager.py`)

**Entry-Hierarchie:**
```
1. Drawdown-Notbremse: –15% ATH → kein Entry | –25% ATH → alles schließen + Telegram
2. Makro-Filter: bearish + bear-Regime → keine LONGs
3. VIX > 30 → Position Size halbieren
4. Cash-Reserve: min(1.500€, 15% Portfolio)
5. Budget-Limit: max 70% investiert
6. Max 8 offene Positionen
7. Sektor-Cap: max 2 pro Sektor (JOIN auf companies.sector)
8. Short-Thesis Score: mind. 2 von 4 Kriterien (Sentiment + P/E + Analyst + Tech)
9. Kein Re-Entry innerhalb 24h
10. Krypto-Filter: -USD/-USDT-Ticker geblockt
11. Liquiditätsfilter: Tagesvolumen ≥ 500.000€
12. Earnings-Blackout: 5 Tage vor Earnings
```

**Position Sizing (Vola-bereinigt / Risk-Parity):**
Das Sizing erfolgt über ein **volatilitätsbereinigtes Risk-Parity-Modell**, um das Risiko unabhängig von der Schwankungsbreite der Aktie im Portfolio zu harmonisieren:
- **Zielrisiko pro Trade:** Maximal **1,5 % des Portfoliowerts** Verlust bei Auslösen des ATR-Stop-Loss.
- **Formel:** `Stückzahl = (Portfolio-Wert * 0.015) / (ATR * sl_multiplier)`
- **Dynamisches Limit (Capping):** Die berechnete Positionsgröße wird weiterhin risikoorientiert gedeckelt durch das klassische Conviction-Limit (HIGH = 20%, NORMAL = 15%, LOW = 10% des Portfolios, halbiert bei VIX > 30) sowie durch das verfügbare Cash und verbleibende Budget-Kapazitäten.

**Exit-Management:**
- SL: 1.5×ATR | TP: 2.5×ATR
- Partial Exit bei +1.5×ATR (50%)
- Trailing Stop alle 0.5×ATR
- Breakeven bei +2.0×ATR

---

## 4. Twitter/X Integration

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
1. `discover_new_sources()`: LLM (DeepSeek via OpenRouter) schlägt YouTube-Kanäle und RSS-Feeds vor basierend auf Coverage-Lücken. **Twitter wird hier bewusst ausgeschlossen** – LLMs halluzinieren Twitter-Handles aus veralteten Trainingsdaten.
2. `discover_twitter_via_grok()`: Sucht über Grok **echte, heute-aktive** Accounts via Echtzeit-X-Suche → extrahiert @handles aus tatsächlichen Tweets → validiert via twitterapi.io (Follower ≥ 5.000) → trägt als Candidate ein

**Lifecycle:**
```
candidate (30d Probezeit)
    ↓ 5+ Trades, WR ≥ 45%
active (gewichtet nach Performance)
    ↓ WR < 30%, 5+ consec. Verluste, oder:
    ↓ 14 Tage keine Tweets (Twitter-spezifisch)
suspended (disabled)
    ↓ 30 Tage keine Tweets (Twitter-spezifisch)
removed
```

YouTube/RSS: Inaktivitäts-Schwelle 90 Tage. Twitter: 14d suspend, 30d remove.

**Gewichtung:** Win-Rate > 60% → Gewicht ×1.15 (max 2.5×). Win-Rate < 35% → Gewicht ×0.80 (min 0.3×).

**Signal-Qualität als Früh-Indikator (neu):**  
Twitter-Quellen haben anfangs keine Trade-Historie. `nightly_eval.py` berechnet daher zusätzlich die *signal_quality*: Anteil der Mentions die zu einer Watchlist-Aufnahme (conviction ≥ 55%) führten. Neue Quellen werden damit bereits nach wenigen Tagen bewertet statt 30+ Tage auf Trades zu warten.

**Halbwertszeit-Kalibrierung:**  
`nightly_eval.py` meldet täglich das Verhältnis von `conviction_raw` zu `conviction_aged`. Bei Decay-Ratio < 0.60 → Hinweis dass `CONVICTION_HALF_LIFE_DAYS` in `config.py` erhöht werden sollte.

---

## 5. Makro-Regime-Erkennung (fundamental_data.py)

**Zwei-dimensionales Modell:**

```
Trend-Dimension (Markov Chain):
  SPY 20d-Return (60% Gewicht) + DAX 20d-Return (40% Gewicht)
  z-Score > 0.5 → bull | z-Score < -0.5 → bear | sonst sideways
  US-Regime und EU-Regime werden separat berechnet

Makro-Overlay (−2 bis +2 Punkte):
  VIX < 18     → +1.0 (Risk-On)
  VIX > 28     → −1.0 (Risk-Off)
  HYG 20d > 1% → +1.0 (Credit-Spreads eng = Risk-On)
  HYG 20d < −1%→ −1.0 (Spreads weiten sich)
  DXY 20d > 2% → −0.5 (starker Dollar = Risk-Off)
  DXY 20d < −2%→ +0.5 (schwacher Dollar = Risk-On)

Kombination:
  Overlay ≥ +1.5 + Trend=sideways → Regime auf bull korrigiert
  Overlay ≤ −1.5 + Trend=bull/sideways → Regime auf bear korrigiert
```

Alle Werte werden in `macro_signal.json` geschrieben und in `regime_history` persistiert. `signal_manager.py` liest das kombinierte Regime und wendet Conviction-Anpassungen an.

---

## 6. Thesis-System (thematic/)

Jede Position kann mit einer Investment-These (`thesis_text`) und einem Theme (`thesis_theme_id`) verknüpft werden. `thesis_monitor.py` prüft täglich ob die These noch intakt ist:

**Status-Logik:**
- `no_thesis`: kein `thesis_theme_id` und kein `thesis_text` → kein LLM-Call, kein Alert
- `intact`: These bestätigt
- `weakening`: leichte Verschlechterung (3× in Folge → Telegram: 50%-Reduktions-Empfehlung)
- `broken`: klare Gegenbeweise (confidence ≥ 70%) → SL auf 0.5×ATR enger ziehen + Alert (behoben: case-sensitive Abgleich mit DB-Wert 'BROKEN')

**Conviction-Boost durch Thesis:**
Wenn ein Ticker in `theme_beneficiaries` eingetragen und das Theme aktiv ist:
- +8% bei intact + bullishem Momentum
- +5% bei intact
- +2% bei noch kein Check
- 0% bei broken/degraded

---

## 7. Breaking News Monitor (breaking_news_monitor.py)

Läuft stündlich 10–17 Uhr. Für jede offene Position:
1. Tavily: aktuelle News der letzten 24h holen
2. LLM: Sentiment-Score 0.0 (positiv) – 1.0 (negativ)
3. Bei Score ≥ 0.65: SL auf 0.5×ATR enger ziehen + Telegram-Alert
4. Bei Pre/After-Hours-Bewegung > 5%: sofortiger Alert

---

## 8. Datenbankstruktur (Auswahl)

| Tabelle | Zweck |
|---------|-------|
| `videos` | YouTube-Videos mit Status (pending/done) |
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

---

## 9. Quellen-Management

```
Quellen-Typen: YouTube | RSS | Twitter/X
Lifecycle: candidate → probation → active → suspended → removed
```

**Discovery:**
- LLM-basiert (OpenRouter): schlägt neue Quellen vor basierend auf Coverage-Lücken
- Grok-basiert (Twitter only): findet echte aktive Accounts aus aktuellen Tweets

**Performance-Tracking (wöchentlich):**
- Win-Rate (90d), avg PnL pro Trade, consecutive Losses
- Gewicht-Anpassung: 0.3× bis 2.5× (fließt in Conviction Score ein)
- Inaktivitäts-Check: Twitter 14d/30d, YouTube/RSS 90d

---

## 10. Company Knowledge Base

- **863 Firmen** in `companies`-Tabelle (Stand: Juni 2026)
- **YAML-Export:** `python3 export_companies_yaml.py` → `companies.yaml` (git-versionierbar)
- **Validierungs-Pipeline:** 5 Stufen (Cache → yf.Search → Equity → Namens-Ähnlichkeit → Liquidität)
- **ISIN-Mapping:** Step 0 erkennt US.../IE...-ISIN-Pattern, 8 bekannte ISINs gemappt
- **Normalisierung:** `company_normalizer.py`, 203 Aliases, Legal-Suffix-Strip

---

## 11. Code-Architektur

```
scripts/
├── config.py              ← Alle Pfade + Konstanten (single source of truth)
├── utils.py               ← get_technical_score(), prefetch_prices(), get_price_data_cached(),
│                             retry(), get_logger()
├── company_normalizer.py  ← 203 Aliases, Legal-Suffix-Strip
├── company_validator.py   ← 5-stufige Validierungspipeline + ISIN-Mapping
├── xsearch_helper.py      ← Grok/X-Integration: conviction_boost, discover_finance_accounts
│
├── yt_channel_monitor.py  ← Step 1: YouTube
├── signal_extractor.py    ← Step 2: LLM (DeepSeek + Retry)
├── technical_validator.py ← Step 3: Tech-Score (delegiert an utils.py)
├── watchlist_manager.py   ← Step 4: Conviction, Thesis-Boost, Stärke-Gewichtung
├── signal_manager.py      ← Step 5: Portfolio, Entry/Exit, Drawdown, Sektor-Cap
├── trading_pipeline.py    ← Orchestrierung
│
├── active_exit_check.py   ← 2× täglich: Tech-Exit + Thesis-broken SL-Tightening
├── breaking_news_monitor.py ← Stündlich: Tavily-News + Pre/AH-Alert
├── fundamental_data.py    ← FRED + erweitertes Regime-Modell (VIX/HYG/DXY)
├── social_scanner.py      ← RSS + Twitter/X-Accounts
├── source_lifecycle.py    ← Quellen-Lifecycle + Grok-Twitter-Discovery
├── llm_validator.py       ← Kreuzvalidierung High-Conviction
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
- SQLite WAL-Modus (Write-Ahead-Logging) und 5000 ms Busy-Timeout standardmäßig aktiviert zur Vermeidung von Thread-Lockings
- DB `videos.status='done'` als primärer LLM-Cache (robust gegen JSON-Verlust)
- `@retry()` auf alle externen API-Calls (FRED, twitterapi.io, yfinance)
- `get_logger()` in allen Haupt-Modulen, RotatingFileHandler

---

## 12. Externe Dienste

| Dienst | Zweck | Schlüssel |
|--------|-------|-----------|
| OpenRouter | LLM-API (DeepSeek, GPT-4o-mini) | `OPENROUTER_API_KEY` |
| Telegram Bot | Alerts + Trade-Nachrichten | `TELEGRAM_BOT_TOKEN` |
| TwitterAPI.io | Twitter-Account-Scanning | `TWITTERAPI_IO_KEY` |
| Grok / GrokLite | X-Suche + Twitter-Discovery | via Hermes AIAgent OAuth |
| Tavily | Breaking News für offene Positionen | `TAVILY_API_KEY` |
| yfinance | Kursdaten, ATR, Fundamentals | kostenlos |
| FRED | Makrodaten | kostenlos |
| SEC EDGAR | Insider Trades | kostenlos |

Alle Keys in `/root/.hermes/.env`, geladen per `env_loader.py`. Crontab enthält keine Keys.

---

## 13. Konfiguration (config.py)

```python
CONVICTION_HALF_LIFE_DAYS = 14    # Halbwertszeit Sentiment-Aging
CONVICTION_PRIOR_NEUTRAL  = 3.0   # Bayesian Prior (konservativer bei wenig Daten)
WATCHLIST_DAYS            = 14    # Tage bis Signal aus Watchlist fällt
MIN_MENTIONS              = 2     # Mindest-Mentions für Aufnahme
MIN_CONVICTION            = 0.55  # Mindest-Conviction für Entry-Kandidaten
CASH_RESERVE_EUR          = 1500  # Immer liquide halten
MAX_ALLOC_PCT             = 0.70  # Max 70% investiert
MAX_POSITION_PCT          = 0.20  # Max 20% in einer Position
```

---

*Dokumentation aus Quellcode generiert. Bei Abweichungen gilt der Code.*
