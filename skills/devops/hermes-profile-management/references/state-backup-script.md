# State Backup Script (hermes-state-sync.sh)

Location: `~/.hermes/scripts/hermes-state-sync.sh`

```bash
#!/bin/bash
# Hermes State → GitHub Sync (no_agent cron script)
# Silent on success, error output on failure
set -u

REPO="/root/martin-hermes-state"
HERMES="/root/.hermes"

cd "$REPO" || { echo "REPO dir $REPO not found"; exit 1; }

# ---- .gitignore ----
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
sessions/
state.db*
bin/
EOF

# ---- Sync Skills ----
rm -rf skills/
cp -aL "$HERMES/skills/" skills/

# ---- Sync Profiles (exclude sensitive/large) ----
rm -rf profiles/
mkdir -p profiles/
for profile_path in "$HERMES"/profiles/hermes-* "$HERMES"/profiles/hermes_lang "$HERMES"/profiles/hermes_trading; do
  [ -d "$profile_path" ] || continue
  profile=$(basename "$profile_path")
  src="$profile_path"
  dst="profiles/$profile"
  rsync -a --delete \
    --exclude='.env' --exclude='.env.*' \
    --exclude='auth.json' --exclude='*auth.json' \
    --exclude='config.yaml' --exclude='config.yaml.bak' \
    --exclude='models_dev_cache.json' \
    --exclude='venv/' --exclude='__pycache__/' --exclude='*.pyc' \
    --exclude='logs/' --exclude='data/' \
    --exclude='cron/output/' --exclude='sessions/' \
    --exclude='state.db*' --exclude='bin/' \
    --exclude='*.tar.gz' --exclude='*.zip' \
    "$src/" "$dst/" 2>/dev/null
done

# ---- Sync Core Identity Files ----
mkdir -p identity/
for f in SOUL.md USER.md MEMORY.md; do
  if [ -f "$HERMES/$f" ]; then
    cp "$HERMES/$f" "identity/$f"
  fi
done

# ---- Sync Hermes config ----
mkdir -p config/
cp "$HERMES/config.yaml" config/ 2>/dev/null

# ---- Git Commit & Push (suppress output) ----
git add -A 2>/dev/null

if git diff --cached --quiet; then
  exit 0
fi

git commit -m "state sync $(date -u '+%Y-%m-%d %H:%M UTC')" >/dev/null 2>&1
git push origin main >/dev/null 2>&1

if [ $? -ne 0 ]; then
  echo "=== STATE BACKUP GIT PUSH FEHLER ==="
  echo "Letzter Git-Status:"
  git status --short 2>&1
  exit 1
fi

exit 0```
