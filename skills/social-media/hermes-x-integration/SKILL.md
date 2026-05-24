---
name: hermes-x-integration
description: "Native X (Twitter) API integration in Hermes Agent via xAI Grok OAuth — x_search tool, xai-oauth credential setup, verification, and troubleshooting."
version: 1.0.0
author: Agent (auto-generated)
created: 2026-05-21
category: social-media
metadata:
  hermes:
    tags: [x, twitter, xai, grok, x_search, social-media]
    min_hermes_version: "0.14.0"
---

# Hermes X Integration — Native x_search Tool

Hermes v0.14.0+ ships a native `x_search` tool that searches X (Twitter) posts, profiles, and threads via xAI's Responses API (`x_semantic_search` / `x_keyword_search`). Unlike the `xurl` CLI (third-party tool), this is a built-in Hermes tool with no external binary dependency.

## Prerequisites

- Hermes Agent **v0.14.0+** (check: `hermes --version`)
- A **SuperGrok subscription** (xAI) — the `x_search` tool requires this paid tier
- **xAI OAuth** set up via `hermes auth add xai-oauth`

## Setup

### 1. Authenticate with xAI (OAuth)

```bash
hermes auth add xai-oauth
```

This runs an OAuth 2.0 PKCE flow via xAI. A browser opens for login. After success, the refresh + access tokens are stored in `~/.hermes/auth.json` under `credential_pool.xai-oauth`.

Verify the credential exists:

```bash
hermes auth list | grep xai-oauth
```

Expected output: `xai-oauth (1 credentials):  #1  xai-oauth-oauth-1    oauth   xai_pkce ←`

### 2. Enable the x_search Toolset

The `x_search` toolset is **disabled by default**. Enable it:

```bash
hermes tools enable x_search
```

This immediately writes the config but only takes effect **after `/reset`** (new session). The tool is not available in the current session.

### 3. Verify in a New Session

Start a new session (`/reset` or start a new `hermes`), then run a search:

```
x_search(query="AI trends", limit=10)
```

Or ask naturally: *"Was gibt's Neues auf X zu KI-Agenten?"* — the agent auto-selects the `x_search` tool when appropriate.

## Tool Schema

The tool `x_search` accepts:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | **yes** | Search query |
| `allowed_x_handles` | string[] | no | Restrict to these handles only (max 10) |
| `excluded_x_handles` | string[] | no | Exclude these handles (max 10) |
| `from_date` | string (YYYY-MM-DD) | no | Start date |
| `to_date` | string (YYYY-MM-DD) | no | End date |
| `enable_image_understanding` | bool | no | Analyze images in matching posts |
| `enable_video_understanding` | bool | no | Analyze videos in matching posts |

**Constraints:**
- `allowed_x_handles` and `excluded_x_handles` are mutually exclusive
- `from_date` must not be after `to_date` or in the future
- Queries are internally split into `x_semantic_search` + `x_keyword_search` by xAI

The response includes `citations` (top-level URLs) and `inline_citations` (annotated in text). A `degraded: true` flag means no real X-index citations were found despite narrowing filters — the answer came from model knowledge alone.

## Testing (Direct API Call)

To verify the credential works without starting a new session:

```bash
python3 << 'PYEOF'
import os, json, requests
auth_path = os.path.expanduser('~/.hermes/auth.json')
with open(auth_path) as f:
    data = json.load(f)
token = data['credential_pool']['xai-oauth'][0]['access_token']

# Phase 1: Basic chat (verifies token is valid)
r = requests.post("https://api.x.ai/v1/chat/completions",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    json={"model": "grok-4.20-reasoning", "messages": [{"role": "user", "content": "say OK"}], "max_tokens": 5},
    timeout=15)
print(f"Chat: {r.status_code} — {r.json()['choices'][0]['message']['content']}")

# Phase 2: x_search (verifies x_search tool works)
r = requests.post("https://api.x.ai/v1/responses",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    json={
        "model": "grok-4.20-reasoning",
        "input": [{"role": "user", "content": "search X for: AI trends"}],
        "tools": [{"type": "x_search"}],
        "store": False,
    },
    timeout=120)
d = r.json()
msg = next((x for x in d.get('output', []) if isinstance(x, dict) and x.get('type') == 'message'), None)
if msg:
    text = ''.join(c.get('text','') for c in msg.get('content',[]) if c.get('type')=='output_text')
    print(f"Search: {r.status_code} — {text[:100]}...")
else:
    print(f"Search: {r.status_code} — Keine message in output")
PYEOF
```

## Pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| Tool not found in session | x_search toolset not enabled | `hermes tools enable x_search` + `/reset` |
| xai-oauth empty in auth.json | OAuth flow not completed | Run `hermes auth add xai-oauth` again |
| `x_search` returns empty (200 OK, 0 citations) | Query too vague; no matching posts | Try a more specific query or use `allowed_x_handles` |
| `401 User not found` on OpenRouter Grok | Different from native x_search | This is expected — the native tool uses xAI API directly, not OpenRouter |
| x_search API timeout | Default tool timeout is 180s | Set `x_search.timeout_seconds` in config.yaml if needed |
| Multiple accounts | Only one xai-oauth credential supported | Re-run `hermes auth add xai-oauth` to replace |

## x_search in Profile Cron Jobs

To make x_search available in another Hermes profile's cron jobs (e.g. `hermes-news` daily briefing), you need **two changes** — not just enabling the toolset:

### 1. Add x_search to the Profile's toolsets

Edit `~/.hermes/profiles/<name>/config.yaml`:

```yaml
toolsets:
- hermes-cli
- x_search
```

The `x_search` toolset is disabled by default. Adding it here makes it available to ALL sessions and cron jobs under that profile.

### 2. Update the Cron Job Prompt

The profile's cron job (in `~/.hermes/profiles/<name>/cron/jobs.json` or managed via `hermes --profile <name> cron`) needs to **instruct** the agent to use x_search. Simply enabling the toolset is not enough — the agent won't know to reach for it unless the prompt says so.

Example prompt addition:

```
Nutze dafuer sowohl WEB-Recherche (web_search) als auch X-Suche (x_search) parallel.
Markiere X-Quellen mit [X] hinter dem Link.
```

### 3. Credential Inheritance

The xai-oauth credential in `~/.hermes/auth.json` is **global** — all profiles inherit it automatically. No per-profile credential setup needed.

### 4. Next Run

Changes take effect on the cron job's next scheduled run. No gateway restart needed — the cron starts a fresh session each time and picks up the updated config.yaml.

### Pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| x_search tool not found in cron session | x_search missing from profile's config.yaml toolsets | Add `- x_search` to `toolsets:` in profile config.yaml |
| Agent doesn't use x_search despite tool being available | Prompt doesn't instruct it — agent defaults to web_search only | Update cron prompt to explicitly request X-Suche |
| Profile cron job not found by cronjob tool | Profile cron ≠ main cron | Use `hermes --profile <name> cron` CLI or edit jobs.json directly |
| x_search returns degraded=true with no citations | Query too vague or narrow date range | Make query more specific, don't restrict dates too tightly |

## Config Reference

In `config.yaml` under `x_search:`:

```yaml
x_search:
  model: grok-4.20-reasoning     # Default model for x_search
  timeout_seconds: 180            # Request timeout
  retries: 2                      # Retry count for 5xx errors
```

## Related

- `xurl` skill — X/Twitter via the xurl CLI (post, reply, DM, follow) — a separate toolchain that uses the X API directly
- `hermes-agent` skill — general Hermes Agent configuration