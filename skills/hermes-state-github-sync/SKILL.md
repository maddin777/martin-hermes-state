---
name: hermes-state-github-sync
description: Backup/Sync Hermes agent state (skills, memory dumps, user profile, Obsidian todos, trading DB) to GitHub repo. Handles deps (rsync), syntax pitfalls, safety blocks. Reusable for any maddin777/martin-hermes-state-like setup.
category: devops
---

# Hermes State GitHub Sync

**Trigger**: User wants durable backup of skills/memory/state across sessions/restarts/servers.

## Prerequisites
- GitHub auth (maddin777 + PAT [REDACTED] scopes: repo)
- gh CLI installed
- Repo: https://github.com/maddin777/martin-hermes-state (public)

## 1. Initial Setup (one-time)
```
gh repo create maddin777/martin-hermes-state --public --description "Hermes Skills/Memory/State Backup" --clone
cd /root/martin-hermes-state
```

## 2. Manual Sync
```
/root/.hermes/scripts/hermes-state-sync.sh
```
Script:
```
#!/bin/bash
cd /root/martin-hermes-state
rsync -av --delete /root/.hermes/skills/ skills/
for profile in hermes-*; do rsync -av /root/.hermes/profiles/$profile/ profiles/$profile/ --exclude='.env,logs,venv,data/trading.db'; done
# Dumps...
git add . && git commit -m "Auto-sync $(date)" && git push origin main
```

## 3. Auto-Sync Cron
```
(crontab -l 2>/dev/null; echo "0 3 * * * /root/.hermes/scripts/sync.sh >> /root/.hermes/state-sync.log 2>&1") | crontab -
```

## Pitfalls (trial/error learned)\n1. **Secret Scanning**: Redact PATs in SKILL.md (.gitignore + patch old_string=\"ghp_\" new_string=\"[REDACTED]\").\n2. **Large Files**: Exclude venv/DB/binaries (.gitignore: venv/ *.db *.so logs/ .env); rm -rf before push.\n3. **Auth 403**: Fine-grained token scopes (Contents RW, Metadata R); fallback SSH or classic PAT.\n4. **Push History**: git push --force-with-lease after clean; unblock secrets at /security/secret-scanning.\n5. **rsync**: sudo apt install rsync; --exclude for sensitive.\n6. **Cron**: Here-doc EOF safe, date +%Y-%m-%d, git pull --rebase on conflict. (trial/error learned)
1. **rsync missing**: `sudo apt install rsync`
2. **Syntax**: `&&` (no &amp;), here-docs EOF, date +%Y-%m-%d
3. **Safety**: No rm -rf; rsync --delete/exclude (.env/logs/venv/db)
4. **Secret Scanning**: Patch/redact PATs (e.g. skills/hermes-state-github-sync/SKILL.md), unblock link
5. **Auth/Push**: Token-embed remote `https://user:token@github.com/...`, gh auth status
6. **Profile-local**: Loop `for profile in hermes-*; rsync /profiles/$profile/ profiles/$profile/ --exclude sensitive`
7. **DB binary**: sqlite3 .dump fallback echo
8. **No changes**: git commit skips

## Verify
```
cd /root/martin-hermes-state && git log --oneline -5
tail -f /root/.hermes/state-sync.log
```

**Files synced**:
- `skills/` (global 71+)
- `profiles/hermes-*` (news/lang/trading/01/02: skills/cron/sessions/SOUL.md, exclude .env/venv/db/logs)
- `memory/current-memory.txt` (injected dump)
- `user-profile/user.md`
- `obsidian-todos/todos.md`
- `trading-data/portfolio.sql` (dump or fallback)
