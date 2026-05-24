# Hermes Trading Skill – Technische & Fachliche Dokumentation

*Stand: Mai 2026 | Version 4.1*

---

## Was ist das?

Der Hermes Trading Skill ist ein vollautomatisches Paper-Trading-System das auf einem Linux-Server läuft und täglich Finanzinformationen aus verschiedenen Quellen sammelt, mit KI analysiert und daraus Kauf- und Verkaufsentscheidungen für Aktien trifft.

Das System handelt **ausschließlich auf Papier** – es wird kein echtes Geld eingesetzt. Startkapital sind fiktive 10.000 €. Ziel ist es, die Strategie über mehrere Monate zu testen und zu verfeinern bevor ggf. echtes Kapital eingesetzt wird.

---

## Fachliche Funktionsweise

### Das Grundprinzip: Sentiment trifft Technik

Das System verfolgt einen Zwei-Säulen-Ansatz:

**Säule 1 – Social Sentiment:** Was reden Finanzexperten, YouTuber, Journalisten und institutionelle Investoren gerade über eine Aktie? Wird sie häufig erwähnt? Überwiegen positive oder negative Meinungen?

**Säule 2 – Technische Analyse:** Bestätigt der Chart diese Meinung? Steigt der Kurs gerade? Sind kurzfristige und langfristige Durchschnittskurse in einer bullischen Formation?

Nur wenn **beide Säulen** ein positives Signal liefern, wird eine Position eröffnet.

---

### Schritt 1: Daten sammeln (nachts, ab 02:00 Uhr)

**Makroökonomische Daten (FRED)**
Das System fragt täglich Daten der US-Notenbank ab: Ist die Zinskurve invertiert? Wie hoch ist der Leitzins? Wie hoch ist die Inflation? Wie ängstlich ist der Markt (VIX)? Aus diesen Daten wird ein globales Makro-Signal berechnet: bullish / neutral / bearish. Bei bearishem Signal wird kein neuer Trade eröffnet.

**Marktregime-Erkennung (Markov Chain)**
Ein statistisches Modell auf zwei Jahren S&P 500 und DAX-Daten klassifiziert den aktuellen Markt: Bull, Bear oder Seitwärts. Im Bear-Regime werden Long-Signale um 20% abgewertet, im Bull-Regime um 10% aufgewertet.

**Insider-Trades (SEC EDGAR)**
Für alle Watchlist-Aktien wird geprüft ob CEOs oder CFOs in den letzten 30 Tagen eigene Aktien gekauft oder verkauft haben. Ein CEO-Kauf über 500.000 USD ist ein stärkeres Signal als jede YouTube-Meinung.

**RSS-Feeds und Twitter/X**
Bloomberg, Reuters, Handelsblatt, FAZ, Börse Online und weitere Quellen werden gescannt. Parallel werden institutionelle Twitter-Accounts (Goldman Sachs, Federal Reserve, Bloomberg Markets, Bill Ackman u.a.) auf Posts der letzten 24 Stunden überwacht.

---

### Schritt 2: YouTube analysieren (04:00 Uhr)

11 deutsche Finanz-YouTube-Kanäle werden täglich gescannt:
mario lochner, maxim investiert, koch wall street, tipp checker, ohne aktien wird schwer, grey x capital, moritz hessel, beating beta, mission money, der aktionär, techaktien

Von jedem neuen Video wird automatisch das Transkript heruntergeladen. Eine KI (Google Gemini Flash Lite) analysiert jedes Transkript und extrahiert welche Unternehmen erwähnt werden, ob die Stimmung bullish oder bearish ist und warum der Ersteller die Aktie empfiehlt.

---

### Schritt 3: Die Watchlist (30-Tage-Gedächtnis)

Alle erwähnten Unternehmen landen in einer 30-Tage-Watchlist. Das System berechnet für jede Aktie einen Conviction Score (0-100%):

    Conviction = Sentiment-Ratio x log(Anzahl Erwaechnungen) x Kanalvielfalt-Bonus

Beispiel: SAP wird in einer Woche 8x erwähnt, davon 6x bullish, von 3 verschiedenen Kanälen = hoher Conviction Score.

**x_search Verbesserung:** Für Aktien mit Conviction über 70% wird zusätzlich über xAI/Grok auf Twitter/X gesucht. Findet das System dort weitere bullische Signale, steigt der Conviction Score um bis zu 10%. Bei bearishen Gegensignalen sinkt er um bis zu 15%.

---

### Schritt 4: Technische Validierung

Für jeden Watchlist-Kandidaten wird ein technischer Confluence Score (0-1) berechnet:

| Indikator | Beschreibung |
|-----------|-------------|
| EMA 20/50/200 Stack | Kurzfristig über langfristig = bullisch |
| RSI | Nicht überkauft oder überverkauft |
| MACD Histogramm | Positiv und steigend |
| Kurs über EMA50 | Mittelfristiger Aufwärtstrend |
| Volumentrend | Steigendes Handelsvolumen |
| Weekly EMA20 | Langfristiger Trend bestätigt |

Ein Score >= 0.65 ist Voraussetzung für einen Kauf.

---

### Schritt 5: Kaufentscheidung

Der Signal Manager prüft alle Bedingungen:

    Makro-Signal nicht bearish
    Marktregime nicht Bear + Makro bearish gleichzeitig
    Conviction Score >= 60%
    Mind. 2 Erwaechnungen aus verschiedenen Quellen
    Technischer Score >= 65%
    Technische Richtung: LONG
    Kein negativer Breaking-News-Alert (x_search letzte 6h)
    Freier Portfolio-Slot vorhanden
    Sektor nicht bereits 3x besetzt

**Dynamisches Position Sizing:**
- High Conviction (>= 80%): 20% des Portfolios
- Normal (60-80%): 15% des Portfolios
- Grenzwertig (55-60%): 10% des Portfolios

Bei Gleichstand entscheidet: Kanalvielfalt, Aktualitaet, Tech Score, Mentions, Alphabet.

---

### Schritt 6: Exit-Management

*"Bessere Ausstiege > bessere Einstiege"* ist die zentrale Erkenntnis des Systems.

Das System prüft zweimal täglich alle offenen Positionen (09:30 Uhr Xetra, 15:30 Uhr NYSE) plus stündlich von 13-20 Uhr:

**Exit 1 - Tech BROKEN:** Dreht EMA-Stack und MACD gleichzeitig bearish, wird die Position sofort geschlossen. Lieber mit kleinem Verlust raus als auf Erholung warten.

**Exit 2 - Profit-Sicherung:** Ist eine Position +2x ATR im Plus, wird der Stop-Loss auf 50% des aktuellen Gewinns nachgezogen. Der Gewinn kann nie mehr vollständig verloren gehen.

**Exit 3 - Trailing Stop:** Der Stop-Loss zieht mit jedem neuen Preishoch mit, immer 0.5x ATR nach.

ATR (Average True Range) ist ein Maß für die typische tägliche Kursschwankung. Stop-Loss bei 1.5x ATR bedeutet: Position wird geschlossen wenn der Kurs um das 1.5-fache der normalen Schwankung fällt. Take-Profit liegt bei 3.0x ATR = 2:1 Gewinn/Verlust-Verhältnis.

---

### Schritt 7: Selbstverbesserung

Jeden Sonntag läuft ein automatischer Optimierer:

**Grid Search:** Alle Kombinationen von Stop-Loss (1.0-2.5x ATR), Take-Profit (2.0-5.0x ATR) und Mindestkonfidenz (60-85%) werden auf bisherigen Trades getestet. Wenn eine Kombination mehr als 10% besser ist, wird sie automatisch übernommen.

**Source Weights:** Quellen mit Win Rate über 70% bekommen +10% Gewichtung. Quellen unter 30% bekommen -10%. Dauerhaft schlechte Quellen werden automatisch deaktiviert.

**Dynamische Parameter:** Wenn die 7-Tage-Win-Rate unter 40% fällt, wird die Mindestkonfidenz um 5% erhöht. Bei über 65% kann sie gelockert werden.

---

## Technische Architektur

### Infrastruktur

    Server:     Proxmox LXC Container (Ubuntu 24)
    Dashboard:  http://192.168.178.16:8081
    Agent:      Hermes Agent v0.14.0 (NousResearch)
    Python:     3.12.13 (pyenv)
    Datenbank:  SQLite (trading.db)

### Zeitplan (Cron-Jobs)

| Zeit | Job | Beschreibung |
|------|-----|-------------|
| 02:00 Mo-Fr | fundamental_data.py | FRED + SEC + PCR + Regime |
| 03:00 Mo-Fr | social_scanner.py | RSS + Twitter |
| 04:00 Mo-Fr | trading_pipeline.py | YouTube bis Kaufentscheidung |
| 05:00 Mo-Fr | nightly_eval.py | Qualitaetsmetriken + Report |
| 09:30 Mo-Fr | active_exit_check.py | Exit-Check Xetra |
| 13-20 Mo-Fr | signal_manager check | Stündlich SL/TP |
| 15:30 Mo-Fr | active_exit_check.py | Exit-Check NYSE |
| 22:00 tägl. | DB Backup | Sicherung |
| So 06:00 | nightly_eval (Woche) | Wochenaggregat |
| So 08:00 | strategy_optimizer.py | Selbstverbesserung |

### Script-Übersicht

| Script | Aufgabe |
|--------|---------|
| fundamental_data.py | FRED, SEC EDGAR, PCR, Regime-Detection |
| social_scanner.py | RSS-Feeds, Twitter via twitterapi.io |
| yt_channel_monitor.py | YouTube Transkripte (11 Kanaele) |
| signal_extractor.py | KI-Analyse via Gemini Flash Lite |
| watchlist_manager.py | Conviction Score, x_search Boost |
| technical_validator.py | EMA/RSI/MACD Confluence Score |
| signal_manager.py | Kaufentscheidung, Position Sizing |
| active_exit_check.py | Tech-Exit, Profit-Sicherung, Trailing |
| nightly_eval.py | Tages-Metriken, Widerspruchs-Check |
| strategy_optimizer.py | Grid Search, Source Weights |
| xsearch_helper.py | xAI x_search via Hermes Grok OAuth |
| trading_pipeline.py | Sequenzieller Pipeline-Ablauf |
| dashboard.py | Web-Dashboard Port 8081 |

### APIs und Kosten

| Dienst | Verwendung | Kosten |
|--------|-----------|--------|
| Gemini Flash Lite (OpenRouter) | Transkript-Analyse | ~0.01-0.05 EUR/Tag |
| Grok (xAI OAuth) | x_search Signal-Bestaetigung | Abo-Quota |
| twitterapi.io | Twitter Monitoring | 0.15 USD/1000 Tweets |
| FRED API | Makrodaten | kostenlos |
| SEC EDGAR | Insider-Trades | kostenlos |
| yfinance | Kursdaten + Technik | kostenlos |
| Telegram Bot | Benachrichtigungen | kostenlos |

### Datenbankstruktur

    trading.db
    positions          Alle Trades (offen + geschlossen)
    portfolio          Kontostand und Gesamtwert
    watchlist          30-Tage Kandidaten mit Conviction Score
    watchlist_mentions Einzelne Erwaechnungen pro Quelle
    macro_data         FRED Makroindikatoren
    insider_trades     SEC Form 4 Insider-Kaeufe
    options_data       Put/Call Ratios
    external_mentions  RSS + Twitter Artikel
    eval_metrics       Taegliche Qualitaetsmetriken
    source_quality     Win Rate pro Quelle
    regime_history     Marktregime-Verlauf

---

## Risikomanagement

| Parameter | Wert |
|-----------|------|
| Startkapital | 10.000 EUR (Paper) |
| Max. Positionen | 8 |
| Max. pro Sektor | 3 |
| Max. Position High Conv. | 20% = 2.000 EUR |
| Max. Position Normal | 15% = 1.500 EUR |
| Max. Position Grenzwertig | 10% = 1.000 EUR |
| Stop-Loss | 1.5x ATR (dynamisch) |
| Take-Profit | 3.0x ATR (2:1 Ratio) |
| Trailing Stop | alle 0.5x ATR |
| Profit-Sicherung | ab +2x ATR = 50% gesichert |
| Min. Haltedauer | 1 Tag (kein Intraday) |

---

## Telegram-Benachrichtigungen

Das System sendet automatisch bei:
- Neuer Kaufposition (mit vollstaendiger Analyse)
- Stop-Loss oder Take-Profit getroffen
- Tech-Exit einer Position
- Profit-Sicherung aktiviert
- Taeglicher Qualitaets-Report (05:00 Uhr)
- Woechentlicher Bericht mit Optimierungsmassnahmen
- Twitter-Cookie-Ablauf (Wartungshinweis)

---

*Entwickelt auf Basis von Hermes Agent v0.14.0 (NousResearch)*
*Paper-Trading only - kein reales Kapital*
