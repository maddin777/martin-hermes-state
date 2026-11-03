# Search / extraction fallback ladder

Order matters: cheap and deterministic first, expensive agentic browsing last. Every step
must be recorded as "answered by <step>", so a later reader can judge reliability.

## Ladder

| # | Step | When | Command shape |
|---|------|------|---------------|
| 1 | `web_search` / `web_extract` | normal case | tool call |
| 2 | Exa semantic search (MCP) | `web_search` fails or needs semantic recall | `mcporter call 'exa.web_search_exa(query: "...", numResults: 5)'` |
| 3 | Jina Reader | need the text of one URL, no JS | `curl -s "https://r.jina.ai/<full-url>"` |
| 4 | Google News RSS | current news, no credits | `curl -s "https://news.google.com/rss/search?q=<terms>&hl=de&gl=DE&ceid=DE:de"` |
| 5 | Site feed / sitemap | site blocks scraping | `<site>/rss`, `<site>/feed`, `<site>/sitemap.xml` |
| 6 | Wikipedia API | definitions, background, tables | `action=query&prop=extracts&explaintext=1` (plain text) or `action=parse` (HTML) |
| 7 | DDGS-backed search | plain keyword lookups | `web_search` already routes here when Firecrawl is unavailable |
| 8 | Browser automation | login wall, JS-only render | `browser_navigate` + `browser_snapshot(full=True)` |

## Known failure modes

- **`Insufficient credits` / `Payment Required`** — Firecrawl quota exhausted; quota resets monthly, so long dead windows are normal. Do not retry the same call; go to step 2.
- **`api.github.com` rate limit** — unauthenticated is 60 req/h; use `gh api` with auth instead of raw curl.
- **Paywall** — reader proxy (step 3) often returns the lede only. If the number you need is behind the paywall, take it from a second outlet and say so.
- **RSS returns stale items** — Google News and some sites keep old items in the feed. Filter on `pubDate` before use; never present an old item as current.
- **Empty extraction on JS apps** — Reader returns navigation chrome only; escalate to browser automation or find the underlying JSON endpoint.
- **Charset** — `urlopen()` yields `bytes`; decode with `.decode("utf-8", "replace")` before parsing, and use `.replace(tzinfo=None)` when comparing RSS dates to `datetime.now()` (RSS dates are naive).
- **HTML to text** — strip `script`/`style` before extracting text, or the output is mostly code.

## Verification

- A URL counts as read only if you got content (title + at least one body sentence).
- For numbers (prices, counts, dates), confirm with a second independent source or label it single-sourced.
