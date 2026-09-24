---
name: hermes-profile-ops
description: "Hermes profiles: cron, bot mode, vault, management."
trigger:
  - "Hermes profile"
  - "Cron jobs not running"
  - "Bot mode"
---

# Hermes Profile Operations

Unified skill for Hermes profile operations, cron troubleshooting, vault management, and bot mode.

## Subsections

- **hermes-profile-cron-troubleshooting** — Diagnose/fix broken cron jobs in profiles
- **hermes-bot-mode-roster** — Build Hermes Bot Mode role bots
- **hermes-vault-management** — Obsidian vault lifecycle
- **hermes-profile-management** — End-to-end profile management

## Duplicate Telegram Credential Triage (Doctor)

Der Doctor meldet oft identische „Duplicate platform credential across profiles"-Warnungen (TELEGRAM_BOT_TOKEN). Die sind NICHT automatisch echte Konflikte:
nur **aktive Gateways**, die denselben Token halten, streiten real um den Bot.
Brachliegende Tokens in Profilen ohne laufendes Gateway (Roster-/Delegation-Profile)
sind harmlos und der Doctor meldet sie weiter, bis man sie anfasst.

**Triage:** 1) Token-Hash je Profil vergleichen (sha256, nie Secret ausgeben),
2) nur `systemctl list-units | grep hermes-gateway` running-Services zählen.
Nur bei 2+ aktiven Gateways mit gleichem Token handeln: Token+CHAT_ID aus dem
Überschuss-Profil (API-Server-only) per sed entfernen, dann **BEIDE** Gateways
restarten — der geparkte Gateway reconnected nicht von selbst, er bleibt degraded.
Verify: `grep telegram ~/.hermes/logs/gateway.log | tail` → '✓ telegram connected'.
Roster-Profile ohne laufenden Gateway NICHT anfassen.

Siehe vollständige Prozedur in `references/duplicate-token-triage.md`.

See archived devops/ skills for detailed procedures.