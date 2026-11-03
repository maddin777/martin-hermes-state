# Feed monitoring notes

## Parsing

```python
import xml.etree.ElementTree as ET
root = ET.fromstring(body)                      # bytes are fine
for item in root.findall(".//item"):            # RSS
    title = (item.findtext("title") or "").strip()
    date  = (item.findtext("pubDate") or "").strip()
    link  = (item.findtext("link") or "").strip()
    src   = item.findtext("source")             # Google News only
```

Atom differs: `root.findall(".//{http://www.w3.org/2005/Atom}entry")`, `title`, `updated`,
`link[@rel=alternate]/@href`, `summary`.

## Freshness

- Parse `pubDate` with `email.utils.parsedate_to_datetime` (handles RFC 822) and compare against `datetime.now(timezone.utc)`.
- Missing date → treat as unknown, not as fresh. Unknown-date items do not fill a section that requires "today".
- Apply the window (`-2d`, `-7d`, `-30d`) *before* summarizing, never after.

## Feed hygiene

- Dedup by normalized title (lowercase, strip punctuation/outlet suffix ` - Reuters`), then merge duplicates into one item listing all outlets.
- Google News item titles carry `"Headline - Outlet"`; split on the last ` - ` to recover the outlet.
- Cap per feed (e.g. 10) and per section (e.g. 5) so one noisy feed cannot dominate.
- Feeds that 404/redirect: `curl -sL` and check the final URL; a redirect to an HTML page means the feed is gone.
- Keep a persisted marker of reported URLs/titles when the run is recurring (see `hermes-profile-ops` change-detection marker rule) — otherwise duplicates every cycle.

## Known-good public feeds

- Google News DE: `https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de`
- Google News topic search: `https://news.google.com/rss/search?q=<terms>&hl=de&gl=DE&ceid=DE:de`
- Weather (no key): `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto`
- arXiv: `http://export.arxiv.org/api/query?search_query=...`

Site feeds (tagesschau, heise, golem, welt, NDR, Ostsee-Zeitung) change paths periodically —
probe `<domain>/rss` and `<domain>/feed` before assuming a feed is dead.
