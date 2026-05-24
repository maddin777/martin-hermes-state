---
name: hermes-state-github-sync
description: Backup Hermes agent state (skills, profiles, config, identity files) to GitHub repo via no_agent cron. Git-based, no rsync needed. Silent on success, alert on failure.
category: devops
---

# Hermes State GitHub Sync

**Trigger**: Durable backup of skills/memory/profile state across sessions/restarts/server migrations. Runs nightly at 03:00 UTC.

## Architecture

```
LLM-driven cron (old, deprecated)    →    no_agent script (current)
rsync → local git → push             →    git directly (no rsync)
system crontab                       →    Hermes cron
always delivers "success" message    →    silent on success, alert on failure
```

## Current Setup (Martin's server)

- **Repo**: `github.com/maddin777/martin-hermes-state` (public)
- **Local clone**: `/root/martin-hermes-state/`
- **Script**: `~/.hermes/scripts/hermes-state-sync.sh`
- **Cron**: `hermes state-github-sync` (job `736b150caef2`)
- **Schedule**: `0 3 * * *` (nightly 03:00 — after vault-bisync at 02:00 and vault-insights at 02:45)
- **Mode**: `no_agent` — no LLM invoked
- **Delivery**: `local` — silent on success, error output on failure

## Initial Setup (one-time)

```bash
# 1. Create repo
gh repo create maddin777/martin-hermes-state --public --description "Hermes Skills/Memory/State Backup"

# 2. Clone locally
cd /root && git clone https://github.com/maddin777/martin-hermes-state.git
```

## What Gets Synced

| Source | Destination | Exclusions |
|--------|------------|------------|
| `~/.hermes/skills/` | `skills/` | `.cache/`, `cron/output/` |
| `~/.hermes/profiles/hermes-*/` | `profiles/hermes-*/` | `.env`, `venv/`, `logs/`, `data/`, `cron/output/`, `sessions/` |
| `~/.hermes/config.yaml` | `config/config.yaml` | — |
| `~/.hermes/cron/jobs.json` | `config/jobs.json` | — |
| `~/obsidian-vault/SOUL.md` | `identity/SOUL.md` | — |
| `~/obsidian-vault/MEMORY.md` | `identity/MEMORY.md` | — |
| `~/obsidian-vault/USER.md` | `identity/USER.md` | — |

Everything goes into a single flat repo with `.gitignore` excluding:
- `.env`, `.env.*`, `**/.env` (secrets)
- `venv/`, `__pycache__/`, `*.pyc`
- `*.db`, `*.sqlite`, `*.tar.gz`, `*.zip`, `*.so`
- `logs/`, `data/`
- `.cache/`, `cron/output/`

## Sync Script

Location: `~/.hermes/scripts/hermes-state-sync.sh`

```bash
#!/bin/bash
# Hermes State → GitHub Sync (no_agent cron script)
# Silent on success, error output on failure
set -u

REPO="/root/martin-hermes-state"
HERMES="/root/.hermes"
VAULT="/root/obsidian-vault"

cd "$REPO" || { echo "REPO dir $REPO not found"; exit 1; }

# Write .gitignore (always fresh)
cat > .gitignore << 'EOF'
# Secrets
.env
.env.*
**/.env
**/venv/
**/__pycache__/
*.pyc
# Large/binary
*.db
*.sqlite
*.tar.gz
*.zip
*.so
logs/
data/
# Temp
.cache/
cron/output/
EOF

# Sync skills
rm -rf skills/
cp -aL "$HERMES/skills/" skills/

# Sync profiles (filtered)
rm -rf profiles/
for profile in hermes-*; do
  src="$HERMES/profiles/$profile"
  [ -d "$src" ] || continue
  dst="profiles/$profile"
  rsync -a --delete \
    --exclude='.env' --exclude='.env.*' \
    --exclude='venv/' --exclude='__pycache__/' \
    --exclude='logs/' --exclude='data/' \
    --exclude='cron/output/' --exclude='sessions/' \
    "$src/" "$dst/" 2>/dev/null
  # Keep only: skills/, cron/jobs.json, SOUL.md, profile configs
  find "$dst" -type f \
    ! -path '*/skills/*' \
    ! -name 'SOUL.md' \
    ! -name 'jobs.json' \
    ! -name '*.profile.yaml' \
    ! -name '*.json' \
    -delete 2>/dev/null
  find "$dst" -type d -empty -delete 2>/dev/null
done

# Sync identity files
mkdir -p identity/
cp "$VAULT/SOUL.md" identity/ 2>/dev/null
cp "$VAULT/MEMORY.md" identity/ 2>/dev/null
cp "$VAULT/USER.md" identity/ 2>/dev/null

# Sync config
mkdir -p config/
cp "$HERMES/config.yaml" config/ 2>/dev/null
cp "$HERMES/cron/jobs.json" config/ 2>/dev/null

# Git commit & push
git add -A 2>/dev/null
if git diff --cached --quiet; then
  exit 0  # No changes — silent
fi

git commit -m "state sync $(date -u '+%Y-%m-%d %H:%M UTC')" 2>&1
git push origin main 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
  echo "=== STATE BACKUP GIT PUSH FEHLER ==="
  exit 1
fi
exit 0  # Silent on success
```

## Cron Setup

```bash
# Create the cron job (no_agent mode)
hermes cron create \
  --name "hermes-state-github-sync" \
  --schedule "0 3 * * *" \
  --script hermes-state-sync.sh \
  --no-agent \
  --deliver local
```

## Pitfalls

### 1. GitHub Push Protection (Secret Scanning)
GitHub blocks pushes containing `ghp_` tokens or other secrets. The initial sync will fail if any file contains a PAT, even in comments/docs.

**Symptoms:**
```
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: - Push cannot contain secrets
remote: - GitHub Personal Access Token
```

**Diagnosis:**
```bash
grep -rn 'ghp_' /root/martin-hermes-state/ --include='*.md' 2>/dev/null
```

**Fix:**
1. Redact the PAT in the synced file (NOT the source — the synced copy in the repo dir)
2. Amend the commit: `git commit --amend && git push origin main`
3. If the original commit is already rejected, rewrite it:
   ```bash
   git add -A && git commit --amend && git push origin main
   ```
4. Also redact the PAT in the source skill file under `~/.hermes/skills/` so it doesn't get pushed again next sync

### 2. No Changes → Silent Exit
If nothing changed since last sync, the script exits 0 without committing. This is correct behavior — no empty commits.

### 3. Large Files Bloating the Repo
The `.gitignore` excludes binaries (`.db`, `.tar.gz`, `.zip`, `.so`). If a large file slips through:
```bash
# Remove from git tracking without deleting local file
echo "*.db" >> .gitignore
git rm --cached *.db
git commit -m "Remove DB files from repo"
git push origin main
```

### 4. Repo Exists but No Local Clone
If the server is rebuilt but the GitHub repo exists:
```bash
cd /root && git clone https://github.com/maddin777/martin-hermes-state.git
```

### 5. PAT in .env is Fine
The PAT used for `gh auth` or in `~/.hermes/.env` is NOT synced (`.env` is in `.gitignore`). Only PATs hardcoded in SKILL.md or other text files trigger the scanner.

## Verification

```bash
# Check last backup
cd /root/martin-hermes-state && git log --oneline -3

# Check cron status
hermes cron list | grep -A3 "state-github-sync"

# Check sync actually ran
ls -la /root/.hermes/cron/output/$(hermes cron list | grep -B1 "state-github-sync" | grep -oP '[a-f0-9]{12}')/
```

## Recovery

If the server dies and you need to restore:
```bash
cd /root && git clone https://github.com/maddin777/martin-hermes-state.git
# Copy skills back
cp -r martin-hermes-state/skills/* ~/.hermes/skills/
# Copy config back
cp martin-hermes-state/config/* ~/.hermes/
# Recreate profiles from profles/* structure
```