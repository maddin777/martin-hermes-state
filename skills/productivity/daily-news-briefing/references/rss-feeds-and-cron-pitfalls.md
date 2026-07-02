# RSS Feeds, Weather API & Cron Pitfalls — Daily News Briefing Reference

## Verified Working RSS Feeds (Stand Juni 2026)

| Source | URL | Format | Sprache | Hinweis |
|--------|-----|--------|---------|---------|
| tagesschau.de | `https://www.tagesschau.de/xml/rss2/` | RSS 2.0 | DE | Zuverlässigste deutsche News-RSS |
| Google News DE (Top) | `https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de` | RSS 2.0 | DE | Aggregiert, gut für Breaking |
| NYT World | `https://rss.nytimes.com/services/xml/rss/nyt/World.xml` | RSS 2.0 | EN | Übersetzen |
| heise online | `https://www.heise.de/rss/heise-atom.xml` | Atom | DE | IT/Tech |
| WELT | `https://www.welt.de/feeds/latest.rss` | RSS 2.0 | DE | Allgemein |
| Reuters Top | `https://feeds.reuters.com/reuters/topNews` | RSS 2.0 | EN | Ggf. User-Agent nötig |

## Google News RSS — Topic-Specific Searches

Basis-URL: `https://news.google.com/rss/search?q=KEYWORDS&hl=de&gl=DE&ceid=DE:de`

### Bewährte Such-URLs für die 4 Sektionen

**Politik & Internationales:**
```
https://news.google.com/rss/search?q=Politik+International+G7+EU&hl=de&gl=DE&ceid=DE:de
```

**Finanzen & Wirtschaft:**
```
https://news.google.com/rss/search?q=DAX+%C3%96l+Gold+Bitcoin+B%C3%B6rse+Finanzen&hl=de&gl=DE&ceid=DE:de
```
(`%C3%96l` = Öl, URL-encodete Umlaute)

**IT & KI:**
```
https://news.google.com/rss/search?q=KI+Artificial+Intelligence+Tech+heise+golem&hl=de&gl=DE&ceid=DE:de
```

**Deutschland & Nordeuropa:**
```
https://news.google.com/rss/search?q=Schleswig-Holstein+Mecklenburg-Vorpommern+Norddeutschland&hl=de&gl=DE&ceid=DE:de
```

## Known-Broken RSS URLs (NICHT verwenden)

| Quelle | Kaputte URL | Grund |
|--------|------------|-------|
| Handelsblatt | `handelsblatt.com/rss/rssindex/17478464.html` | 404 HTML |
| NDR | `ndr.de/nachrichten/norddeutschland/rss.xml` | 404 |
| Ostsee-Zeitung | `ostsee-zeitung.de/rss/feed/ozserie2` | Auth-Redirect |
| Golem | `golem.de/news/golem-newsfeed-*.xml` | 404 |

## Open-Meteo Weather API (kein API-Key)

### Ratzeburg (53.70, 10.75)
```
curl -s "https://api.open-meteo.com/v1/forecast?latitude=53.70&longitude=10.75&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto"
```

### Schwerin (53.63, 11.41)
```
curl -s "https://api.open-meteo.com/v1/forecast?latitude=53.63&longitude=11.41&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto"
```

### Python Parser
```python
import json, sys
d = json.load(sys.stdin)
d2 = d['daily']
tag = 0  # 0=heute, 1=morgen etc.
print(f'{d2["temperature_2m_max"][tag]}°C / {d2["temperature_2m_min"][tag]}°C, Regen-wkt: {d2["precipitation_probability_max"][tag]}%')
```

## Water Temperature Research (browser fallback)

Keine kostenlose API für Wassertemperaturen verfügbar. Browser-basiert:

| Gewässer | URL |
|----------|-----|
| Ostsee Lübeck/Trave | `https://www.wassertemperatur.org/ostsee/luebeck/` |
| Ostsee Wismar | `https://www.wassertemperatur.org/ostsee/wismar/` |
| Ostsee Rostock | `https://www.wassertemperatur.org/ostsee/rostock/` |
| Ostsee Warnemünde | `https://www.wassertemperatur.org/ostsee/warnemuende/` |
| Schweriner See | `https://www.wassertemperatur.org/schweriner-see/` |

### Browser Workflow
```python
browser_navigate("https://www.wassertemperatur.org/ostsee/luebeck/")
snap = browser_snapshot(full=True)
# Aus dem Snapshot-Text die Temperatur extrahieren (z.B. "16.6°C")
```

Alternative: `seatemperature.org` über browser, z.B.:
`https://www.seatemperature.org/europe/germany/`

## Telegram Delivery Pattern (manuelle Runs)

Wenn das Briefing manuell (nicht via Cron) versendet werden muss:

```bash
source /root/.hermes/profiles/hermes-news/.env
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_HOME_CHANNEL}" \
  -d "text=NACHRICHT" \
  -d "parse_mode=Markdown"
```

Für mehrere Nachrichten: curl mehrfach aufrufen mit verschiedenen Texten.

**Wichtig:** Der Prompt-Validator blockiert curl-Befehle im Cron-Job-Prompt (`threat pattern 'exfil_curl_url'`). Also NIE curl in den Prompt schreiben — entweder `deliver: origin` im Profil-Scheduler nutzen oder manuell via terminal ausführen.

## Cron Job Tool Constraints

| Tool | Status in Cron | Workaround |
|------|---------------|------------|
| `execute_code` | ❌ BLOCKED | `read_file` + manuelles Parsen |
| `curl \| python3` | ❌ BLOCKED | In terminal()-Aufrufen erlaubt (nicht-cron) |
| `web_search` | ⚠️ Meist ohne Credits | RSS-Fallback (Google News RSS) |
| `web_extract` | ⚠️ Meist ohne Credits | RSS-Fallback |
| `send_message` | ❌ Nicht nötig | Auto-Delivery via Profil-Gateway |

## no_agent Scripts: Python Path

**Wichtig:** no_agent Cron-Jobs (script-only) werden mit `sys.executable` des Schedulers ausgeführt = **Hermes Agent venv** (`/root/.hermes/hermes-agent/venv/bin/python`), nicht mit dem system Python3.

**Konsequenz:** Pakete die im system Python (pyenv) installiert sind (yfinance, pandas, etc.) sind in der Hermes Agent venv NICHT verfügbar und müssen dort separat installiert werden.

**Fix:** 
```bash
uv pip install <package> --python /root/.hermes/hermes-agent/venv/bin/python
```

**Oder:** Statt no_agent einen normalen agent-driven Cron-Job verwenden, der das Script per terminal() aufruft. Dann läuft es mit der Profil-Venv.

**Betroffene Cron-Jobs (Stand 19.06.2026):**
- `sp500-sma200-check` (1bbecc075d3e) — braucht yfinance in Hermes Agent venv

## Firecrawl Credit Reset

Credits werden monatlich resettet. Datum merken und ggf. im MEMORY ablegen:
- Aktuell: **13.07.2026** (Refresh)
- Dazwischen: `web_search` und `web_extract` sind de facto tot
- Workaround: Google News RSS + Open-Meteo + Browser

## Cron Job Prompt Structure (Martins aktuelle Konfiguration)

Der Prompt im `jobs.json` des `hermes-news` Profils hat folgende Struktur:

```
Du bist mein News-Agent. Erstelle ein tägliches Morgen-Briefing (06:00).

═══ ARBEITSSCHRITTE ═══
1. WEB-RECHERCHE: web_search intensiv
2. X-RECHERCHE: x_search parallel
3. DEDUP: gleiche Meldung einmal
4. ÜBERSETZUNG: international → Deutsch

═══ SEKTIONEN ═══
Pro Sektion: Top 5 Meldungen
### 🌍 Politik & Internationales
### 📈 Finanzen & Wirtschaft  
### 💻 IT & KI
### 🇩🇪 Deutschland & Nordeuropa
### WETTER & WASSER

═══ AUSGABE ═══
- Max 3000 Zeichen pro Telegram-Nachricht
- Bis zu 5 Nachrichten
- Max 15000 Zeichen gesamt
```

Modell: `nvidia/nemotron-3-super-120b-a12b:free` (Provider: `openrouter`)
Alternativ: `deepseek/deepseek-v4-flash` — schneller, ebenfalls OpenRouter
Schedule: `0 6 * * *`
Delivery: `origin` (via hermes-news Profil-Gateway)

## Subagent Delegation Pitfall

**Niemals einen Subagenten das Briefing selbst recherchieren lassen, wenn Firecrawl-Credits leer sind.** Der Subagent bekommt keine Daten (web_search/web_extract schlagen fehl) und liefert leere Überschriften.

**Fix:** Rohdaten vorab per curl/Google-RSS sammeln, strukturiert als Context übergeben, und den Subagenten nur noch formatieren + senden lassen.