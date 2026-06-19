# Profile Cron Broken-Job Diagnosis

Session: 2026-06-18 — Martin: "Warum kamen keine news?"

## Symptom

A cron job created via `cronjob action=create ... profile=hermes-news` never ran. No error, no delivery — the job simply didn't exist from the scheduler's perspective.

## Root Cause

The `cronjob create` tool wrote the job into the **profile's** `cron/jobs.json` (`/root/.hermes/profiles/hermes-news/cron/jobs.json`) instead of the default one. The job object was structurally incomplete:

### Job comparison: complete (default DB) vs. broken (profile DB)

| Field | Default DB (works) | Profile DB (broken) |
|---|---|---|
| `id` | `"d1c92b5337c5"` | **missing** |
| `enabled` | `true` | **missing** (→ None → disabled) |
| `repeat` | `{"times": null, "completed": 282}` | **missing** |
| `last_run_at` | `"2026-06-18T08:11:43+02:00"` | **missing** |
| `created_at` | `"2026-06-15T09:15:46+02:00"` | **missing** |
| `origin` | `{"platform": "telegram", "chat_id": "216051232", ...}` | **missing** |
| `next_run_at` | future timestamp | **"2026-06-17T07:35:00+02:00"** (past → already expired) |
| `state` | `"scheduled"` | `"scheduled"` |
| `deliver` | `"telegram"` | `"origin"` |

## Diagnosis Steps

### 1. Check both cron DBs

```bash
# Default DB — what cronjob list shows
python3 -c "
import json
d = json.load(open('/root/.hermes/cron/jobs.json'))
for j in d['jobs']:
    print(f'name={j[\"name\"]} | id={j.get(\"id\",\"MISSING\")[:12]} | enabled={j.get(\"enabled\")} | next_run={j.get(\"next_run_at\",\"?\")}')
"

# Profile DB — what the profile's gateway scheduler uses
python3 -c "
import json
d = json.load(open('/root/.hermes/profiles/hermes-news/cron/jobs.json'))
for j in d.get('jobs',[]):
    print(f'name={j.get(\"name\",\"?\")} | has_id={\"id\" in j} | has_enabled={\"enabled\" in j} | next_run={j.get(\"next_run_at\",\"?\")}')
"
```

### 2. Identify incomplete jobs

A job is broken if it:
- Has no `id` field
- Has no `enabled` field (or `enabled` is `None`/`false`)
- Has `next_run_at` in the past
- Is in the profile DB but NOT in the default DB

### 3. Fix

```python
import json

# Step 1: Delete broken job from profile DB
path = '/root/.hermes/profiles/hermes-news/cron/jobs.json'
data = json.load(open(path))
data['jobs'] = [j for j in data['jobs'] if j.get('name') != 'daily-news-briefing']
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
print(f"Removed broken job. {len(data['jobs'])} jobs remaining in profile DB.")

# Step 2: Verify profile DB is clean
data = json.load(open(path))
for j in data.get('jobs', []):
    print(f"  Remaining: {j.get('name','?')}")
```

Then recreate in default scheduler via the `cronjob` tool (see pitfall #15 in SKILL.md).

## Prevention

When creating any cron job that should run under a profile:
- **Use Approach A** (default scheduler + `profile:` param) if delivery through main bot is fine
- **Use Approach B** (write directly to profile DB with all fields) if delivery must go through profile's bot
- **Never** use `cronjob create` with `profile:` — it writes a broken job