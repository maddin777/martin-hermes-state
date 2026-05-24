# no_agent Bisync Script: obsidian-bisync.sh

**Location**: `~/.hermes/scripts/obsidian-bisync.sh`
**Cron job**: `obsidian-vault-bisync-nightly` (f5eb3bfaf65e)
**Schedule**: 0 2 * * * (nightly at 02:00)
**Delivery**: local

## Purpose

Bidirectional sync between local Obsidian vault (`/root/obsidian-vault/`) and Google Drive (`gdrive:hermes-obsidian-vault/`) via rclone bisync. Runs as no_agent cron — no LLM involved.

## Behavior

- **Success** → exit 0, empty stdout → SILENT (no delivery)
- **Cache missing/corrupt** → auto-detects "Must run --resync to recover", retries with `--resync`, silent on success
- **Real failure** → prints error details to stdout, exit 1 → delivered to user

## Script

```bash
#!/bin/bash
# Obsidian Vault Bisync — no_agent cron script
# Silent on success (no delivery), outputs error on failure
# Auto-recovers with --resync when cache is missing or corrupted
set -u

VAULT="/root/obsidian-vault"
REMOTE="gdrive:hermes-obsidian-vault"

run_bisync() {
  local extra_flags="${1:-}"
  rclone bisync "$VAULT/" "$REMOTE/" \
    $extra_flags \
    -v --progress \
    --exclude "*.conflict*" \
    --exclude "*conflict*" \
    --exclude ".DS_Store" \
    2>&1
  return $?
}

# First attempt: normal bisync
OUTPUT=$(run_bisync)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  # Silent on success — nothing to report
  exit 0
fi

# Check if it's a recoverable error (cache missing/corrupt → needs --resync)
if echo "$OUTPUT" | grep -q "Must run --resync to recover"; then
  OUTPUT=$(run_bisync "--resync")
  EXIT_CODE=$?
  
  if [ $EXIT_CODE -eq 0 ]; then
    # Resync successful — silent
    exit 0
  fi
fi

# Failure — output error details
echo "=== OBSIDIAN BISYNC FEHLER ==="
echo "Zeit:    $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Exit:    $EXIT_CODE"
echo "Output:"
echo "$OUTPUT"
exit 1
```

## Pitfalls

- **Path consistency is critical**: Use `gdrive:hermes-obsidian-vault/` not `gdrive:`. The cache files are named after the path strings — different paths produce different cache filenames, causing "cannot find prior listings" errors on alternating runs.
- **`--resync-permission` does NOT exist** in rclone v1.73.5 (current on this system). Don't use it.
- **Cache cleanup**: If the bisync state gets confused, delete `/root/.cache/rclone/bisync/` and the next run will auto-resync.
- **Conflict files**: Excluded via `--exclude "*.conflict*"` and `--exclude "*conflict*"` — they accumulate otherwise.
- **Manual resync**: `rclone bisync /root/obsidian-vault/ gdrive:hermes-obsidian-vault/ --resync -v`