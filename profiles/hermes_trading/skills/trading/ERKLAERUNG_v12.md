# Hermes Trading Skill — Erklärung
**Version:** v12 (Dual-System) | **Stand:** 2026-05-26
**Betrieb:** Paper-Trading (kein Echtgeld) | **Startkapital:** 10.000 €
**Dashboard:** http://192.168.178.16:8081

---

## Was ist das?

Der Hermes Trading Skill ist ein vollautomatisches **KI-gestütztes Paper-Trading-System**, das auf einem Linux-Server (Ubuntu 24, Proxmox LXC-Container) läuft. Es beobachtet täglich deutschsprachige und internationale Finanzmedien, identifiziert Investmentthemen und Aktiensignale via KI-Analyse, bewertet diese mit technischer Börsenanalyse und verwaltet ein simuliertes Aktienportfolio mit realistischen Handelsregeln.

Das System handelt **nicht mit echtem Geld**. Alle Käufe und Verkäufe sind simuliert und dienen dazu, Strategien zu testen und zu optimieren, bevor real gehandelt wird.

**Ziel:** Maximale risikoadjustierte Rendite bei Robustheit über alle Marktphasen — messbar als Alpha gegenüber SPY (S&P 500) und DAX.

---

## Zwei parallele Trading-Ansätze

Das System besteht seit v12 aus **zwei unabhängig laufenden Systemen**, die dieselbe Datenbank teilen aber unterschiedliche Strategien verfolgen:

| | Klassischer Bot | Thematic Bot |
|---|---|---|
| **Signalquelle** | YouTube, RSS, Twitter | Makro-News, Tavily, Polymarket |
| **Logik** | Reaktiv (was empfehlen Medien?) | Proaktiv (welche Themen treiben Märkte?) |
| **Horizont** | Tage bis Wochen | Wochen bis Monate |
| **Trades/Monat** | 10–20 | 2–6 |
| **Exit-Trigger** | ATR-Stop, Tech-Break | Thesis-Break (LLM), ATR als Notbremse |
| **Codeordner** | `scripts/` | `thematic/` |
| **Log** | `data/cron.log` | `data/thematic.log` |

---

## Fachliche Erklärung — Klassischer Bot

### Wie der klassische Bot eine Kaufentscheidung trifft

**Stufe 1 — Quellen scannen (04:00–05:00 Uhr):**
Täglich werden YouTube-Videos (ca. 20 Finanzkanäle), RSS-Newsfeeds (13 Quellen) und Twitter/X-Accounts (43 Accounts) ausgelesen. Bei YouTube werden die Untertitel/Transkripte der letzten 5 Tage geladen.

**Stufe 2 — KI-Analyse:**
Ein LLM (DeepSeek v4 Flash via OpenRouter) liest die Transkripte und Artikel und extrahiert strukturiert: *Welche Aktie wird erwähnt? Ist die Empfehlung bullish oder bearish? Warum?*

**Stufe 3 — Watchlist mit Conviction Score:**
Alle erwähnten Unternehmen landen auf einer 14-Tage-Watchlist. Pro Unternehmen wird ein Conviction Score (0–1) berechnet, gewichtet nach der historischen Trefferquote jeder Quelle.

**Stufe 4 — Technische Analyse:**
Kandidaten mit hohem Conviction Score werden technisch bewertet: EMA-Stack (20/50/200), RSI, MACD, ADX, Volumentrend und Wochentrend. Nur Aktien die sowohl fundamentales Sentiment als auch technische Stärke zeigen, werden für den Kauf qualifiziert.

**Stufe 5 — Portfolio-Management:**
Das System verwaltet bis zu 8 offene Positionen gleichzeitig, mit dynamischer Aufteilung je nach Marktphase (Bull/Bear/Sideways).

---

## Fachliche Erklärung — Thematic Bot

### Grundprinzip: Theme First, Stocks Second

Der Thematic Bot dreht die Logik um. Statt zu fragen *"Was empfehlen Finanzmedien?"* fragt er: *"Welche strukturellen Verschiebungen in der Wirtschaft schaffen gerade neue Investment-Opportunitäten — und wer profitiert davon, bevor der Mainstream es bemerkt?"*

### Die 7 Stufen der Thematic Pipeline

**Stufe 1 — Prediction Market Scanner (02:30 Uhr):**
Polymarket (weltgrößter Prediction Market) wird täglich nach liquiden Märkten (>100.000 USD Volumen) durchsucht. Diese Märkte liefern marktbasierte Wahrscheinlichkeiten für geopolitische Ereignisse, wirtschaftliche Entwicklungen und Regulierungsentscheidungen. Da reales Geld gesetzt wird, sind diese Wahrscheinlichkeiten oft besser kalibriert als Analysten-Umfragen. Die Daten fließen als zusätzlicher Signal-Layer in alle nachfolgenden Stufen ein.

**Stufe 2 — Theme Discovery (03:00 Uhr):**
Tavily (KI-gestützte Suche) sammelt aktuelle News aus Premium-Finanzquellen zu 5 kuratierten Themen-Queries. Claude Sonnet 4 analysiert die Snippets und identifiziert 3–5 *strukturelle Investment-Themen* — keine Einzelaktien-Stories, sondern wirtschaftliche Megatrends wie "AI-Datacenter-Stromnachfrage", "European Defense Spending Surge" oder "Semiconductor Reshoring".

Für jedes Thema wird bewertet:
- **Momentum:** accelerating / steady / decelerating
- **Underreported Score (0–1):** Wie wenig ist das Thema schon im Mainstream? Je höher, desto mehr Alpha-Potenzial.
- **PM-Signal:** Bestätigen oder widersprechen Polymarket-Märkte dem Thema?

Neue Themen werden via **Embedding-Similarity** geprüft: Wenn ein ähnliches Thema bereits existiert (Cosine-Similarity ≥ 0.88), wird es als Update zusammengeführt statt neu angelegt.

**Stufe 3 — Beneficiary Mapping (03:30 Uhr):**
Für jedes neue oder sich beschleunigende Thema werden **drei LLMs parallel** befragt (Claude Sonnet 4, GPT-4o, Gemini 2.5 Pro). Jedes Modell listet Aktien in vier Kategorien:
- **Direct Plays:** Direkte Profiteure (oft schon eingepreist)
- **Picks & Shovels:** Infrastruktur und Zulieferer (unabhängig vom Endspieler)
- **Second Derivatives:** 2 Stufen tiefer in der Wertschöpfungskette (höchstes Alpha-Potenzial)
- **Losers:** Strukturelle Verlierer (potenzielle Short-Kandidaten)

Nur Aktien die von **mindestens 2 von 3 LLMs** genannt wurden (Intersection-Logik) kommen weiter. Das filtert LLM-Halluzinationen und erhöht die Signalqualität durch echten Multi-Modell-Konsens.

**Stufe 4 — Fundamental Screener (04:00 Uhr):**
Für jeden Kandidaten werden via Finnhub Fundamentaldaten geladen: MarketCap, KGV, FCF Yield, Revenue-Wachstum, Analystenzahl, Verschuldung, nächstes Earnings-Datum. Flags werden gesetzt für überbewertete Titel, hohen Short Interest oder bevorstehende Earnings. Besonders wertvoll: Aktien mit **weniger als 8 Analysten** bekommen einen positiven Asymmetrie-Bonus — wenig Abdeckung = mehr Potenzial für Überraschungen.

**Stufe 5 — Factor Ranking (04:30 Uhr):**
Alle 172 Aktien des Anlage-Universums werden täglich nach 5 quantitativen Faktoren gerankt:

| Faktor | Berechnung | Gewicht |
|--------|------------|---------|
| Momentum | 6M-Return minus 1M-Return, Perzentil | 30% |
| Quality | ROIC + geringe Verschuldung, Perzentil | 25% |
| Value | Free Cash Flow Yield, Perzentil | 20% |
| Revision | Analysten-Estimate-Änderung 90 Tage | 15% |
| Low Volatility | 1/Vola(60d), Perzentil | 10% |

Ein Composite Score (0–100) entscheidet, welche thematischen Kandidaten auch quantitativ attraktiv sind. Nur Aktien die thematisch relevant UND fundamental stark sind, kommen ins Briefing.

**Stufe 6 — Technical Timing (05:00 Uhr):**
Der Timing Validator prüft für alle aktiven Kandidaten ob gerade eine günstige Einstiegszone vorliegt:
- **RSI Oversold:** RSI < 35 im intakten Aufwärtstrend
- **EMA50 Touch:** Preis berührt 50-Tage-EMA (Unterstützung)
- **Consolidation:** Enge Handelsspanne vor möglichem Ausbruch
- **Breakout Retest:** Nach Ausbruch Rückkehr an altes Widerstandsniveau

Status je Ticker: `READY` (Setup aktiv), `APPROACHING` (innerhalb 5%), `OVERBOUGHT`, `NEUTRAL`.

**Stufe 7 — Position Thesis Monitor (05:30 Uhr):**
Für jede offene Position prüft ein LLM täglich via aktueller News: *Ist die ursprüngliche These noch gültig?* Output: `INTACT` / `WEAKENING` / `BROKEN` mit Confidence 0–1. Bei BROKEN (Confidence ≥ 0.7) → Exit-Empfehlung im Briefing. Bei 3× WEAKENING in Folge → 50%-Reduktions-Empfehlung.

**ATR-Stop und Drawdown-Schwellen** bleiben als Notbremsen aktiv, werden aber erst bei technischen Gaps oder LLM-Ausfällen ausgelöst.

### Conviction Score und Sizing

Der Conviction Score (0–1) kombiniert alle Signale:
```
conviction = 0.30 × LLM-Konsens (1/3=0.33, 2/3=0.66, 3/3=1.0)
           + 0.25 × Factor Composite / 100
           + 0.20 × Timing Score (READY=1.0, APPROACHING=0.6)
           + 0.15 × Theme Momentum (accelerating=1.0)
           + 0.10 × Asymmetrie-Bonus (wenig Analysten)
```

Polymarket-Confirmation multipliziert: Supporting × 1.10, Contradicting × 0.85.

**Tier-Zuweisung bei 15.000 € Portfolio:**
| Tier | Conviction | Allokation |
|------|-----------|------------|
| A | ≥ 0.75 | 20–25 % (3.000–3.750 €) |
| B | 0.55–0.74 | 10–15 % (1.500–2.250 €) |
| C | 0.40–0.54 | 5–8 % (750–1.200 €) |

### Exit Quality Review (wöchentlich)

Jeden Sonntag analysiert ein LLM rückblickend alle Exits der letzten 14 Tage:
- War der Exit zu früh / korrekt / zu spät?
- Hat sich die These nach dem Exit erholt?
- Hätte ein engerer/weiterer Stop-Loss besser funktioniert?

Ergebnisse landen in `exit_quality_log` und aggregieren sich in `exit_learnings`. Nach 3 Monaten entstehen so systematische Einblicke: *"Thesis-Breaks bei Geopolitik-Themen waren zu 70% korrekt"* oder *"AI-Themen WEAKENING sollte man 5 weitere Tage halten."*

---

## Risikosteuerung (beide Systeme)

### Klassischer Bot
- **Stop-Loss:** 1.5× ATR (Average True Range = Tagesvolatilität)
- **Take-Profit:** 2.5× ATR
- **Partieller Exit:** 50% bei +1.5× ATR, SL auf Einstandspreis
- **Trailing Stop:** zieht SL automatisch nach

### Thematic Bot
- **Primärer Exit:** Thesis BROKEN (LLM Confidence ≥ 0.7)
- **Notbremse 1:** -25% vom Höchst (Trailing Drawdown)
- **Notbremse 2:** -2× ATR vom Entry (Gap-Schutz)
- **Time-Review:** LLM bewertet nach 30 Tagen "Halten oder Verkaufen?"
- **Portfolio-Drawdown-Schutz:**
  - -10% → Soft Warning, Tier-C-Käufe gesperrt
  - -15% → Alle Käufe gesperrt, Trailing verschärft
  - -20% → System pausiert, 72h Cooling-Off, Pflicht-Reflektion

### Gemeinsame Parameter
- **Slippage:** 0,1% pro Seite simuliert
- **Ordergebühr:** 1 € (Trade Republic)
- **Liquiditätsfilter:** min. 500.000 € Tagesumsatz
- **Earnings-Blackout:** 5 Handelstage vor Earnings
- **Max. offene Positionen:** 8 gesamt
- **Max. Themen gleichzeitig:** 3 (Thematic Bot)
- **FX-Tracking:** EUR/USD, EUR/JPY etc. werden bei jedem Trade gespeichert; PnL wird in Local Currency und EUR separat ausgewiesen

---

## Technische Erklärung

### Systemumgebung

```
Server:    Linux (Ubuntu 24), Hermes 2nd, Proxmox LXC-Container
Pfad:      /root/.hermes/profiles/hermes_trading/skills/trading/
Python:    3.12 (venv unter skills/trading/venv/)
Datenbank: SQLite (data/trading.db)
Dashboard: Flask-Webserver auf Port 8081
```

### Verzeichnisstruktur

```
trading/
├── scripts/                        # Klassischer Bot
│   ├── trading_pipeline.py         # Orchestrierung
│   ├── yt_channel_monitor.py       # YouTube Transkripte
│   ├── signal_extractor.py         # KI-Analyse (DeepSeek)
│   ├── watchlist_manager.py        # Conviction Score
│   ├── technical_validator.py      # Technische Analyse
│   ├── signal_manager.py           # Kaufen/Verkaufen/Portfolio
│   ├── active_exit_check.py        # Intraday SL/TP
│   ├── social_scanner.py           # RSS + Twitter
│   ├── fundamental_data.py         # FRED, SEC Insider, Regime
│   ├── source_lifecycle.py         # Quellen-Management
│   ├── llm_validator.py            # LLM-Kreuzvalidierung
│   ├── strategy_optimizer.py       # Walk-Forward-Optimierung
│   ├── backtester.py               # OHLC-Backtest-Engine
│   ├── nightly_eval.py             # Tages-Report + Telegram
│   ├── dashboard.py                # Webinterface (Flask)
│   ├── dashboard_thematic.py       # Thematic-Dashboard-Module
│   └── utils.py                    # Shared: Slippage, Liquidität
│
├── thematic/                       # Thematic Bot (neu ab v12)
│   ├── thematic_pipeline.py        # Orchestrator
│   ├── theme_discovery.py          # Schritt 1: Themen erkennen
│   ├── beneficiary_mapper.py       # Schritt 2: Aktien ableiten
│   ├── fundamental_screener.py     # Schritt 3: Fundamentaldaten
│   ├── factor_ranker.py            # Schritt 4: Quant-Ranking
│   ├── timing_validator.py         # Schritt 5: Technisches Timing
│   ├── thesis_monitor.py           # Schritt 6: Thesis-Check
│   ├── briefing.py                 # Schritt 7: Tages-Briefing
│   ├── prediction_market_scanner.py # Polymarket-Daten
│   ├── theme_merge_engine.py       # Embedding-basiertes Dedup
│   ├── drawdown_monitor.py         # Portfolio-Risk-Monitor
│   ├── news_cleanup.py             # TTL-Cleanup (30 Tage)
│   ├── tax_tracker.py              # Steuer-Tracking
│   ├── weekly_review.py            # Wöchentliche Review inkl. Exit-Quality
│   │
│   ├── lib/                        # Shared Libraries
│   │   ├── llm_client.py           # OpenRouter Wrapper
│   │   ├── tavily_client.py        # Tavily News API
│   │   ├── finnhub_client.py       # Finnhub Fundamentals
│   │   ├── polymarket_client.py    # Polymarket (via Hermes-Skill)
│   │   ├── embedding_client.py     # OpenAI/sentence-transformers
│   │   └── fx_rates.py             # Wechselkurse (ECB)
│   │
│   ├── prompts/                    # Versionierte LLM-Prompts
│   │   ├── theme_discovery_v1.md
│   │   ├── beneficiary_map_v1.md
│   │   ├── thesis_check_v1.md
│   │   └── pm_market_classifier_v1.md
│   │
│   ├── config/
│   │   ├── thematic_config.json    # Schwellwerte + Parameter
│   │   ├── news_sources.json       # Tavily-Query-Konfiguration
│   │   └── universe.json           # 172 Tickers im Anlage-Universum
│   │
│   └── migrations/                 # SQLite-Schema-Migrationen
│       ├── 001_initial_schema.sql  bis 007_prediction_markets.sql
│
├── config/
│   └── sources.json                # RSS-Feeds + Twitter (Klassischer Bot)
│
└── data/
    ├── trading.db                  # Hauptdatenbank (SQLite)
    ├── strategy_config.json        # Strategie-Parameter
    ├── macro_signal.json           # Aktuelles Makrosignal
    ├── cron.log                    # Logs klassischer Bot
    └── thematic.log                # Logs Thematic Bot
```

### Datenbankschema (wichtigste Tabellen)

**Klassischer Bot:**
| Tabelle | Inhalt |
|---------|--------|
| `positions` | Offene + abgeschlossene Trades (Entry, Exit, PnL, ATR, SL/TP, Thesis) |
| `watchlist` | Beobachtete Unternehmen inkl. Conviction Score |
| `watchlist_mentions` | Einzelne Erwähnungen pro Quelle und Tag |
| `portfolio` | Aktueller Kontostand |
| `source_registry` | Quellen mit Lifecycle-Status + Performance |
| `source_quality` | Historische Trefferquoten pro Quelle |
| `eval_metrics` | Tägliche Performance-Metriken |
| `benchmark` | Täglicher Vergleich vs. SPY und DAX |
| `regime_history` | Marktphasen-Erkennung (Bull/Bear/Sideways) |

**Thematic Bot (neu):**
| Tabelle | Inhalt |
|---------|--------|
| `theme_definitions` | Aktive Investment-Themen mit Momentum und PM-Signal |
| `theme_beneficiaries` | Abgeleitete Aktien pro Thema (Play-Type, LLM-Konsens) |
| `fundamentals_snapshot` | Tägliche Fundamentaldaten pro Ticker |
| `factor_scores` | Tägliches Quant-Ranking aller 172 Universum-Tickers |
| `setup_zones` | Aktive technische Setups (RSI_OVERSOLD, EMA50_TOUCH etc.) |
| `thesis_status_log` | Tägliche LLM-Bewertung jeder Position-These |
| `prediction_markets` | Polymarket-Märkte mit Kategorisierung und Preisen |
| `pm_index_definitions` | Aggregierte PM-Indizes (Geopolitical Risk etc.) |
| `news_references` | News-Metadaten (URL dauerhaft, Volltext 30d TTL) |
| `theme_merge_queue` | Pending Reviews für ähnliche Themen |
| `drawdown_log` | Portfolio-Drawdown-Historie |
| `exit_quality_log` | Rückblickende Exit-Qualitätsbewertung |
| `exit_learnings` | Aggregierte Lerneffekte aus Exit-Reviews |
| `tax_year_tracking` | YTD Gewinne/Verluste + geschätzte Steuerlast |
| `system_state` | System-Status (paused/active, Reaktivierungs-Bedingungen) |

### Cron-Schedule

```
# ═══ Täglich / Mo–Fr ═══
02:00   fundamental_data.py          Makro + Regime + Benchmark (FRED)
02:30   prediction_market_scanner.py Polymarket-Daten (Thematic)
03:00   social_scanner.py            RSS + Twitter (Klassisch)
03:00   thematic_pipeline.py         Vollständige Thematic Pipeline
04:00   trading_pipeline.py          Klassische Pipeline (YT → Signal)
04:50   llm_validator.py             LLM-Kreuzvalidierung
05:00   nightly_eval.py              Tages-Report + Telegram
09:30   active_exit_check.py         Exit-Check Xetra-Open
10:00   drawdown_monitor.py          Portfolio-Drawdown-Check (Thematic)
10:00   signal_manager.py full       Neue Positionen eröffnen
11–20   signal_manager.py check      Stündliche SL/TP-Kontrolle
15:30   active_exit_check.py         Exit-Check NYSE-Open
15:30   thesis_monitor.py            Intraday Thesis-Check (Thematic)
22:00   DB-Backup                    trading.db → Obsidian Vault
22:05   export_watchlist.py          Watchlist → Obsidian

# ═══ Wöchentlich (Sonntag) ═══
04:00   news_cleanup.py              Volltext-Cleanup (>30d)
06:00   nightly_eval.py              Wochen-Report
07:00   source_lifecycle.py          Quellen-Lifecycle (Klassisch)
08:00   strategy_optimizer.py        Walk-Forward-Optimierung (Klassisch)
08:00   weekly_review.py             Thematic Review + Exit Quality
```

### KI-Modelle und externe APIs

| Zweck | Modell / API | Wo |
|-------|-------------|-----|
| Transkript-Analyse (Klassisch) | DeepSeek v4 Flash | OpenRouter |
| Fallback Signale | GPT-4o-mini | OpenRouter |
| LLM-Kreuzvalidierung (Klassisch) | Llama 4 Scout | OpenRouter |
| Theme Discovery | Claude Sonnet 4 | OpenRouter |
| Thesis Monitor | Claude Sonnet 4 | OpenRouter |
| Beneficiary Mapping A | Claude Sonnet 4 | OpenRouter |
| Beneficiary Mapping B | GPT-4o | OpenRouter |
| Beneficiary Mapping C | Gemini 2.5 Pro | OpenRouter |
| Aktienpreise + ATR | yfinance (Yahoo Finance) | kostenlos |
| Fundamentaldaten (US) | Finnhub Free Tier | kostenlos |
| News-Aggregation | Tavily API | ~30 USD/Monat |
| Prediction Markets | Polymarket Gamma + CLOB API | kostenlos |
| Makrodaten | FRED API (Federal Reserve) | kostenlos |
| Insider-Trades | SEC EDGAR Form 4 | kostenlos |
| Twitter/X | twitterapi.io | kostenpflichtig |
| Embeddings (Theme-Merge) | sentence-transformers (lokal) | kostenlos |

### Umgebungsvariablen

```bash
OPENROUTER_API_KEY    # OpenRouter (alle LLM-Calls)
TELEGRAM_BOT_TOKEN    # Telegram-Bot für Benachrichtigungen
TELEGRAM_CHAT_ID      # Telegram Chat-ID
TWITTERAPI_IO_KEY     # twitterapi.io
TAVILY_API_KEY        # Tavily News Search
FINNHUB_API_KEY       # Finnhub Fundamentaldaten
FRED_API_KEY          # FRED Makrodaten
PYTHONPATH            # /root/.hermes/.../trading (für thematic-Imports)
```

### Polymarket-Integration

Polymarket-Daten werden über den bestehenden Hermes-Research-Skill eingebunden (`/root/.hermes/hermes-agent/skills/research/polymarket/scripts/polymarket.py`). Kein API-Key nötig — Read-Only-Zugriff auf die öffentliche Gamma und CLOB API.

Täglich werden ~440 relevante Märkte (nach Volumen und Kategorie gefiltert) gescannt. Eine keyword-basierte Kategorisierung klassifiziert sie in: `geopolitics`, `politics`, `economics`, `tech`, `regulatory`. Sport und andere irrelevante Kategorien werden gefiltert.

Die Märkte werden via LLM den aktiven Themen und Tickers zugeordnet. Im Dashboard sind sie im "Prediction Markets"-Subtab sichtbar.

### Dashboard-Struktur

Das Webinterface unter http://192.168.178.16:8081 zeigt:
- **Portfolio-Tab:** Offene Positionen, abgeschlossene Trades, Performance vs. SPY/DAX
- **Watchlist-Tab:** Klassische Watchlist mit Conviction Score
- **Thematic-Tab** (neu):
  - *Today's Briefing:* Tages-Briefing mit Red/Yellow Alerts
  - *Theme Watchlist:* Alle Kandidaten mit Farbcodierung (Rot=Action, Gelb=Watch, Grün=Position, Grau=Monitoring)
  - *Themes:* Übersicht aktiver Themen mit PM-Confirmation-Status
  - *Position Thesis Health:* Thesis-Status-Historie pro Position
  - *Prediction Markets:* Polymarket-Märkte und PM-Indizes
  - *Theme Merge Queue:* Manuelle Review für ähnliche Themen
  - *Drawdown Status:* Portfolio-Drawdown-Monitor
  - *Tax Summary:* YTD Steuer-Tracking
- **Quellen-Tab:** Admin-Interface für Quellen-Management
- **Cron & Logs-Tab:** Status aller Jobs, Logs beider Systeme

---

## Selbstverbesserungsschleifen

### Klassischer Bot (wöchentlich)
```
Tägliche Signale → Trade ausgeführt → Position in DB
        ↓ (Sonntag)
Walk-Forward-Backtest (4 Folds)
  → Parameter nur übernehmen wenn ≥60% OOS-Folds profitabel
        ↓
Source Quality Update
  → Gewichte nach Trefferquote und Avg-PnL pro Quelle
        ↓
Discovery via KI
  → Coverage-Lücken füllen (Region × Kategorie)
```

### Thematic Bot (wöchentlich)
```
Tägliche Signale → Thesis-Monitor → Exit-Entscheidung
        ↓ (Sonntag)
Exit Quality Review
  → War der Exit zu früh/korrekt/zu spät?
  → Hätte anderer SL besser geholfen?
  → Lessons in exit_learnings persistiert
        ↓
Theme Lifecycle Review
  → Dormante Themen archivieren
  → PM-Confirmation-Status aktualisieren
```

---

## Risikoparameter (aktuell)

```
Startkapital:              10.000 €
Max. Portfolioallokation:  70% (30% Cash-Reserve)
Max. SHORT-Allokation:     30% (klassisch)
Position Size:             10–25% pro Trade (conviction-basiert)
Stop-Loss (klassisch):     1.5× ATR
Take-Profit (klassisch):   2.5× ATR
Stop-Loss (thematic):      25% Trailing vom Höchst
Thesis-Break-Schwelle:     LLM Confidence ≥ 0.7
Slippage:                  0.1% pro Seite
Ordergebühr:               1 € (Trade Republic)
Liquiditätsfilter:         min. 500.000 € Tagesumsatz
Earnings-Blackout:         5 Handelstage vor Earnings
Min-Hold (Thematic):       21 Tage
Drawdown Soft Warning:     -10% vom ATH
Drawdown Hard Stop:        -15% vom ATH
Drawdown Auto-Pause:       -20% vom ATH (72h Cooling-Off)
```

---

## Monatliche Betriebskosten

| Service | Kosten/Monat |
|---------|--------------|
| Tavily API (News-Aggregation) | ~30 USD |
| OpenRouter (LLMs) | ~50–70 USD |
| twitterapi.io | variabel |
| Alle anderen APIs | kostenlos |
| **Gesamt** | **~80–100 USD/Monat** |

---

## Änderungshistorie

| Version | Wichtigste Änderungen |
|---------|----------------------|
| v7 | Grundsystem: YT-Scan, KI-Extraktion, Watchlist, TA, Portfolio |
| v8 | Plan: SHORT-Integration, Walk-Forward, Slippage, Source Lifecycle |
| v9 | Umsetzung v8-Plan: alle Kernfeatures implementiert |
| v10 | Bug-Fixes, Benchmark-Integration, Equity-Kurve, Dynamische Limits |
| v11 | Backtester: sl_multiplier parametrisierbar; Dashboard-Fixes; Locale-Fix |
| v12 | **Thematic Bot** (parallel): Theme Discovery, Multi-LLM Beneficiary Mapping, Factor Ranking, Thesis Monitor, Polymarket-Integration, Exit Quality Review, erweitertes Dashboard |

---

*Pfad auf Server: `/root/.hermes/profiles/hermes_trading/skills/trading/ERKLAERUNG.md`*
