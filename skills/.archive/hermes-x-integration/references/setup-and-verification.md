# x_search Setup & Verification (Session 2026-05-21)

## Initial State

- Hermes v0.14.0 (2026.5.16)
- `x_search` toolset: **disabled** (listed as `✗ disabled  x_search  🐦 X (Twitter) Search`)
- `TWITTERAPI_IO_KEY` in `.env` — NOT used by x_search (legacy)
- `xai-oauth` credential registered in auth.json but empty (no tokens)

## Steps Performed

### 1. Auth Inspection

```
hermes auth list
```
Output showed: `xai-oauth (1 credentials): #1  xai-oauth-oauth-1  oauth  xai_pkce ←`

auth.json structure:
- Key `credential_pool.xai-oauth` exists with empty provider entry
- First token was stored with `access_token` + `refresh_token` fields

### 2. Enable Toolset

```
hermes tools enable x_search
```
→ `✓ Enabled: x_search`

### 3. Direct API Verification

Used the xAI Responses API directly (bypassing Hermes session, since tool changes need `/reset`):

**Phase 1 — Basic auth check:**
```
POST https://api.x.ai/v1/chat/completions
Model: grok-4.20-reasoning
→ 200 OK, "OK"
```

**Phase 2 — x_search tool call:**
```
POST https://api.x.ai/v1/responses
Model: grok-4.20-reasoning
Tools: [{"type": "x_search"}]
Input: "search X for: AI trends"
→ 200 OK
```
Response contained:
- `reasoning` block (model planning which sub-tools to call)
- `custom_tool_call` for `x_semantic_search` and `x_keyword_search`
- `message` block with full answer + inline citations with X post URLs

### 4. Verifying OpenRouter Grok (separate, not the same)

The user first thought they'd set up Grok via OpenRouter. Tested:
```
x-ai/grok-4.20 via OpenRouter → 200 OK
```
This costs $0.0013/1K input tokens via OpenRouter credit. Works independently of the native x_search tool (which uses xAI API directly via OAuth).

## Key Insights

1. **x_search is NOT the xurl CLI** — it's a native Hermes tool backed by xAI's Responses API
2. **Requires SuperGrok subscription** — free xAI accounts won't work for x_search
3. **Tool needs separate enable** — disabled by default in all platforms
4. **Needs /reset after enabling** — tools are loaded at session start
5. **xAI API is fast for chat** (~1-2s), **slower for x_search** (10-30s depending on query breadth)
6. **Default timeout is 180s** — the tool handles this internally; direct curl needs explicit `--timeout`

## Available Grok Models (via xAI API)

| Model | Context | Notes |
|-------|---------|-------|
| `grok-4.20-reasoning` | 2M | Default for x_search tool |
| `grok-4.3` | 1M | Lighter model |

These are used by the native tool. OpenRouter offers additional models like `x-ai/grok-build-0.1` at different pricing.