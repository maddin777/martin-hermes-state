# Trading Signals Skill v4.0

## Uebersicht
KI-gestuetztes Paper-Trading System fuer deutsche und US-Aktien.
Kombiniert Social Sentiment, Fundamentaldaten und technische Analyse
zu einem vollautomatischen Portfolio-Management System mit
kontinuierlicher Selbstverbesserung.

Startkapital: 10.000 Euro | Paper-Trading only
Dashboard:    http://192.168.178.16:8081
Python:       /usr/bin/python3 (pyenv 3.12.13)

---

## Dashboard (v4.0)

Modernes Web-Interface mit 4 Tabs:
  Portfolio   Offene + abgeschlossene Positionen mit Live P&L
  Watchlist   30-Tage Kandidaten mit Conviction Score
  Quellen     Admin-Interface fuer alle Datenquellen (OHNE SSH!)
  Cron & Logs Ausfuehrungs-Status und System-Logs

Quellen-Tab Funktionen:
  YouTube   Kanaele anzeigen, hinzufuegen, entfernen
  RSS Feeds Toggle aktiv/inaktiv, Gewicht anpassen, hinzufuegen, entfernen
  Twitter   Toggle aktiv/inaktiv, Gewicht anpassen, hinzufuegen, entfernen
  Aenderungen werden direkt in sources.json + yt_channel_monitor.py gespeichert

---

## Architektur

### Layer 1: Datenbeschaffung (Mo-Fr ab 10:00)

  active_exit_check.py (10:00 + 15:30)
    Prueft bestehende Positionen auf:
    1. Tech BROKEN (EMA+MACD gedreht) -> Sofortiger Exit
    2. Profit-Sicherung bei +2x ATR -> 50% Gewinn absichern
    3. Trailing Stop alle 0.5x ATR nachziehen

  fundamental_data.py (10:30)
    FRED Makrodaten: Yield Curve (T10Y2Y), Fed Funds Rate,
                     CPI Inflation, Arbeitslosigkeit, VIX
    SEC EDGAR Form 4: Insider-Trades fuer Watchlist-Aktien
    Put/Call Ratio:   Options-Sentiment via yfinance
    Output: macro_signal.json (bullish/neutral/bearish)

  social_scanner.py (10:45)
    RSS Feeds:  Bloomberg, Reuters, Handelsblatt, FAZ,
                Boerse Online, Der Aktionaer, MarketWatch,
                Seeking Alpha, Motley Fool, Finanzen.net
    Twitter/X:  Institutionelle Accounts (Goldman, Fed,
                Bloomberg, Reuters, Bill Ackman u.a.)
    API:        twitterapi.io (kein Cookie-Problem, Key-basiert)
    Filter:     nur Tweets der letzten 24h, keine Retweets
    Konfiguration: config/sources.json (im Dashboard editierbar)

  yt_channel_monitor.py (11:00)
    11 deutsche Finanz-YouTube-Kanaele:
    mario lochner, maxim investiert, koch wall street,
    tipp checker, ohne aktien wird schwer, grey x capital,
    moritz hessel, beating beta, mission money,
    der aktionaer, techaktien
    Neue Kanaele: Dashboard Quellen-Tab oder /trading-add-channel

### Layer 2: Analyse

  signal_extractor.py (11:30)
    KI-Analyse aller Transkripte via Gemini Flash Lite (OpenRouter)
    Chunking: 15.000 Zeichen pro Chunk fuer lange Videos
    Extrahiert: Unternehmensnamen, Sentiment, Begruendung
    JSON-Fehler werden pro Chunk abgefangen

  watchlist_manager.py (11:45)
    30-Tage Watchlist mit Conviction Score:
    Score = Sentiment-Ratio x log(Mentions) x Kanalvielfalt-Bonus
    Sektor-Zuordnung via yfinance (gecached in DB)
    Injiziert RSS/Twitter/SEC Mentions in Watchlist
    UNIQUE Constraint auf name verhindert Duplikate

  technical_validator.py (12:00)
    Confluence Score (0-1) aus 7 Faktoren:
    EMA Stack 20/50/200, RSI, MACD Histogram,
    Preis vs EMA50, Volumen-Trend, Weekly EMA20
    Benoetigt 2 Jahre Kursdaten (dropna() fuer Wochenenden)

### Layer 3: Signal-Entscheidung

  signal_manager.py full (12:15)
    Makro-Filter: FRED Signal bearish -> kein neuer LONG-Kauf
    Kauf-Bedingungen (alle muessen erfuellt sein):
    - Conviction Score >= 60%
    - Mind. 2 Erwaechnungen aus versch. Quellen
    - Technischer Score >= 65%
    - Tech Direction = LONG
    - Max. 3 Positionen pro Sektor

    Dynamisches Position Sizing nach Conviction:
    - High Conviction (>= 80%): 20% des Portfolios
    - Normal (60-80%):          15% des Portfolios
    - Grenzwertig (55-65%):     10% des Portfolios

    Tiebreaker bei Gleichstand (der Reihe nach):
    1. Kanalvielfalt (verschiedene Quellen)
    2. Aktualitaet (juengste Erwaehnung)
    3. Technischer Score
    4. Anzahl Mentions
    5. Alphabetisch (deterministisch)

  signal_manager.py check_only (stündlich 11-20)
    Prueft SL/TP + Trailing Stop aller offenen Positionen
    Telegram-Benachrichtigung bei Position-Aenderung

### Layer 4: Risikomanagement

  Startkapital:            10.000 Euro
  Max. Positionen gesamt:  8
  Max. Positionen/Sektor:  3
  Min. Haltedauer:         1 Tag (kein Intraday)
  Stop-Loss:               1.5x ATR (dynamisch, Trailing)
  Take-Profit:             3.0x ATR (2:1 Ratio)
  Trailing Stop:           alle 0.5x ATR nachziehen
  Profit-Sicherung:        bei +2x ATR -> SL auf 50% Gewinn
  Breakeven:               aktiviert automatisch
  Tech-Exit:               bei EMA+MACD Umkehr -> sofortiger Exit

  Erkenntnis: Bessere Ausstiege > bessere Einstiege

### Layer 5: Selbstverbesserung (Stufe 2)

  strategy_optimizer.py (Sonntag 10:00)
    Voraussetzung: mind. 10 abgeschlossene Trades
    Grid Search: SL 1.0-2.5x, TP 2.0-5.0x, Konfidenz 60-85%
    Metriken: Win Rate, Profit Factor, Sharpe Ratio, Max Drawdown
    Composite Score = WR*0.3 + PF*0.3 + Sharpe*0.25 + DD*0.15
    Auto-Update wenn neue Parameter > 10% besser -> Telegram Report

---

## Vollstaendiger Cron-Schedule

  Mo-Fr:
  10:00  active_exit_check    Tech-Check + Profit-Sicherung (Xetra)
  10:30  fundamental_data     FRED + SEC Insider + PCR
  10:45  social_scanner       RSS Feeds + Twitter/X
  11:00  yt_channel_monitor   YouTube Scan (11 Kanaele)
  11:30  signal_extractor     KI-Analyse Transkripte
  11:45  watchlist_manager    Watchlist + Conviction Score
  12:00  technical_validator  Technische Analyse
  12:15  signal_manager full  Neue Positionen + Telegram
  11-20  signal_manager check Stuendlich SL/TP pruefen
  15:30  active_exit_check    Tech-Check + Profit-Sicherung (NYSE)

  Woechentlich:
  Freitag 20:00   signal_manager full   Wochenend-Check
  Sonntag 10:00   strategy_optimizer    Selbstverbesserung

  Taeglich:
  22:00  DB Backup            -> Obsidian Vault
  22:05  export_watchlist     Watchlist als Markdown

---

## Kommandos (Hermes-Konsole)

  /trading-scan
    Kompletter Scan-Zyklus manuell (alle Scripts)

  /trading-status
    Portfolio-Status mit offenen Positionen und P&L

  /trading-check
    SL/TP + Tech-Check sofort ausfuehren

  /trading-optimize
    Strategy Optimizer manuell starten

  /trading-watchlist
    Aktuelle Watchlist anzeigen

  /trading-add-channel URL NAME
    Neuen YouTube-Kanal hinzufuegen
    Beispiel: /trading-add-channel https://www.youtube.com/@NikNavarskij "nik navarskij"

---

## Quellen verwalten (ohne SSH)

  Im Dashboard unter Tab "Quellen":

  YouTube-Kanaele:
    -> Hinzufuegen: Name + URL eingeben + Button klicken
    -> Entfernen: Roten Entfernen-Button klicken
    -> Aenderungen in yt_channel_monitor.py gespeichert

  RSS Feeds:
    -> Toggle: Aktiv/Inaktiv per Klick
    -> Gewicht: 0.5 (schwach) bis 3.0 (stark), Speichern per Klick
    -> Hinzufuegen: Name + URL + Sprache + Gewicht
    -> Aenderungen in config/sources.json gespeichert

  Twitter/X Accounts:
    -> Toggle: Aktiv/Inaktiv per Klick
    -> Gewicht anpassen + Kategorie
    -> Hinzufuegen: Handle (ohne @) + Name + Kategorie + Gewicht
    -> Benoetigt twscrape: pip3 install twscrape --break-system-packages

  Gewicht-Empfehlungen:
    Zentralbanken (Fed):      2.0
    Institutionell (Goldman): 1.5-1.8
    News-Agenturen:           1.3-1.5
    Journalisten DE:          1.2-1.3
    Investoren:               1.0-1.5
    Privatpersonen:           0.8-1.0

---

## Konfiguration

  Credentials (/root/.hermes/.env):
    OPENROUTER_API_KEY  (Gemini Flash Lite fuer KI-Analyse)
    TELEGRAM_BOT_TOKEN  (8220070984:...)
    TELEGRAM_CHAT_ID    (-1003918757178 = Ch_hermster_trade)
    FRED_API_KEY        (optional, kostenlos bei fred.stlouisfed.org)
  TWITTERAPI_IO_KEY   (twitterapi.io, $1 Startguthaben, ~$0.15/1000 Tweets)

  Quellen-Konfiguration:
    skills/trading/config/sources.json
    -> rss_feeds, twitter_accounts, fred_indicators

  Strategie-Parameter:
    skills/trading/data/strategy_config.json
    -> wird automatisch vom strategy_optimizer angepasst

---

## Dateistruktur

  scripts/
    yt_channel_monitor.py    YouTube Ingestion (11 Kanaele)
    signal_extractor.py      KI Analyse (Gemini Flash Lite)
    watchlist_manager.py     Watchlist + Conviction Score
    technical_validator.py   Technische Analyse (yfinance)
    fundamental_data.py      FRED + SEC EDGAR + PCR
    social_scanner.py        RSS Feeds + Twitter/X
    signal_manager.py        Portfolio Management
    active_exit_check.py     Tech-Check + Profit-Sicherung
    strategy_optimizer.py    Selbstverbesserung (Stufe 2)
    export_watchlist.py      Watchlist Export Obsidian
    dashboard.py             Web Dashboard Port 8081 (4 Tabs)
    run.sh                   Hermes Runner
    setup.sh                 Erstinstallation + Cron-Setup

  config/
    sources.json             RSS/Twitter/FRED Konfiguration
                             -> im Dashboard editierbar

  data/
    trading.db               SQLite Hauptdatenbank
      positions              Trades (offen + geschlossen)
      portfolio              Kontostand
      watchlist              30-Tage Kandidaten (UNIQUE name)
      watchlist_mentions     Einzelne Erwaechnungen
      macro_data             FRED Makrodaten
      insider_trades         SEC Form 4 Insider-Trades
      options_data           Put/Call Ratios
      external_mentions      RSS + Twitter Artikel
    trading_signals.json          Extrahierte Unternehmen
    trading_signals_validated.json Tech-validierte Signale
    strategy_config.json          Aktuelle Strategie-Parameter
    macro_signal.json             Aktuelles Makro-Signal
    cron.log                      Ausfuehrungs-Log

---

## Setup und Selbstpruefung

WICHTIG: Beim ersten Laden oder wenn Cron-Jobs fehlen,
fuehre automatisch folgendes aus:

  1. Pruefe Cron-Jobs:
     crontab -l | grep yt_channel_monitor

  2. Falls leer - Setup ausfuehren:
     bash /root/.hermes/profiles/hermes_trading/skills/trading/setup.sh

  3. Pruefe Dashboard:
     systemctl is-active trading-dashboard

  4. Falls inaktiv:
     systemctl start trading-dashboard

  5. Dependencies pruefen:
     python3 -c "import yfinance, pandas_ta, feedparser, requests"

  6. Falls fehlend:
     pip3 install yfinance pandas-ta feedparser requests yt-dlp \
       youtube-transcript-api --break-system-packages
