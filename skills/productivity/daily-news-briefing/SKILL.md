---
name: daily-news-briefing
description: "Create structured daily morning briefings (Morgen-Briefing) in German from multiple news sources via RSS feeds, weather APIs, and browser fallback. Handles web_search/web_extract failures gracefully. Designed for profile-cron delivery (profil-eigener Bot)."
version: 1.2.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [news, briefing, rss, cron, german, morning, weather]
    related_skills: [research-tools, idea-scout-pipelines, hermes-profile-ops]
    schedule: "0 6 * * *"
---

# Daily News Briefing (Morgen-Briefing)

Structured German-language morning briefing from RSS feeds, weather and water temperatures,
delivered by a **profile cron job** (profil-eigener Bot).

## When to Use

- "Morgen-Briefing", daily news digest, the `daily-news-briefing` cron job
- Changing sections, sources or delivery target of the briefing
- Diagnosing an empty, duplicated or stale briefing run

## Output Format

Max 5 items per section:

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

## Delivery Model

Runs in the **hermes-news profile scheduler** (job `46acda532f8`), not the default Hermes
scheduler; the job lives in `/root/.hermes/profiles/hermes-news/cron/jobs.json`. Model
`deepseek/deepseek-v4-flash` via OpenRouter, `deliver: telegram` → the profile bot
(@hermster_news_bot) into `TELEGRAM_HOME_CHANNEL` (`-1003687061880`, News-Channel).

Job mechanics — creating/migrating the job, the duplicate-job check across both schedulers,
toolset-vs-prompt rules, proof that a run happened, gateway deadlocks — are in
`hermes-profile-ops` → `references/profile-cron-jobs.md`. Never keep the job in both
schedulers: two jobs means two deliveries with different models and prompts. The packaged
checker `scripts/check_duplicate_jobs.py` greps both schedulers and warns on duplicates.

- The profile gateway must be running or the scheduler does not tick:
  `systemctl start hermes-gateway-hermes-news.service`; check `gateway_state.json`
  (`gateway_state == "running"`, `platforms.telegram.state`).
- The skill must also exist inside the profile (`<profil>/skills/`); re-copy after edits.
- `enabled_toolsets` must match the prompt: the agent fetches nothing itself, so `terminal`
  and `file` do not belong in the toolset. With them present the run ends in path-search
  loops and an answer that starts with "I stopped retrying…".

## Pre-Run Data Gathering (verified cron path)

`scripts/gather_briefing_data.py` fetches news (2-day filter), weather and water temperatures
BEFORE the agent run; its stdout lands in the prompt and the agent only formats.

1. Copy the script into the profile (`<profil>/scripts/gather_briefing_data.py`).
2. Attach by filename: `hermes-<profil> cron edit <job_id> --script gather_briefing_data.py`.
3. The prompt must state: data is above, no terminal commands, no file reads/searches, no
   `send_message`/curl to Telegram (the gateway delivers the final answer itself).
4. Run it once by hand (`python3 scripts/gather_briefing_data.py`) and inspect the output.

**Script rules:** a feed with no article from the last 2 days prints "keine Artikel" — never
fall back to older items. Two silent breakers: `urlopen` returns `bytes` (decode before
parsing) and RSS `pubDate` is naive (`.replace(tzinfo=None)` on both sides before comparing).

## Workflow (manual run)

1. `web_search` / `web_extract` first.
2. If they fail (Firecrawl credits exhausted), use the fallback ladder documented in the
   `research-tools` skill — Exa, Jina Reader, Google News RSS via curl, Wikipedia API, DDGS.
3. Google News RSS is the reliable base:
   ```bash
   curl -s "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de"
   curl -s "https://news.google.com/rss/search?q=DAX+%C3%96l+Gold+Bitcoin+B%C3%B6rse&hl=de&gl=DE&ceid=DE:de"
   curl -s "https://news.google.com/rss/search?q=KI+Artificial+Intelligence+Tech+heise+golem&hl=de&gl=DE&ceid=DE:de"
   curl -s "https://news.google.com/rss/search?q=Schleswig-Holstein+Mecklenburg-Vorpommern+Norddeutschland&hl=de&gl=DE&ceid=DE:de"
   ```
   Working feeds: `references/rss-feeds-and-cron-pitfalls.md`.
4. Weather, no API key:
   ```bash
   curl -s "https://api.open-meteo.com/v1/forecast?latitude=53.70&longitude=10.75&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto"
   curl -s "https://api.open-meteo.com/v1/forecast?latitude=53.63&longitude=11.41&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto"
   ```
5. Water temperatures have no free API: browser on wassertemperatur.org (Ostsee Lübeck /
   Wismar / Rostock, Schweriner See) or seatemperature.org. Open-Meteo air temperature is NOT
   water temperature.
6. Dedup, categorize, translate to German, assemble.

**Recency filter — only items from the last 2 days.** Parse `<pubDate>` and drop everything
older, without exceptions. Google News always carries current items; fewer fresh items beat
stale ones.

## Quality Rules

- **No empty headings or sections.** Martin complained explicitly. If a section is thin, give
  its 1-2 most relevant items anyway — never "Keine Meldungen" or "Ruhiger Tag".
- Every item gets 1-2 sentences of substance and names its source ("laut Tagesschau/Reuters");
  translated sources (FT, WSJ, NYT, SVT, DR, YLE, Gazeta Wyborcza) are rendered in German.
- Factual, dry, no marketing tone.
- **Telegram length:** ~3000 characters per message, split into up to 5 messages
  (Politik+Finanzen, IT/KI+Deutschland, Wetter/Wasser).

### Price and market figures

1. **Check the article date.** Older than 2 days → context only, not a current price.
2. **Validate every price with a current lookup** (Gold, Bitcoin, DAX, S&P 500, oil).
3. Write "laut Artikel vom [Datum] bei X€ — aktuell Y€"; no unanchored superlatives.
4. Forbidden: "Gold ist auf Allzeithoch", "Bitcoin explodiert".
5. Finance blogs without a feed date ("Der Aktionär") are dropped rather than cited as current.

## Source Priority

| Section | Priority sources |
|---------|------------------|
| Politik & Internationales | Tagesschau, NZZ, Handelsblatt, Reuters, AP, DW, NDR, Ostsee-Zeitung, Welt, SVT, DR, YLE, Gazeta Wyborcza, FT, WSJ, NYT |
| Finanzen & Wirtschaft | FT, WSJ, Handelsblatt, Manager Magazin, WirtschaftsWoche, Finanzen.net, tagesschau Marktbericht |
| IT & KI | TechCrunch, The Verge, heise online, Golem, Table.Media |
| Deutschland & Nordeuropa | NDR, Ostsee-Zeitung, Welt, Nordkurier, SVT, DR, YLE, Gazeta Wyborcza |
| Wetter & Wasser | Open-Meteo (air), wassertemperatur.org / seatemperature.org (water) |

## Cron Constraints

- `execute_code` is blocked in cron mode; terminal commands with an interpreter flag
  (`python -c`, heredoc) are blocked too. Data comes from the pre-run script.
- `web_search` / `web_extract` may fail (Firecrawl credits) — the RSS fallback must be ready.
- No user interaction: decide autonomously. The final answer is auto-delivered — do not
  `send_message` or curl Telegram from inside the job.
- Prompt changes: write via Python `json.dump(ensure_ascii=False)`, back up `jobs.json`, and
  assert the new prompt is non-empty before writing.

## Cron Error Patterns

- **`last_status: ok` does not mean content arrived.** Check `deliveries.db` →
  `length(content)`; 0 or a bare skeleton = empty run. `errors.log` shows why.
- `Reasoning-only clean stop` → the reasoning model ends without a visible answer → empty
  delivery. Mitigation: disable reasoning for the job or change the model.
- `BLOCKED: Command flagged as dangerous` → interpreter-flagged terminal command in cron;
  use the pre-run script.
- `Upstream error ... Output data may contain inappropriate content` (provider filter) →
  transient; re-run after a few minutes. Not a gateway fault while the gateway is active and
  delivery is `delivered`.
- **Telegram MarkdownV2 breaks on `(` in source parentheses** (`Can't parse entities`) → the
  gateway falls back to plain text and delivery still works; cosmetic only. Switching to
  `— Quelle` is NOT verified — do not present it as a fix.
- **Abort with a status message instead of a briefing** (`I stopped retrying…`, delivered
  length ~0): the log shows `read_file` errors on directories or non-existent files. Cause is
  a file tool in the toolset, not the script. Fix toolset and prompt, then re-run.
- Cron-health false alarms (timing overlap, the `✅ ... DONE` marker format) are covered in
  `hermes-profile-ops`.

## Subagent Delegation (manual runs)

Do: hand over structured raw data (finished RSS lists, finished weather numbers), the explicit
instruction to deliver, and the full send command. Don't: let the subagent research on its own
— Firecrawl credits are often empty and the result is empty headings.
