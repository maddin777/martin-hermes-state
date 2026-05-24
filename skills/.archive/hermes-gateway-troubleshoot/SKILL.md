---
name: hermes-gateway-troubleshoot
category: devops
description: Diagnose and fix hermes-gateway.service failures — PID file races, Telegram token conflicts, systemd restart loops.
---

# Hermes Gateway Troubleshooting

Use when `hermes-gateway.service` or profile gateway services are **failed**, **inactive**, or **crash-looping**.

## Symptoms & Fixes

### 1. "PID file race lost to another gateway instance"
**Cause:** Stale gateway.pid from previous unclean shutdown.
**Fix:** Stop service → delete gateway.pid in ~/.hermes/ → reset-failed → start service.

### 2. "Telegram bot token already in use (PID XXXX)"
**Cause:** Another gateway instance (or zombie) holds the bot token.
**Fix:** Find process with `ps aux | grep hermes`, kill it, then reset-failed and start service.

### 3. systemd "Start request repeated too quickly"
**Cause:** systemd rate-limiter after repeated crashes (counter at 6).
**Fix:** Run `systemctl reset-failed` on the service before retrying.

### 4. Profile gateway conflicts
Profile gateways share the same Telegram bot token — only ONE can run at a time. The main gateway takes priority.

## Quick Health Check
```bash
systemctl status hermes-gateway.service --no-pager
tail -15 ~/.hermes/logs/agent.log
journalctl -u hermes-gateway.service --no-pager -n 20
```

## Pitfalls

### Updated Systemd Configuration
- Add `PIDFile=/run/hermes-gateway/hermes-gateway.pid` and **both** `EnvironmentFile=/root/.hermes/.env` **and** `EnvironmentFile=/root/.hermes/profiles/<profile>/.env` (e.g., `hermes-news`) to the service unit, ensuring profile‑specific environment variables (Telegram token, allowed users) are loaded.
- Use `ExecStartPre` to:
  - `mkdir -p /run/hermes-gateway`
  - `chmod 755 /run/hermes-gateway`
  - `rm -f /root/.hermes/gateway.pid /root/.hermes/profiles/hermes-news/gateway.pid`
- Reload systemd with `systemctl daemon-reload` after editing the unit file.
- Restart the gateway: `systemctl restart hermes-gateway.service`.
- Verify status: `systemctl status hermes-gateway.service` and that the service is `enabled`.
- This prevents stale PID files and eliminates the “PID file race lost” error.

- Don't remove gateway_state.json unless necessary — it tracks cron state.
- After 6 failed starts, systemd enters rate-limit — must reset-failed before retrying.
- Stale gateway.pid files (both ~/.hermes/gateway.pid and any profile-specific gateway.pid, e.g., ~/.hermes/profiles/<profile>/gateway.pid) are the #1 cause of PID file race errors.
