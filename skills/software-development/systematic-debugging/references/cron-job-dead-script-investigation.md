# Cron Job Failure: Missing Target Script Investigation

## Scenario

A cron job runs regularly but always fails with `Errno 2 No such file or directory` — the target script doesn't exist.

## Investigation Sequence

### Step 1: Distinguish Hermes Cron vs System Crontab

```bash
# Hermes managed crons (profile-specific)
hermes cron list
hermes --profile <name> cron list

# System crontab (root)
crontab -l
```

Hermes cron jobs appear in `hermes cron list`. System crontab entries are managed via `crontab -e`. A missing script in one does not imply anything about the other.

### Step 2: Find the First Failure

Check the cron log for the first occurrence of the error:

```bash
grep "START" /path/to/cron.log | head -5    # first runs
grep "No such file" /path/to/cron.log | head -1  # first failure
```

Key question: Did the script **ever** complete successfully?

```bash
grep -c "DONE" /path/to/cron.log   # 0 = never ran successfully
```

### Step 3: Check File Existence + Traces

```bash
# Does the script exist?
ls -la /path/to/scripts/target_script.py

# Was it ever compiled (pre-3.5 Python)?
ls /path/to/scripts/__pycache__/ | grep target_script

# Does any file reference it? (aspirational code)
grep -r "target_script" /path/to/project/ --include="*.py" --include="*.md" --include="*.json"
```

Three categories of reference:
- **Import reference** — another script `import`s it → script likely existed
- **Hardcoded string/description** — a label, cron description, or config key → may be aspirational
- **Cron log only** — only the cron entry references it → likely never existed

### Step 4: Check Dashboard / Frontend References

If the system has a dashboard with hardcoded cron descriptions, check whether the description is an aspirational label for a **workflow** (not a script). Example:

```python
descriptions = {
    "trading_pipeline": "YouTube → Analyse → Watchlist → Signale",
}
```

This describes the **orchestration**, not a specific script. The individual steps run as separate scripts at different times.

### Step 5: Check Session / Git History

```bash
# Git
cd /path/to/project
git log --all --oneline -- scripts/target_script.py

# Session history
session_search(query="target_script")
```

### Step 6: Cross-Reference with Actual Pipeline

If the cron entry describes a pipeline, compare the individual scripts that actually run:

| Time | Script | Purpose |
|------|--------|---------|
| 10:00 | `script_a.py` | Step 1 |
| 10:30 | `script_b.py` | Step 2 |
| 11:00 | `script_c.py` | Step 3 |

The "pipeline" label may be a summary of these individual steps.

## Root Cause Categories

| Finding | Likely Cause |
|---------|-------------|
| `__pycache__` has compiled bytecode | Script existed, was deleted |
| No `__pycache__`, no git history | Script was planned but never created |
| Script referenced but with different name | Renamed during refactor |
| Only cron entry + dashboard label reference it | Aspirational — added prematurely |
| Script exists in different directory | Path changed, cron not updated |

## Resolution Options

1. **Remove stale cron entry** if the work is done by other scripts
2. **Create the script** if the pipeline step is missing
3. **Update the cron path** if the script was moved
4. **Rename the dashboard label** if it was always aspirational
