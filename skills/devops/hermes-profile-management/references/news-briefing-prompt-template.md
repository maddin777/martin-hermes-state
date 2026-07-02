# Daily News Briefing Prompt Template (v4.3 — June 17, 2026)

Approved prompt for Martins `hermes-news` profile cron job `daily-news-briefing`.

**⚠️ Wichtig — Delivery-Bot Beachten:**
Der Job läuft **direkt im hermes-news Profil** (in `cron/jobs.json`), NICHT als Cross-Profil-Job im main Scheduler.
Die Zustellung geht über `@hermster_news_bot`, nicht über den main-Bot `@myhermster_bot`.
Siehe Pitfall #14 in `hermes-profile-management` SKILL.md für Details zum Cross-Profile Delivery Bug.

## Model Setup

| Component | Model | Provider | Notes |
|-----------|-------|----------|-------|
| **Cron (LLM)** | `deepseek/deepseek-v4-flash` | `openrouter` | Free model, handles multi-turn news research |
| **x_search API** | `grok-4.20-reasoning` | `xai-oauth` | Separately configured in config.yaml |

When xAI Grok tokens run out (HTTP 403 spending-limit): switch BOTH `model` and `provider` in the cron job to deepseek/deepseek-v4-flash. x_search stays on xai-oauth (separate config).

## Source List (stable, use in every prompt version)

**Deutsch:** Tagesschau, NZZ, Handelsblatt, Reuters, AP, DW, NDR, Ostsee-Zeitung, Welt

**International:** SVT (Schweden), DR (Dänemark), YLE (Finnland), Gazeta Wyborcza (Polen), Financial Times, Wallstreet Journal, New York Times, TechCrunch, The Verge, heise online, Golem, Table.Media

## Approved Prompt Text

```
Du bist mein News-Agent. Erstelle ein tägliches Morgen-Briefing (06:00).

═══ ARBEITSSCHRITTE (Reihenfolge einhalten) ═══

1. WEB-RECHERCHE: Nutze web_search INTENSIV für JEDE Sektion.
   Quellen (deutsch):
   Tagesschau, NZZ, Handelsblatt, Reuters, AP, DW, NDR,
   Ostsee-Zeitung, Welt
   Quellen (international):
   SVT (Schweden), DR (Dänemark), YLE (Finnland),
   Gazeta Wyborcza (Polen), Financial Times, Wallstreet Journal,
   New York Times, TechCrunch, The Verge, heise online, Golem,
   Table.Media

2. X-RECHERCHE: Nutze x_search parallel für Breaking News und
   regionale Entwicklungen. Markiere X-Quellen mit [X].

3. DEDUP: Identische Meldungen aus verschiedenen Quellen NUR EINMAL.
   Gib IMMER die Quelle(n) an.

4. ÜBERSETZUNG: ALLE News auf Deutsch — auch internationale Quellen
   (FT, WSJ, NYT, SVT, DR, YLE, Gazeta Wyborcza etc.)
   übersetzt und sinngemäß auf Deutsch wiedergeben.

═══ SEKTIONEN ═══

Pro Sektion: Top 5 Meldungen. Meldungen aus Schritt 1/2 einsortieren.

### 🌍 Politik & Internationales
Globale Politik, internationale Konflikte, EU, UN, G7/G20,
Osteuropa/USA/China

### 📈 Finanzen & Wirtschaft
Globale Märkte (DAX, Dow, Nasdaq, Nikkei, Öl, Gold, Bitcoin),
Konjunktur, Zinsen, Unternehmen. FT, WSJ, Handelsblatt priorisieren.

### 💻 IT & KI
AI-News: Modelle, Releases, Regulation. Tech: Cybersecurity, Cloud,
Halbleiter. TechCrunch, The Verge, heise, Golem priorisieren.

### 🇩🇪 Deutschland & Nordeuropa
- Bundespolitik, Wirtschaft DE
- SH + MV: Landespolitik, Kommunales
- Skandinavien (Schweden, Dänemark, Norwegen, Finnland)
  → SVT, DR, YLE als Quellen nutzen
- Polen (Politik, Wirtschaft, Außenbeziehungen)
  → Gazeta Wyborcza als Quelle nutzen

═══ WETTER & WASSER ═══

Wetter (DWD, wetter.com, wetteronline.de):
- Ratzeburg: Max/Min-Temp, Bewölkung, Niederschlags-wkt.
- Schwerin: Max/Min-Temp, Bewölkung, Niederschlags-wkt.

Wassertemperaturen (seatemperature.org, wassertemperatur.org, DWD):
- Schweriner See: XX.X °C
- Ostsee bei Lübeck/Trave: XX.X °C
- Ostsee bei Wismar: XX.X °C
- Ostsee bei Rostock/Warnemünde: XX.X °C

═══ AUSGABE ═══

- Pro News: **Überschrift** (max 10 Wörter) + 1-2 Sätze + Quellenlink
- Nüchtern, sachlich, Fakten pur
- Bei ruhiger Lage: kürzere Sektion statt „Keine Meldungen"
- Pro Telegram-Nachricht: max 3000 Zeichen
- Das Briefing DARF über bis zu 5 Telegram-Nachrichten verteilt sein
  (1-2 Sektionen pro Nachricht, Wetter+Wasser an letzter ranhängen)
- Gesamtbudget: ~15000 Zeichen
```

## Key Design Decisions

1. **Multi-section with dedup:** 4 explicit sections (Politik, Finanzen, IT/KI, Regional) with top 5 each. Dedup across all sections — identical news from different sources shown once with combined source attribution.

2. **Translation required:** Explicit step #4 — international sources MUST be translated to German. Not "can be" or "prefer" but imperative.

3. **No "nothing to report":** LLMs take the easy out when the prompt allows "nothing happened". Instead: "Bei ruhiger Lage: kürzere Sektion statt 'Keine Meldungen'".

4. **Multi-message delivery:** Up to 5 Telegram messages, 3000 chars each. Each message = 1-2 sections. Weather goes on the last message.

5. **Two-tier research:** web_search for long-form articles + x_search for breaking news and real-time regional developments. X sources marked with `[X]`.

6. **Regional weather + water temps:** Always included at the end. Water temps are saisonal (Mai–September) in practice but defined in the prompt year-round.

## Scheduler / Cron Runner Note

This cron runs under the `hermes-news` profile, NOT the main Hermes scheduler.
The job is stored directly in `/root/.hermes/profiles/hermes-news/cron/jobs.json`.

**Management (immer via Python, nie via Shell-Quote):**

```python
import json
path = '/root/.hermes/profiles/hermes-news/cron/jobs.json'
data = json.load(open(path))

# Update prompt von Job 0
data['jobs'][0]['prompt'] = """...neuer Prompt..."""

# Oder neuen Job hinzufügen
data['jobs'].append({...})

json.dump(data, open(path, 'w'), indent=2, ensure_ascii=False)
```

**Nach jeder Änderung: Gateway neustarten:**
```bash
systemctl restart hermes-gateway-hermes-news
```

**Verifikation:**
```bash
# Test Delivery via Profil-Bot
source /root/.hermes/profiles/hermes-news/.env
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_HOME_CHANNEL}" \
  -d "text=✅ Cron-Job aktiv, Delivery über Profil-Bot" \
  -d "parse_mode=Markdown"
```

**⚠️ Nicht `hermes cron create` im main-Profil verwenden** — das erzeugt einen Cross-Profil-Job,
dessen Delivery über den main-Bot geht (-> `Chat not found`). Siehe Pitfall #14 in `hermes-profile-management`.

## Manual Fallback: Briefing bei Cron-Ausfall

Wenn der Cron-Job nicht triggert (Scheduler-Tick dauert zu lange, Gateway wurde gerade neugestartet) und Martin das Briefing sofort braucht:

**Nicht:** Den vollen Prompt als `delegate_task` an einen Subagenten geben mit der Erwartung, dass der alles selbst recherchiert. Das führte zu leeren Sektions-Überschriften ohne Inhalt (der Subagent hatte keine Firecrawl-Credits und hat Browser-Scraping nicht zuverlässig hinbekommen).

**Sondern:**
1. Selbst die Rohdaten recherchieren (curl Google News RSS + Google Finanzen RSS + Open-Meteo API)
2. Die strukturierten Rohdaten (Titel, Quelle, Kurzbeschreibung) dem Subagenten übergeben
3. Subagent bekommt klare Anweisung: aus diesen Daten das Briefing schreiben + per Telegram-API senden (curl mit Bot-Token aus source .env)
4. Klarstellen: KEINE leeren Überschriften, JEDE Section muss Inhalt haben

**Sendekommando für Telegram (per terminal im Subagenten):**
```bash
source /root/.hermes/profiles/hermes-news/.env
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_HOME_CHANNEL}" \
  -d "text=NACHRICHT" \
  -d "parse_mode=Markdown"
```

**API-Fallback-Recherche (wenn Firecrawl/web_search keine Credits):**
```bash
# Deutsche Top-News via Google News RSS
curl -s "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de"

# Nach Kategorie
curl -s "https://news.google.com/rss/search?q=KI+Artificial+Intelligence+Tech&hl=de&gl=DE&ceid=DE:de"

# Wetter Open-Meteo (kostenlos, kein Key)
curl -s "https://api.open-meteo.com/v1/forecast?latitude=53.70&longitude=10.75&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto"

# Wassertemperaturen via Browser auf wassertemperatur.org (nur browser_navigate + snapshot)
```

## Prompt Update History

| Date | Version | Key Change |
|------|---------|------------|
| 2026-04-22 | v1 | Initial, generic RSS summary |
| 2026-05-24 | v2 | Added local events, water temps, removed "nothing to report" |
| 2026-06-14 | v3 | Full multi-section rewrite, 4 explicit sections, dedup, translation, 5-message delivery, source list expanded |
| 2026-06-17 | v4 | **Delivery-Fix:** Job moved from main-scheduler (`profile: hermes-news`) to direct profile `cron/jobs.json`. Delivery now uses `@hermster_news_bot` instead of `@myhermster_bot`. |
| 2026-06-17 | v4.3 | **Manual Fallback:** Added section for ad-hoc briefing execution when cron doesn't fire. Includes pre-researched-data delegation pattern (avoiding empty output) and API-fallback curl commands for Firecrawl-less scenarios. |