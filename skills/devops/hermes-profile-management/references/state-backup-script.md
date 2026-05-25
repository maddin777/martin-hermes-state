# State Backup Script (hermes-state-sync.sh)

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