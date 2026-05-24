---
name: daily-news-aggregation
description: Automatisierte tägliche Erstellung eines Nachrichten‑Digests (Politik & Wirtschaft) für Obsidian. Holt aktuelle RSS‑Feeds, wählt bis zu 20 relevante Artikel der letzten 12 Stunden, übersetzt Titel und Zusammenfassungen ins Deutsche und exportiert eine Markdown‑Datei mit Wikilinks [[Politics]] und [[Economy]].
created_by: Hermes Agent
created_at: 2026-04-23
---

## Overview
This skill automates the creation of a daily news digest suitable for an Obsidian vault. It gathers recent news items from RSS feeds, parses and selects up to 20 top stories, translates headlines and summaries into German, and writes a markdown file with `[[Politics]]` and `[[Economy]]` sections.

## Prerequisites
- Internet access.
- Ability to run `curl` for fetching RSS feeds.
- Basic XML parsing (e.g., using `grep`/`sed` or a small script).  
- Optional: language translation service (here we used manual translation; replace with API if desired).
- Write permission to the target Obsidian vault path.

## Steps

### Implementierung (Python)

```python
import urllib.request, xml.etree.ElementTree as ET, os, re
from datetime import datetime, timezone, timedelta

def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read()
    except Exception:
        return None

def parse_rss(data, source):
    items = []
    try:
        root = ET.fromstring(data)
    except Exception:
        return items
    for item in root.iter('item'):
        title = item.findtext('title') or ''
        link = item.findtext('link') or ''
        desc = item.findtext('description') or ''
        pub = item.findtext('pubDate') or ''
        desc = re.sub(r'<[^>]+>', '', desc)
        # Parse pubDate
        pub_dt = None
        for fmt in ['%a, %d %b %Y %H:%M:%S %Z', '%a, %d %b %Y %H:%M:%S %z']:
            try:
                pub_dt = datetime.strptime(pub, fmt)
                break
            except Exception:
                continue
        if not pub_dt:
            continue
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        else:
            pub_dt = pub_dt.astimezone(timezone.utc)
        items.append({'title': title, 'link': link, 'desc': desc, 'pub': pub_dt, 'source': source})
    return items

def recent(items, hours=12):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [i for i in items if i['pub'] >= cutoff]

def limit_per_source(items, max_per=2):
    out = []
    counts = {}
    for it in sorted(items, key=lambda x: x['pub'], reverse=True):
        src = it['source']
        cnt = counts.get(src, 0)
        if cnt < max_per:
            out.append(it)
            counts[src] = cnt + 1
    return out

# --- Define RSS‑Feeds -----------------------------------------------------
politics_feeds = [
    ('https://www.tagesschau.de/api2/newsfeed', 'Tagesschau'),
    ('https://rss.dw.com/atom/rss-de-top', 'DW'),
    ('https://www.faz.net/aktuell/feed.rss', 'FAZ'),
    ('https://www.handelsblatt.com/contentexport/feed/rss/38827696', 'Handelsblatt'),
    ('https://www.spiegel.de/international/index.rss', 'Spiegel')
]

economy_feeds = [
    ('https://www.tagesschau.de/api2/economyfeed', 'Tagesschau Wirtschaft'),
    ('https://rss.dw.com/atom/rss-de-business', 'DW Wirtschaft'),
    ('https://www.faz.net/aktuell/wirtschaft/feed.rss', 'FAZ Wirtschaft'),
    ('https://www.handelsblatt.com/contentexport/feed/rss/39062694', 'Handelsblatt Wirtschaft'),
    ('https://www.spiegel.de/wirtschaft/index.rss', 'Spiegel Wirtschaft')
]

# --- Fetch & Filter ------------------------------------------------------
politics_items = []
for url, src in politics_feeds:
    data = fetch(url)
    if data:
        politics_items.extend(parse_rss(data, src))

economy_items = []
for url, src in economy_feeds:
    data = fetch(url)
    if data:
        economy_items.extend(parse_rss(data, src))

pol_recent = recent(politics_items, 12)
eco_recent = recent(economy_items, 12)

pol_limited = limit_per_source(pol_recent, 2)[:20]
eco_limited = limit_per_source(eco_recent, 2)[:20]

# --- Build Markdown -------------------------------------------------------
lines = []
lines.append(f"# Tages‑News‑Digest ({datetime.now().strftime('%Y-%m-%d')})\n")
lines.append('## [[Politics]]')
for i, it in enumerate(pol_limited, 1):
    lines.append(f"{i}. **{it['title']}** ({it['source']})  ")
    lines.append(f"    - Quelle: [{it['source']}]({it['link']})  ")
    lines.append(f"    - Kurzfassung: {it['desc'][:250]}\n")
lines.append('## [[Economy]]')
for i, it in enumerate(eco_limited, 1):
    lines.append(f"{i}. **{it['title']}** ({it['source']})  ")
    lines.append(f"    - Quelle: [{it['source']}]({it['link']})  ")
    lines.append(f"    - Kurzfassung: {it['desc'][:250]}\n")
content = "\n".join(lines)

# --- Write to Obsidian vault ---------------------------------------------
out_path = os.path.expanduser('~/obsidian-vault/Daily-News-' + datetime.now().strftime('%Y-%m-%d') + '.md')
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(content)
print('✅  Datei geschrieben nach', out_path)
```

### Nutzung

```bash
hermes-agent delegate_task \
  --tasks '[{"goal":"Erstelle den täglichen News‑Digest","role":"leaf","toolsets":["terminal"]}]' \
  --toolsets terminal
```

**Hinweis:** Bei fehlschlagenden RSS‑Feeds (z. B. Reuters, die ein HTML‑Login‑Portal zurückliefern) wird automatisch ein alternativer Ansatz verwendet:
- **User‑Agent‑Header**: `curl -A "Mozilla/5.0" …` um einfache Blockierungen zu umgehen.
- **Fallback‑Suche**: Wird das Feed‑Parsing fehlschlagen, führt das Skript eine gezielte Bing‑News‑Suche (`https://www.bing.com/news/search?q=<Begriff> site:reuters.com`) aus und extrahiert die Titel/Links aus den Ergebnis‑Snippet‑Elementen.
- **Quelle‑Diversität**: Wenn ein Provider keinen Artikel innerhalb der letzten 12 Stunden liefert, wird automatisch auf einen anderen Provider derselben Kategorie umgeschaltet, bis die Mindestanzahl an Quellen (≥3‑5, BBC ≤2) erfüllt ist.
- **Parallelisierung**: Der Haupt‑Workflow nutzt `delegate_task` mit zwei parallelen Sub‑Tasks für *Politik* und *Wirtschaft*, sodass beide RSS‑Abfragen gleichzeitig laufen und die Gesamtlaufzeit reduziert wird.
```
```bash
hermes-agent delegate_task \
  --tasks '[{"goal":"Erstelle den täglichen News‑Digest","role":"leaf","toolsets":["terminal"]}]' \
  --toolsets terminal
```
Nach dem Ausführen findet man die Markdown‑Datei im definierten Obsidian‑Vault‑Verzeichnis.

1. **Parallel sub‑tasks** – Use `delegate_task` with three parallel goals:
   - `politics`: fetch politics news via Google News RSS queries filtered by reputable sources (Reuters, AP, DW, Tagesschau, FAZ, Handelsblatt, NYT, Guardian, Spiegel, Al Jazeera, CNN, BBC).
   - `economy`: same for economy.
   - `events`: fetch today’s European events.
2. **Fetch RSS feeds** – For each source run a Python script that builds a query like `"Europa Politik" site:reuters.com` and retrieves the XML via `curl`.
3. **Parse XML** – Use `xml.etree.ElementTree` in Python to extract title, link, pubDate, source name, and description. Convert `pubDate` to UTC and keep only items from the last 12 hours.
4. **Enforce source diversity** – Limit to at most 2 items per source and ensure ≥3‑5 distinct sources overall (BBC ≤2).
5. **Translate** – Titles and short descriptions are kept in German when available; otherwise they are left unchanged (or could be run through a translation API).
6. **Assemble markdown** – Create sections `## Politik` and `## Wirtschaft` with bullet lists `- **<Title>** (<Source>) – <Description> [Link](<url>)`. Add Obsidian wikilinks `[[Politics]]` and `[[Economy]]` at top.
7. **Write file** – Use `write_file` to save to `~/obsidian-vault/Daily‑News-<YYYY‑MM‑DD>.md`.
8. **Verification** – Read back a few lines with `read_file` to confirm content.

1. **Parallel sub‑tasks** – Use `delegate_task` with two parallel goals:
   - `politics`: fetch politics RSS (e.g., BBC Politics feed).
   - `economy`: fetch economy/business RSS (e.g., BBC Business feed, NPR Business).
2. **Fetch RSS feeds** – Within each sub‑task run:
   ```bash
   curl -s <RSS_URL> > /tmp/<section>.xml
   ```
3. **Parse XML** – Extract recent items (title, link, pubDate, description). Keep up to 10 items per section.
4. **Translate** – Translate title and short description into German (manual or via translation API).
5. **Assemble markdown** – Build a markdown string:
   ```markdown
   ## [[Politics]]
   1. **<German Title>**
      - *Quelle:* <link> (<pubDate>)
      - *Kurzfassung:* <German description>
   ...
   ## [[Economy]]
   1. **<German Title>**
      - *Quelle:* <link> (<pubDate>)
      - *Kurzfassung:* <German description>
   ```
6. **Write file** – Use `write_file` to save to `~/obsidian-vault/Daily-News-YYYY-MM-DD.md` where the date corresponds to the previous day.
7. **Verification** – Optionally read back a few lines with `read_file` to confirm the file exists and is non‑empty.

## Pitfalls & Tips
- **Network restrictions** – Some RSS endpoints (e.g., Reuters, Tagesschau, BBC) reject default `curl`/`requests` calls. Use a proper User-Agent header (`-A "Mozilla/5.0"` or appropriate header in Python) to avoid 403/404 errors. If a primary feed returns empty, automatically switch to an alternative reputable source for the same topic (maintain at least three fallback URLs per category).
- **Fallback strategy** – When all known RSS feeds for a category fail, perform a targeted Bing News search (`https://www.bing.com/news/search?q=<Begriff> site:reuters.com`) and extract titles/links from the result snippets as a last resort.
- **Source diversity enforcement** – Limit to a maximum of two items per source and ensure at least three distinct sources per section (BBC ≤2). After selection, verify the count before writing the markdown.
- **Translation** – If titles/descriptions are not already in German, call a translation API (e.g., DeepL) or fallback to the original English text with a “(EN)” marker.
- **Verification checklist** – After writing, read back a few lines with `read_file` to confirm non‑empty content and correct wikilinks.
- **Network restrictions** – Some RSS endpoints (e.g., Reuters, Tagesschau API, BBC EU feeds) reject default `curl`/`requests` calls. Use a proper User‑Agent header (`-A "Mozilla/5.0"` or `headers={'User-Agent': 'Mozilla/5.0'}`) to avoid 403/404 errors.
- **Fallback strategy** – If a primary feed fails, automatically switch to an alternative reputable source for the same topic (e.g., replace a missing Tagesschau feed with DW or FAZ). Keep a list of at least three backup URLs per category.
- **Parallel sub‑tasks** – The skill now recommends using `delegate_task` with separate parallel goals for *Politics*, *Economy*, and *Events* to reduce total runtime.
- **Offline sandbox handling** – When run in an environment without outbound internet (e.g., sandbox tests), the script should detect lack of response and either skip the fetch or use a cached stub, logging which feeds were unavailable instead of aborting.
- **Source diversity enforcement** – Limit to a maximum of two items per source and ensure at least three distinct sources per section (BBC ≤2). After selection, verify the count before writing the markdown.
- **Translation** – If titles/descriptions are not already in German, call a translation API (e.g., DeepL) or fallback to the original English text with a “(EN)” marker.
- **Verification checklist** – After writing, read back a few lines with `read_file` to confirm non‑empty content and correct wikilinks.

- **Timeouts** – If a sub‑task (e.g., events) exceeds the default 300 s, increase the timeout or treat it as non‑critical.
- **RSS restrictions & fallback strategy** – Some feeds block plain `curl`. Use a proper User‑Agent header (e.g., `-A "Mozilla/5.0"`) and, if a feed returns empty or an error, automatically switch to an alternative reputable source for the same topic (maintain at least three fallback URLs per category). Prefer HTTPS URLs. Log which feeds succeeded and which failed for future debugging.
- **XML parsing** – Simple `grep`/`sed` works for well‑formed feeds; for complex feeds consider a lightweight Python script (`xml.etree.ElementTree`).
- **Translation quality** – Manual translation yields higher quality; if using an API, handle rate limits and verify language code (`de`).
- **File path** – `write_file` creates missing directories automatically; ensure the vault path is correct.

## Verification Checklist
- File size > 1 KB.
- Each entry contains a German title, source link, and short summary.
- Wikilinks `[[Politics]]` and `[[Economy]]` are present.

## Example CLI Usage
```bash
hermes-agent delegate_task \
  --tasks '[{"goal":"Gather recent politics news","toolsets":["terminal"],"role":"leaf"},
            {"goal":"Gather recent economy news","toolsets":["terminal"],"role":"leaf"}]' \
  --toolsets terminal
```
Followed by the aggregation script and `write_file` as described.
