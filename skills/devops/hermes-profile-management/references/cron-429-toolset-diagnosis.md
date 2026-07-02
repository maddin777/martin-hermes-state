# Cron 429 Failure — Toolset Cascade Diagnosis

When a profile cron job fails with `HTTP 429: Provider returned error` (rate limit), the root cause is often **not** the rate limit itself — it's a cascade from missing toolsets that burns through tokens and retries until the provider throttles.

## Symptom

```
⚠️ Cron job '<name>' failed:
RuntimeError: HTTP 429: Provider returned error
```

The cron output may show the agent trying multiple approaches before the 429 hits.

## Root Cause Cascade

```
Missing toolset (no `web_search`) 
    → Agent falls back to browser_navigate 
    → bot detection walls (DataDome, Cloudflare) on target sites
    → wasted tokens + API calls
    → max_retries exhausted (agent.api_max_retries: 3)
    → Provider rate limit triggered (429) on final retry
```

## Diagnosis Steps

### 1. Check the request_dump

Profile cron sessions save request dumps under the profile's sessions directory:

```bash
ls -lt ~/.hermes/profiles/<profile>/sessions/request_dump_*_<date>.json | head -3
```

Read the latest one. Key fields to look for:

- `reason`: `"max_retries_exhausted"` — confirms the 429 was the terminal error
- `request.body.model`: which model was actually used (may differ from what you expect)
- `request.body.messages`: first few tool calls show what the agent attempted first
- `request.body.tools`: the full tool list shows which tools were AVAILABLE to the agent

### 2. Check profile config.yaml for toolsets

```bash
grep -A 5 'toolsets:' ~/.hermes/profiles/<profile>/config.yaml
```

Expected: `[hermes-cli, x_search, web]` for any news/research profile that needs `web_search`.

If `web` is missing:
- The agent CANNOT call `web_search` — it doesn't exist in its function list
- Sub-agents spawned via `delegate_task` with `toolsets=[\"web\"]` DO get it (they start a fresh session with their own toolset), but the sub-agent approach adds latency and token overhead
- The parent agent will fall back to `browser_navigate` — unreliable for news sites (bot detection, paywalls)

### 3. Check the model

```bash
grep -A 1 'model:' ~/.hermes/profiles/<profile>/config.yaml
grep '"model"' ~/.hermes/profiles/<profile>/cron/jobs.json | head -1
```

**Free models on OpenRouter** (e.g. `openai/gpt-oss-120b:free`, `nvidia/nemotron-3-super-120b-a12b:free`) are aggressively rate-limited. A single long session with retries can exhaust the free-tier quota for minutes.

**Fix:** Switch to a paid-tier model with higher rate limits, e.g. `deepseek/deepseek-v4-flash` on OpenRouter.

### 4. Reconstruct the failure timeline

From the request_dump, look at the tool_calls in order:

1. First parallel calls → `delegate_task` or `web_search`?
2. If `web_search` → does it exist? (check tools list)
3. If not → what did the agent try instead? `browser_navigate`?
4. Did those succeed? (check snapshot for bot detection: "Just a moment...", "Verifying device", "Security Verification")
5. Did the retry counter exhaust?

## Fix

```yaml
# profile config.yaml — add 'web' toolset
toolsets:
  - hermes-cli
  - x_search
  - web         # enables web_search for the parent agent
```

AND/OR:

```yaml
# profile config.yaml — switch from free to paid model
model:
  provider: openrouter
  default: deepseek/deepseek-v4-flash
```

After changes, restart the gateway:
```bash
systemctl daemon-reload
systemctl restart hermes-gateway-<profile>
```

## Prevention

When creating a new profile for a cron job that needs web research:
- Profile creation checklist must include `web` in toolsets if the cron prompt uses `web_search`
- Don't rely on free-tier OpenRouter models for cron jobs — they WILL 429 eventually
- Test with `hermes --profile <name> cron run <job_id>` before setting the schedule

## Test-Run-Succeeds-But-Cron-Fails Pattern

When a cron job passes a manual DM test but fails at the scheduled time (e.g. with 429):

### Root Cause: Environment Difference

The cron job runs under a **different environment** than a DM test:

| Dimension | DM Test Session | Cron Job | 
|-----------|----------------|----------|
| **Profile** | Default (your DM) | Profile (e.g. hermes-news) |
| **Model** | Your DM model (e.g. deepseek/deepseek-v4-flash) | Cron model override OR profile default |
| **Toolsets** | Full DM toolset | Profile's `toolsets` from config.yaml |
| **web_search** | Always available in DM | Only if `web` in profile toolsets |

The DM test passes because the session has the full toolset + a reliable paid model. The cron fails because the profile is missing tools or uses a free-tier model.

### Diagnosis Checklist

1. **Compare models** — the cron job's model (from `jobs.json` model override) may differ from the profile's `config.yaml` default:
   ```bash
   # Cron model override
   python3 -c "import json; d=json.load(open('~/.hermes/profiles/<profile>/cron/jobs.json')); [print(j.get('model',''), j.get('provider','')) for j in d['jobs'] if j['id']=='<job_id>']"
   
   # Profile default model  
   grep -A 2 '^model:' ~/.hermes/profiles/<profile>/config.yaml
   ```

   **Config drift pitfall:** The cron job may have one model override while `config.yaml` shows a different (possibly outdated) default. Always check `jobs.json` for the actual running model — do NOT trust `config.yaml` alone. If you read config.yaml and find an old model, verify against jobs.json before telling the user.

2. **Compare toolsets** — the cron job inherits the profile's `toolsets`, NOT the DM's toolsets:
   ```bash
   grep -A 5 'toolsets:' ~/.hermes/profiles/<profile>/config.yaml
   ```

3. **Reconstruct the failure from request_dump** — the dump shows EXACTLY what tools were available and what the agent tried:
   - Look at the `tools` array in the request body: is `web_search` present?
   - Look at the first tool calls: did they attempt `web_search` and get "Tool does not exist"?
   - Did they fall back to `browser_navigate`? Hit bot detection?

### Fix

Apply both:
1. **Add `web` to profile toolsets** (if missing) — enables `web_search` directly
2. **Update the profile's default model** to match the cron override — prevents confusion when reading config later
3. **Restart the profile gateway** after changes

### Key Insight

Never rely on a DM-session test to validate a profile cron job. The environments are fundamentally different. Always test via `hermes --profile <name> cron run <job_id>` — this runs in the actual profile environment with its actual toolsets and model.