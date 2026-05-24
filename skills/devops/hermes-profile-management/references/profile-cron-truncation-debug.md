# Profile Cron Truncation Debugging (Martin's hermes-news Session)

## Error

```
RuntimeError: Response remained truncated after 3 continuation attempts
```

Seen in `hermes --profile hermes-news cron list` output or the cron output MD file.

## Root Cause

The cron job's model (`openai/gpt-oss-120b:free`) has a small output-token ceiling. The model produces content that exceeds Hermes' response-length limit. Hermes attempts 3 continuations, each also truncated, then gives up.

## Diagnostic Sequence (from May 15, 2026 session)

### Step 1: Check the cron job config

```bash
cat /root/.hermes/profiles/hermes-news/cron/jobs.json | grep -A2 '"model"'
```
Expected: `"model": "openrouter/owl-alpha"` (high-output model)
Found: `"model": "openai/gpt-oss-120b:free"` (low-output model, reverted from previous fix)

### Step 2: Check profile default model

```bash
head -5 /root/.hermes/profiles/hermes-news/config.yaml
```
Showed `model.default: openai/gpt-oss-120b:free` -- the cron job's model had silently reverted to this default.

### Step 3: Check gateway logs for the truncation event

```bash
journalctl -u hermes-gateway-hermes-news --no-pager -n 30 --since "06:00"
```
Showed:
```
Response truncated (finish_reason='length') - model hit max output tokens
Requesting continuation (1/3)...
Response truncated (finish_reason='length') - model hit max output tokens
Requesting continuation (2/3)...
```

This appeared in the OLD gateway's shutdown log when the service was restarted while still processing the failed cron run.

### Step 4: Check output file

```bash
ls -lt /root/.hermes/profiles/hermes-news/cron/output/999fe77b345a/
```
The latest file was 996 bytes -- only the error message, no actual news.

## Fix Applied

1. **Change model in jobs.json** from `openai/gpt-oss-120b:free` to `openrouter/owl-alpha` (free, 1M context, agentic-workload-optimized).
2. **Restart the profile gateway:** `systemctl restart hermes-gateway-hermes-news`
3. **Trigger test run:** `hermes --profile hermes-news cron run 999fe77b345a`
4. **Verify:** Check cron list for `ok` status and output file for content.

## Result

After fix, the triggered run completed successfully:
- Last run: `2026-05-15T06:33:51 -- ok`
- Output: 3200 bytes, 8 German news items with links
- Model: `openrouter/owl-alpha` handled the output without truncation

## Key Observations

- The `cronjob` tool (used for main Hermes cron) does NOT work for profile cron jobs. Attempting `cronjob(action='update', job_id='999fe77b345a')` returns "Job with ID '999fe77b345a' not found". Profile crons must be managed via `hermes --profile <name> cron <command>` or direct jobs.json editing.
- The model in jobs.json had been changed previously (May 11) from `openai/gpt-oss-120b:free` to `openrouter/owl-alpha`, but was silently reverted by May 15. The config.yaml model.default was still `openai/gpt-oss-120b:free`, suggesting some process or restart resets the cron job's model to the profile default.
- `hermes cron run` executes on the **next scheduler tick**, not immediately. The cron list's `last_run` only updates after the job completes.
- Test-run session files are at `~/.hermes/profiles/hermes-news/sessions/session_cron_999fe77b345a_<timestamp>.json` and may be large (128KB+) if the cron agent was actively browsing.