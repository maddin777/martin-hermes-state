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

## Delivery Model (CRITICAL — Default Scheduler + Profile Routing)

**Dieses Briefing läuft im default Hermes Scheduler mit `profile: hermes-news`** —
der Job lebt in `/root/.hermes/cron/jobs.json`, nicht in der Profil-Cron-DB.
Der `profile`-Parameter steuert die Runtime-Umgebung (`.env`, `config.yaml`).

**ACHTUNG — Delivery-Bot:** Der default Scheduler liefert IMMER über den
default Bot aus, NICHT über den Profil-Bot. `deliver: telegram` geht zum
`TELEGRAM_HOME_CHANNEL` des default Bots (Martins DM), nicht zum News-Channel.

**Stand 01.07.2026:** Der Job (id `769f3356b8d1`) hat:
- `profile: hermes-news` (Runtime-Kontext)
- `deliver: telegram` (→ TELEGRAM_HOME_CHANNEL des Scheduler-Bots)
- `model: deepseek/deepseek-v4-flash`
- `enabled_toolsets: [web, terminal, file, browser]`

⚠️ **Bekanntes Problem:** Wenn der default Bot den Ziel-Channel nicht kennt
(`Chat not found`), muss der Job entweder ins Profil-eigene `cron/jobs.json`
umziehen (siehe §Migration) oder via `deliver: telegram` nur in den Home-Channel
des default Bots liefern.

### Voraussetzung: Profil-Gateway läuft

Der Gateway des Ziel-Profils muss aktiv sein, sonst tickt der Scheduler nicht:

```bash
# Prüfen: Gateway läuft?
cat /root/.hermes/profiles/hermes-news/gateway_state.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('✅ Running' if d.get('gateway_state')=='running' else '❌ Dead')"
# Telegram verbunden?
cat /root/.hermes/profiles/hermes-news/gateway_state.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('platforms',{}).get('telegram',{}).get('state','❌'))"
```

Falls der Gateway nicht läuft: `systemctl start hermes-gateway-hermes-news.service`

### Konfiguration

Job-Struktur in der Profil-Cron-DB (`/root/.hermes/profiles/<profil>/cron/jobs.json`):

```json
{
  "id": "<hash>",            // selbst generiert (z.B. md5(name+ts)[:11])
  "name": "daily-news-briefing",
  "prompt": "...",
  "skills": ["daily-news-briefing"],
  "skill": "daily-news-briefing",
  "model": "deepseek/deepseek-v4-flash",
  "provider": "openrouter",
  "schedule": {"kind": "cron", "expr": "0 6 * * *", "display": "0 6 * * *"},
  "deliver": "telegram",       // → TELEGRAM_HOME_CHANNEL des Profil-Bots
  "state": "scheduled",
  "enabled": true,
  "repeat": {"times": null, "completed": 0},
  "no_agent": false,
  "enabled_toolsets": ["web", "terminal", "file", "browser"]
}
```

**Wichtig:** Der Skill (`daily-news-briefing`) muss auch im Profil-Verzeichnis existieren:
```bash
cp -r /root/.hermes/skills/productivity/daily-news-briefing /root/.hermes/profiles/<profil>/skills/productivity/
```

### Anlegen eines Profil-Cron-Jobs (Python)

Das `cronjob`-Tool arbeitet NUR im default Scheduler. Für Profil-Crons direkt ins JSON schreiben:

```python
import json, hashlib
from datetime import datetime, timezone, timedelta

path = "/root/.hermes/profiles/hermes-news/cron/jobs.json"
data = json.load(open(path))

job = {
    "id": hashlib.md5(f"job-name-{datetime.now().isoformat()}".encode()).hexdigest()[:11],
    "name": "daily-news-briefing",
    "prompt": "<prompt>",
    "skills": ["daily-news-briefing"],
    "model": "deepseek/deepseek-v4-flash",
    "provider": "openrouter",
    "schedule": {"kind": "cron", "expr": "0 6 * * *", "display": "0 6 * * *"},
    "enabled": True,
    "state": "scheduled",
    "deliver": "telegram",
    "repeat": {"times": None, "completed": 0},
    "no_agent": False,
    "enabled_toolsets": ["web", "terminal", "file", "browser"]
}

data["jobs"].append(job)
data["updated_at"] = datetime.now(timezone(timedelta(hours=2))).isoformat()

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, default=str)
```

Danach Gateway neustarten (falls nötig — der Scheduler liest live):
```bash
systemctl restart hermes-gateway-<profil>
```

### ⚠️ Default Scheduler + profile-Routing (aktueller Stand)

Der Job (id `769f3356b8d1`) läuft aktuell im default Scheduler mit
`profile: hermes-news` und `deliver: telegram`. Das deliver geht zum
TELEGRAM_HOME_CHANNEL des Scheduler-Bots (default), nicht des Profil-Bots.

**Wenn Delivery im DM statt im News-Channel ankommt:** Job ins Profil
migrieren (siehe §Migration unten).

### ✅ Alternative: Job direkt in Profil-Cron-DB (empfohlen für Channel-Delivery)

Soll das Briefing im News-Channel (Ch_hermster_news) landen, MUSS der Job
im hermes-news Profil-Scheduler leben. Anlegen via Python:

### Migration: Job aus default Scheduler → Profil-Scheduler

Wenn der Job noch im default Scheduler läuft und in den Profil-Scheduler umziehen soll:

1. **Job im default Scheduler löschen:**
   ```
   hermes cron remove <job-id>
   ```

2. **Skill ins Profil kopieren:**
   ```bash
   cp -r /root/.hermes/skills/productivity/daily-news-briefing /root/.hermes/profiles/<profil>/skills/productivity/
   ```

3. **Profil-Gateway prüfen (muss laufen):**
   ```bash
   cat /root/.hermes/profiles/<profil>/gateway_state.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('✅' if d.get('gateway_state')=='running' else '❌')"
   ```
   Falls nicht: `systemctl start hermes-gateway-<profil>.service`

4. **Job in Profil-Cron-DB anlegen** (siehe Python-Snippet unter "Anlegen eines Profil-Cron-Jobs").

### ⚠️ Bekanntes Problem: cron_health.py false-positives

Der `cron_health.py` Check (Job `cron-health-daily`) kann ❌ für Jobs melden,
die parallel zu ihm laufen. Der Health-Check liest `cron.log` und markiert einen Job
als "crashed" wenn sein Log-Block ein `START` aber noch kein `DONE/✅` enthält.

**Betroffen:** Jobs die zur gleichen Minute wie der Health-Check starten (08:00)
und länger als ein paar Sekunden brauchen.

**Diagnose:** Im Dashboard oder per `grep` prüfen ob der betreffende Job
tatsächlich `✅ ... abgeschlossen` im Log hat — wenn ja, ist es ein Timing-Problem.

**Fix:** `cron-health-daily` auf 08:30 verschieben, sodass alle 08:00-Jobs
durch sind bevor er checkt.

### Verifikation

```bash
source /root/.hermes/profiles/hermes-news/.env
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_HOME_CHANNEL}" \
  -d "text=Test" | python3 -c "import json,sys; print('✅' if json.load(sys.stdin).get('ok') else '❌')"
```

### Manuelles Triggern (Profil-Kontext)

Nach Änderungen am Prompt oder Skill den nächsten scheduled Run abwarten (06:00)
oder den Gateway neustarten, damit er den Job sofort triggert:

```bash
systemctl restart hermes-gateway-hermes-news.service
```

Verifikation dass der Bot im Channel ist:
```bash
source /root/.hermes/profiles/hermes-news/.env
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_HOME_CHANNEL}" \
  -d "text=Test" | python3 -c "import json,sys; print('✅' if json.load(sys.stdin).get('ok') else '❌')"
```

### Cron Job Lebenszyklus (Profil-Cron)

Der Job lebt in `/root/.hermes/profiles/hermes-news/cron/jobs.json`.
Nach jeder Änderung am Prompt oder Skill:
1. Prompt in der Profil-`jobs.json` per Python-json.dump updaten
2. Gateway neustarten: `systemctl restart hermes-gateway-hermes-news.service`
3. Verifikation: `journalctl -u hermes-gateway-hermes-news.service --since "1 min ago"`

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
- **RECENCY FILTER — NUR Artikel der letzten 2 Tage!** Jeder RSS-Item hat ein `<pubDate>`-Element. Parse es und vergleiche mit heute. Alles älter als 2 Tage → WEGLASSEN. Keine Ausnahmen, auch wenn interessant. Google News RSS liefert immer aktuelle News — wenn der Feed Müll/Altes ausspuckt, lieber weniger Items als alte.
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

### 🔴 PREISANGABEN — Datum prüfen & validieren

Martin hat sich explizit über veraltete Preisangaben beschwert ("Gold nahe Allzeithoch").

**Pflicht-Regeln für ALLE Preis-/Kursangaben:**

1. **RSS-Artikel-Datum prüfen:** Jeder RSS-Item hat ein `<pubDate>`-Element. Extrahiere es mit Python (cron) oder prüfe per regex. Ist der Artikel älter als 2 Tage? → NICHT für aktuelle Kurse verwenden, nur für Kontext

2. **Aktuelle Kurse validieren:** Bei Preisangaben (Gold, Bitcoin, DAX, S&P 500, Öl) IMMER einen aktuellen Kurs per web_search abgleichen. Schema:
   ```
   Suche: "Goldpreis aktuell heute" oder "Bitcoin Kurs heute"
   Ergebnis: Gold bei X€ (Datum: Y) — NICHT "nahe Allzeithoch" schreiben wenn der Artikel alt ist
   ```

3. **Formulierung:** Statt "Gold auf Allzeithoch" besser "Gold notierte laut Artikel vom [Datum] bei X€ — aktuell bei Y€". Bei Unsicherheit: "heute bei X€" statt Superlative.

4. **Verboten:** Absolute Aussagen ohne zeitlichen Bezug ("Gold ist auf Allzeithoch", "Bitcoin explodiert"). Erlaubt: "Laut einem Artikel vom [Datum] lag Gold bei X€."

5. **Keine veralteten Quellen priorisieren:** "Der Aktionär" und andere Finanzblogs haben oft allgemeine Marktkommentare ohne Datumsangabe. Wenn kein Datum im Feed → lieber weglassen als veraltet zu zitieren.

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

## Cron Job Constraints (Profil-eigener Scheduler)

This job runs in the **hermes-news profile's own scheduler**, NOT the default Hermes scheduler.
Delivery goes through the **profile's own Telegram bot** to the profile's TELEGRAM_HOME_CHANNEL.

Key constraints for the agent running this cron:
- `execute_code` is **blocked** in cron mode — do not attempt it
- `web_search` / `web_extract` may fail due to Firecrawl credits — always have RSS fallback ready
- `curl | python3` pipe is **safe in terminal() calls** (non-cron runs) but blocked in cron
- In cron mode: save RSS to `/tmp/` then `read_file`
- No user interaction possible — make autonomous decisions
- Final response is auto-delivered by the profile's gateway — do NOT use `send_message` or `curl`-based Telegram API calls
- **Delivery goes to the profile's TELEGRAM_HOME_CHANNEL** via the profile's bot
- For verification after manual trigger: `source /root/.hermes/profiles/hermes-news/.env && curl -s https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage...`
- **Profile gateway must be running** for the scheduler to tick. Check via `gateway_state.json`.

### Timing Conflicts with cron_health.py

⚠️ **Der `cron_health.py` Check (Job `cron-health-daily`) kann false-positive ❌ melden**
wenn er gleichzeitig mit einem anderen Cron-Job läuft.

**Mechanismus:** `cron_health.py` liest `cron.log` und sucht nach `=== DATUM === jobname START ===`-Markern.
Für jeden gefundenen START prüft er, ob der Block ein `✅ ... abgeschlossen` oder `✅ ... DONE` enthält.
Wenn der Job noch läuft (nur START, noch kein DONE im Log), wird er als `❌ crashed` gemeldet.

**Bekannter Konflikt:** `strategy_optimizer` (Sonntag 08:00) und `cron-health-daily` (08:00)
laufen parallel. Der Optimizer braucht ~2 Minuten → Health-Check findet nur START ohne DONE.

**Fix:** Staggered Schedules — z.B. `cron-health-daily` auf `30 8 * * *` (08:30) verschieben.
Der Optimizer ist dann längst durch.

## Firecrawl Credit Exhaustion (Dauerzustand)

Firecrawl-Credits werden monatlich zurückgesetzt (aktuell: 13.7.). Dazwischen sind `web_search` und `web_extract` **nicht verfügbar**.

**Symptom:** `Firecrawl search failed: Payment Required: Insufficient credits`

**Workaround-Reihenfolge:**
1. **Exa Search** — semantische Websuche, kein Credit: `mcporter call 'exa.web_search_exa(query: "...", numResults: 5)'`
2. **Jina Reader** — Webseiten lesen, kein Credit: `curl -s "https://r.jina.ai/URL"`
3. Google News RSS per curl (funktioniert zuverlässig, keine Credits nötig)
4. Open-Meteo API für Wetter (kein API-Key, keine Credits)
5. Browser für Wassertemperaturen (wassertemperatur.org)
6. Direkte curl-Aufrufe auf andere RSS-Feeds (tagesschau.de, heise.de, welt.de)