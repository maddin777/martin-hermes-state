---
name: github-operations
description: "GitHub: auth, PRs, issues, repos, code review."
trigger:
  - "GitHub auth, push, pull"
  - "Create or review PR"
  - "GitHub issue"
  - "Clone or fork repo"
---

# GitHub Operations

Unified skill for all GitHub operations — authentication, pull requests, issues, repository management, and code review.

## Authentication

```bash
# Quick check
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  AUTH="gh"
else
  AUTH="git"
fi
```

### Methods

- **gh CLI**: `gh auth login` or `echo "TOKEN" | gh auth login --with-token`
- **HTTPS + PAT**: github.com/settings/tokens
- **SSH**: `git config --global url."git@github.com:".insteadOf "https://github.com/"`

### Headless Device Flow

```bash
RESP=$(curl -s -X POST -H "Accept: application/json" \
  -d "client_id=178c6fc778ccc68e1d6a&scope=repo,read:org,gist" \
  https://github.com/login/device/code)
USER_CODE=$(echo "$RESP" | sed 's/.*"user_code":"\([^"]*\)".*/\1/')
echo "Enter $USER_CODE at https://github.com/login/device"

while true; do sleep 5; POLL=$(curl -s -X POST -H "Accept: application/json" \
  -d "client_id=178c6fc778ccc68e1d6a&device_code=${DEVICE_CODE}&grant_type=urn:ietf:params:oauth:grant-type:device_code" \
  https://github.com/login/oauth/access_token); 
  case "$POLL" in *access_token*) echo "$POLL" | sed 's/.*"access_token":"\([^"]*\)".*/\1/' | timeout 20 gh auth login --with-token; break ;; esac; done
```

## Pull Requests

```bash
# Create
git checkout -b feat/feature && git add . && git commit -m "feat: add"
git push -u origin HEAD
gh pr create --title "feat: add" --body "## Summary"

# Monitor
gh pr checks --watch

# Merge
gh pr merge --squash --delete-branch
```

## Issues

```bash
gh issue create --title "Bug: login redirect" --body "Description" --label bug
gh issue list --label needs-triage
gh issue edit 42 --add-label bug
```

## Repos

```bash
gh repo clone owner/repo
gh repo create my-project --public --clone
gh repo fork owner/repo --clone
gh release create v1.0.0 --generate-notes
```

## Code Review

```bash
git diff main...HEAD --stat
gh pr view 123
gh pr checkout 123
gh pr review 123 --approve --body "LGTM!"
```

## Issue → PR Workflow

1. Read full issue thread
2. Sweep duplicates: `gh pr list --search "#N" --state all`
3. Validate premise vs current code
4. Implement fix + class-level fix
5. Prove regression test fails without fix
6. Open PR immediately
7. Shepherd CI, comment PR link on issue

## References

- `references/github-auth.md` — Full auth setup
- `references/ci-troubleshooting.md` — CI auto-fix
- `templates/pr-body-feature.md` — PR template
- `templates/pr-body-bugfix.md` — Bugfix template
