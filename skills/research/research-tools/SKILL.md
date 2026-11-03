---
name: research-tools
description: "Web research: search fallbacks, papers, feeds, citations."
trigger:
  - "Research papers / arXiv"
  - "Monitor competitors / news"
  - "Grounded citations"
  - "web_search or web_extract failing"
  - "Firecrawl credits exhausted"
---

# Research Tools

Class-level skill for getting information INTO a session and proving where it came from: search fallbacks, paper lookup, feed monitoring, and citation grounding.

## Always-on rules

1. **Search is a ladder, not one tool.** Try the cheapest source that can answer, and say which one you used. Full ladder and failure modes: `references/web-extraction-fallback.md`.
2. **Never invent a source.** If no reachable source confirms a claim, report the gap. A cited-but-unreachable URL is worse than "not verified".
3. **Every factual claim carries its provenance** — publisher + date, not just a link. Undated finance/market commentary is not evidence for a current number (see `daily-news-briefing` price rules).
4. **Freshness filter before content.** Parse the feed/article date and drop anything outside the requested window; do not silently fall back to older items.
5. **Quote, don't paraphrase, when the wording matters** (regulation, API contract, competitor pricing) and keep the quote short.
6. **Batch reads over per-item fetches.** One `web_extract` with N URLs, or one feed fetch parsed locally, beats N sequential calls.

## Web search and extraction

- Default `web_search` / `web_extract` when credits exist.
- When they fail (`Insufficient credits`, paywall, JS-only page), switch down the ladder in `references/web-extraction-fallback.md` — Exa semantic search, Jina Reader, direct RSS, Wikipedia API, DDGS.
- Blocked/paywalled page: try the reader proxy, then the site's RSS/AMP/print variant, then an alternative outlet covering the same event. Record that the primary source was unreachable.

## Papers and citations

- **arXiv**: `http://export.arxiv.org/api/query?search_query=all:<terms>&start=0&max_results=20` → Atom XML (`entry/id`, `title`, `summary`, `published`, `author/name`). Use `cat:cs.LG` style field queries for category-scoped searches.
- **Semantic Scholar** for impact and related work: `https://api.semanticscholar.org/graph/v1/paper/search?query=<q>&fields=title,year,abstract,citationCount,externalIds,url`. Unauthenticated calls are rate-limited — back off, don't retry in a tight loop.
- **Crossref** for DOI/metadata verification: `https://api.crossref.org/works?query.bibliographic=<ref>`.
- Verify a citation by resolving its DOI/arXiv id before citing it. A plausible-looking author+year is not a source.
- Report the exact version/date of a paper you rely on; preprints change.

## Monitoring named entities (companies, competitors, topics)

Workflow for "tell me when X does something material":

1. Build the query list once (entity name + product line + legal name variants), not one query per run.
2. Pull Google News RSS `https://news.google.com/rss/search?q=<query>&hl=de&gl=DE&ceid=DE:de` and the entity's own newsroom/IR RSS; parse `pubDate`.
3. Dedup by normalized title, then by story (same event across outlets → one item, all sources).
4. Score materiality (funding, M&A, product launch, leadership, litigation) and drop commentary/opinion pieces.
5. Persist a marker of what was already reported (see the change-detection marker rule in `hermes-profile-ops`), otherwise every run re-reports the same items.
6. Deliverable = dated list with source per item; no "no news" padding.

## Feed monitoring (RSS/Atom)

- `curl -s <feed>` then parse with `xml.etree.ElementTree`; RSS is `rss/channel/item`, Atom is `feed/entry` with `updated` instead of `pubDate`.
- Feed-specific quirks (redirects, missing dates, truncated content) and a known-working feed list: `references/monitoring-feeds.md`.
- Always cap items and apply the freshness window *before* summarizing.

## Related skills

- `daily-news-briefing` — German morning digest built on these sources.
- `idea-scout-pipelines` — recurring source-scan → scored idea pipelines.
- `obsidian` — where research output gets filed (wikilinks, MOC, LLM-wiki pattern).
