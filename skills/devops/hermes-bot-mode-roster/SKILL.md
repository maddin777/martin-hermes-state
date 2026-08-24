---
name: hermes-bot-mode-roster
description: Build Hermes Bot Mode role bots as local-only profiles.
category: devops
---

# Hermes Bot Mode Roster

Build and manage **Bot Mode** role bots — named agents with their own personality, chat, memory and schedule (the "Named Agent Engine" shown in Julian Ivanov's / Julian Goldie's Hermes videos, free alternative to Grok Bot).

Core fact: **a bot IS a Hermes profile.** Bot Mode is just a desktop-sidebar interface layered on existing profiles. Every existing profile already shows up as a bot.

## Local-only roster (no gateway)

For a desktop-local bot you do NOT need a Telegram bot token, gateway systemd service, or channel. That is the big fork from the profile-management skill's gateway flow — skip it.

Quick setup (per bot):
```bash
# 1. Create profile, cloning default config (inherits OPENROUTER_API_KEY + model)
hermes profile create <name> --clone

# 2. Set roster + kanban description (surfaces job in roster & kanban routing)
hermes profile describe <name> --text "One sentence: what this bot is good at."

# 3. Write the bot's personality
#    $EDITOR ~/.hermes/profiles/<name>/SOUL.md
```

Verify: `hermes profile list` → bot present, Gateway column `stopped` (correct for local-only). Smoke-test the SOUL loaded:
```bash
hermes -p <name> chat -q "Was ist deine Rolle?" -Q
# bot answers with its own role → SOUL.md effective
```

## Building a role-bot team

Create them in a loop, one clone+describe+SOUL each: writer, coder, designer, researcher, reviewer…

Each SOUL.md should carry:
- **Deine Rolle** section naming the job and its artifacts
- **Autonomie-Grenzen**: explicit "Ohne Fragen machen" vs "Nur mit ausdrücklichem OK" (e.g. publishing needs OK; drafting/researching does not)
- **Team-Koordination**: e.g. reviewer critiques the others' work as QA, not attack; researcher feeds facts to writer/designer
- A **Qualitätsstandard** line so the bot self-checks before declaring done

## Pitfalls
- SOUL.md personality only applies on a **new** session; running sessions keep the old prompt until reset/restart. Fine for freshly-created bots.
- Profile alias (`writer chat`, `coder chat`, …) auto-appears at `~/.local/bin/<name>`.
- `hermes profile describe <name> --text "..."` sets the description used by the kanban decomposer to route work by role, not just name.
- Add Telegram/cron delivery only later IF a bot needs it — reuse `hermes-profile-management` for those steps. Don't pre-build gateways for bots that stay local.

## Related
- `hermes-profile-management` — full gateway/cron/credential flow for when a bot graduates to Telegram.
