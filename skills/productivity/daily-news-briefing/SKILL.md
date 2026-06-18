---
name: daily-news-briefing
description: "Create structured daily morning briefings (Morgen-Briefing) in German from multiple news sources via RSS feeds, weather APIs, and browser fallback. Handles web_search/web_extract failures gracefully. Designed for profile-cron delivery (profil-eigener Bot)."
metadata:
  hermes:
    tags: [news, briefing, rss, cron, german, morning, weather]
    schedule: "0 6 * * *"
---

# Daily News Briefing (Morgen-Briefing)

Create a structured German-language morning briefing from multiple news sources, weather data, and water temperatures. Designed to run as a cron job in an isolated Hermes profile (e.g. `hermes-news`).

## Output Format

Standard 4-section briefing (Martins Konfiguration), max 5 items per section:

```
☀️ Guten Morgen! Hier ist Euer tägliches Morgen-Briefing für den [Datum].

━━━━━━━━━━━━━━━━━━━

## 🌍 Politik & Internationales
## 📈 Finanzen & Wirtschaft
## 💻 IT & KI
## 🇩🇪 Deutschland & Nordeuropa
## 🌡️ Wetter & Wassertemperaturen
```

Each item: **Überschrift** (max 10 Wörter) + 1-2 Sätze + Quellenlink in Klammern.

## Delivery Model (CRITICAL — Profile Cron)

**Dieses Briefing läuft im hermes-news Profil, nicht im main Hermes Scheduler.**

- Der Job wird via `cron/jobs.json` im Profil-Verzeichnis definiert
- `deliver: origin` im Profil-Scheduler = Delivery über den **Profil-eigenen Bot** an `TELEGRAM_HOME_CHANNEL`
- KEIN curl/Telegram-Aufruf im Prompt — der Scheduler delivered automatisch
- Wenn das Briefing manuell getriggert werden muss: `source .env` + `curl -X POST` (siehe references)

## Workflow

### Step 1: Try web_search and web_extract first

```
web_search(query="...", limit=10)
web_extract(urls=[...])
```

If these fail (Firecrawl credits exhausted — Refresh meist 13.7.), proceed to Step 2.

### Step 2: Fetch RSS feeds directly via curl

**CRITICAL for cron jobs:** `execute_code` is blocked in cron. Use `curl -sL` and pipe to Python directly in terminal (in non-cron mode) or save to file then `read_file` (in cron mode).

```bash
# Google News DE — Top News (funktioniert immer)
curl -s "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de" | python3 -c "
import sys, xml.etree.ElementTree as ET
root = ET.fromstring(sys.stdin.read())
for item in root.findall('.//item')[:15]:
    title = item.find('title')
    source = item.find('source')
    src = source.text if source is not None else ''
    print(f'{title.text} ({src})')
"

# Topic-Specific Search (Finanzen, IT/KI, Regional)
curl -s "https://news.google.com/rss/search?q=DAX+%C3%96l+Gold+Bitcoin+B%C3%B6rse&hl=de&gl=DE&ceid=DE:de"
curl -s "https://news.google.com/rss/search?q=KI+Artificial+Intelligence+Tech+heise+golem&hl=de&gl=DE&ceid=DE:de"
curl -s "https://news.google.com/rss/search?q=Schleswig-Holstein+Mecklenburg-Vorpommern+Norddeutschland&hl=de&gl=DE&ceid=DE:de"
```

Working RSS feeds documented in `references/rss-feeds-and-cron-pitfalls.md`.

### Step 3: Weather Data via Open-Meteo API (kein API-Key nötig)

```bash
# Ratzeburg (53.70, 10.75)
curl -s "https://api.open-meteo.com/v1/forecast?latitude=53.70&longitude=10.75&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto"

# Schwerin (53.63, 11.41)
curl -s "https://api.open-meteo.com/v1/forecast?latitude=53.63&longitude=11.41&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto"
```

Parse with Python:
```python
import json, sys
d = json.load(sys.stdin)
d2 = d['daily']
print(f'Max: {d2["temperature_2m_max"][0]}°C, Min: {d2["temperature_2m_min"][0]}°C, Regen: {d2["precipitation_probability_max"][0]}%')
```

### Step 4: Water Temperatures (browser fallback, da keine offene API)

Wassertemperaturen gibt es keine kostenlose API. Workaround:

```python
# Browser-basiert auf wassertemperatur.org
# Ostsee Lübeck/Trave: https://www.wassertemperatur.org/ostsee/luebeck/
# Ostsee Wismar: https://www.wassertemperatur.org/ostsee/wismar/
# Ostsee Rostock: https://www.wassertemperatur.org/ostsee/rostock/
# Schweriner See: https://www.wassertemperatur.org/schweriner-see/
browser_navigate(url)
browser_snapshot(full=True)  # Temperatur aus dem Text extrahieren
```

Alternative: seatemperature.org via browser. Die Open-Meteo Lufttemperatur ist NICHT die Wassertemperatur.

### Step 5: Deduplicate, categorize, translate

- Same story from multiple sources → list once with all sources
- Sort into 4 sections (Politik, Finanzen, IT/KI, D/Nordeuropa) + Wetter/Wasser
- Prioritize recency (today > yesterday)
- All output in German — translate international sources

### Step 6: Assemble and deliver

- Pro Telegram-Nachricht: max 3000 Zeichen
- Aufteilen auf bis zu 5 Nachrichten:
  - Nachricht 1: Politik & Internationales + Finanzen & Wirtschaft
  - Nachricht 2: IT & KI + Deutschland & Nordeuropa
  - Nachricht 3: Wetter & Wassertemperaturen (kürzer, ggf. an letzte Sektion anhängen)
- Quellenangabe bei jeder News

## Quality Rules

- **KEINE leeren Überschriften oder Sektionen.** Martin hat sich explizit darüber beschwert. Wenn eine Sektion wenig Meldungen hat: die 1-2 relevantesten trotzdem mit Inhalt nennen. Kein "Keine Meldungen" oder "Ruhiger Tag".
- **Alle News mit Inhalt** — 1-2 Sätze pro Meldung, Kernfakt nennen
- **Quellen immer angeben** — "laut Tagesschau/Reuters"
- **Max 5 Items pro Sektion**
- Übersetzte internationale Quellen (FT, WSJ, NYT, SVT, DR, YLE, Gazeta Wyborcza) auf Deutsch wiedergeben
- Nüchtern, sachlich, Fakten pur — kein Marketing-Ton

## Subagent Delegation (When running manually)

Wenn du das Briefing nicht selbst erstellst sondern an einen Subagenten delegierst:

**DO: Strukturierte Rohdaten mitgeben**
- Google News RSS-Ergebnisse als fertige Liste
- Wetterdaten als fertige Zahlen
- Explizite Anweisung: "Sende per Telegram via `source .env && curl -X POST`"
- Den vollständigen Telegram-Befehl in den Context schreiben

**DON'T: Subagent selbst recherchieren lassen**
- Firecrawl-Credits sind oft leer → web_search/web_extract schlagen fehl
- Subagent bekommt dann keine Daten und liefert leere Überschriften
- Immer Rohdaten vorab sammeln und strukturiert übergeben

## Source Priority by Section (Martins Konfiguration)

| Section | Priority Sources |
|---------|-----------------|
| Politik & Internationales | Tagesschau, NZZ, Handelsblatt, Reuters, AP, DW, NDR, Ostsee-Zeitung, Welt, SVT, DR, YLE, Gazeta Wyborcza, FT, WSJ, NYT |
| Finanzen & Wirtschaft | FT, WSJ, Handelsblatt, Manager Magazin, WirtschaftsWoche, Finanzen.net, tagesschau Marktbericht |
| IT & KI | TechCrunch, The Verge, heise online, Golem, Table.Media |
| Deutschland & Nordeuropa | NDR, Ostsee-Zeitung, Welt, Nordkurier, SVT (Schweden), DR (Dänemark), YLE (Finnland), Gazeta Wyborcza (Polen) |
| Wetter & Wasser | Open-Meteo API (wetter), wassertemperatur.org / seatemperature.org (Browser) |

## Cron Job Constraints (Profil-Scheduler)

When running as a profile cron job (hermes-news Profil):
- `execute_code` is **blocked** in cron mode — do not attempt it
- `web_search` / `web_extract` may fail due to Firecrawl credits — always have RSS fallback ready
- `curl | python3` pipe is **safe in terminal() calls** (non-cron runs) but blocked in cron
- In cron mode: save RSS to `/tmp/` then `read_file`
- No user interaction possible — make autonomous decisions
- Final response is auto-delivered via profile gateway — do NOT use `send_message`
- Delivery goes through the **profile's own bot** (e.g. `@hermster_news_bot`), not the main DM bot
- For verification: `source /root/.hermes/profiles/hermes-news/.env && curl -s https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage...`

## Firecrawl Credit Exhaustion (Dauerzustand)

Firecrawl-Credits werden monatlich zurückgesetzt (aktuell: 13.7.). Dazwischen sind `web_search` und `web_extract` **nicht verfügbar**.

**Symptom:** `Firecrawl search failed: Payment Required: Insufficient credits`

**Workaround-Reihenfolge:**
1. Google News RSS per curl (funktioniert zuverlässig, keine Credits nötig)
2. Open-Meteo API für Wetter (kein API-Key, keine Credits)
3. Browser für Wassertemperaturen (wassertemperatur.org)
4. Direkte curl-Aufrufe auf andere RSS-Feeds (tagesschau.de, heise.de, welt.de)