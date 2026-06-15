# Daily News Briefing Prompt Template (v4.2 — June 14, 2026)

Approved prompt for Martins `hermes-news` profile cron job `daily-news-briefing` (999fe77b345a).

## Model Setup

| Component | Model | Provider | Notes |
|-----------|-------|----------|-------|
| **Cron (LLM)** | `openrouter/owl-alpha` | `openrouter` | Free model, handles multi-turn news research |
| **x_search API** | `grok-4.20-reasoning` | `xai-oauth` | Separately configured in config.yaml |

When xAI Grok tokens run out (HTTP 403 spending-limit): switch BOTH `model` and `provider` in the cron job to openrouter/owl-alpha. x_search stays on xai-oauth (separate config).

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

This cron runs under the `hermes-news` profile, NOT the main Hermes scheduler. Management commands:

```bash
# List
hermes --profile hermes-news cron list

# Update (via Python, never shell)
python3 -c "
import json
path = '/root/.hermes/profiles/hermes-news/cron/jobs.json'
data = json.load(open(path))
data['jobs'][0]['prompt'] = new_text
json.dump(data, open(path, 'w'), indent=2, ensure_ascii=False)
"

# Trigger test run
hermes --profile hermes-news cron run 999fe77b345a

# Gateway restart needed after jobs.json change
systemctl restart hermes-gateway-hermes-news
```

**Warning:** `hermes cron run` schedules for the next scheduler tick — it does NOT execute immediately after a gateway restart. The old gateway may have cached `jobs.json` in memory. After restart + `cron run`, wait for the next scheduled run (06:00) or verify via `journalctl`.

## Prompt Update History

| Date | Version | Key Change |
|------|---------|------------|
| 2026-04-22 | v1 | Initial, generic RSS summary |
| 2026-05-24 | v2 | Added local events, water temps, removed "nothing to report" |
| 2026-06-14 | v3 (this) | Full multi-section rewrite, 4 explicit sections, dedup, translation, 5-message delivery, source list expanded |