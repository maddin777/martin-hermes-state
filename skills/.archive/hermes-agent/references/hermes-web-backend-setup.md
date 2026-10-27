# Hermes Web Backend Setup

Configuration of web search and extraction backends for Hermes.

## Background

Hermes `web` toolset (`web_search_tool`, `web_extract_tool`, `web_crawl_tool`) supports multiple backends for search + extraction. Each backend needs specific env vars.

## Backend Matrix

| Backend | Search | Extract | Crawl | Auth Method | Free? |
|---------|--------|---------|-------|-------------|-------|
| `ddgs` (DuckDuckGo) | ✅ | ❌ | ❌ | `pip install ddgs` | ✅ Free |
| `brave-free` | ✅ | ❌ | ❌ | `BRAVE_SEARCH_API_KEY` | ✅ Free tier |
| `searxng` | ✅ | ❌ | ❌ | `SEARXNG_URL` (self-hosted) | ✅ Free |
| `firecrawl` | ✅ | ✅ | ✅ | `FIRECRAWL_API_KEY` or `FIRECRAWL_API_URL` | ⚠️ Freemium |
| `tavily` | ✅ | ✅ | ✅ | `TAVILY_API_KEY` | ⚠️ Freemium |
| `exa` | ✅ | ✅ | ❌ | `EXA_API_KEY` | 💰 Paid |
| `parallel` | ✅ | ✅ | ✅ | `PARALLEL_API_KEY` | 💰 Paid |

## Recommended Free Setup (No API Keys)

```bash
# 1. Install ddgs DuckDuckGo search
pip install ddgs

# 2. Configure Hermes
hermes config set web.search_backend ddgs

# 3. Reset session (or /reset)
```

This gives you web search with no API keys, no rate limits. Extraction falls back to LLM-based content extraction (OpenRouter auxiliary model).

## Setting Up Firecrawl

Firecrawl gives search + extraction + crawl. Two options:

### Option A: Cloud API (easiest)
1. Get key at https://www.firecrawl.dev/ (free tier available)
2. Add to `.env`:
   ```
   FIRECRAWL_API_KEY=fc-...
   ```
3. Configure Hermes:
   ```bash
   hermes config set web.extract_backend firecrawl
   hermes config set web.search_backend firecrawl
   ```

### Option B: Self-Hosted
Requires Docker with overlay2 support. See [Firecrawl docs](https://docs.firecrawl.dev/self-host).

**Not compatible with Proxmox unprivileged LXC containers** (overlayfs denied).

## Verifying

```bash
# Check what backends are active
grep -E '^(search|extract)_backend' ~/.hermes/config.yaml

# Check env vars exist
grep -E '^(FIRECRAWL|TAVILY|EXA|BRAVE|SEARXNG)_' ~/.hermes/.env

# Quick test that Hermes recognizes the backend
hermes doctor 2>&1 | grep -i web
```

## Pitfalls

- `hermes doctor` shows "web — no search/extract API key set" when no backend is configured. This is normal if you haven't configured one — the tools still work with limited capability.
- Backends are checked at session start. After changing config, do `/reset`.
- `web.search_backend` and `web.extract_backend` can differ (e.g., ddgs for search, firecrawl for extract).
- The `web.backend` key is a combined override. Setting both search+extract separately is more precise.