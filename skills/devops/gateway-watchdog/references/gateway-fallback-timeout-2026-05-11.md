# Session: Telegram Gateway Fallback-Timeout + Watchdog Recovery (2026-05-11)

## Problem

`hermes doctor` showed `messaging (system dependency not met)`. Gateway service
status showed `failed (Result: exit-code)` with "Start request repeated too quickly".

```log
2026-05-09 09:42:53,678 INFO gateway.run: Connecting to telegram...
2026-05-09 09:43:13,788 INFO gateway.platforms.telegram_network: DoH discovery yielded no new IPs
  (system DNS: unknown); using seed fallback IPs 149.154.167.220
2026-05-09 09:43:23,694 ERROR gateway.run: ✗ telegram error: telegram connect timed out after 30s
```

## Root Cause

`gateway/platforms/telegram_network.py` implements `TelegramFallbackTransport` — an `httpx.AsyncHTTPTransport`
wrapper that rewrites the TCP destination IP to a seed IP (149.154.167.220) while preserving `api.telegram.org`
in the TLS SNI/host header. This transport is used when the initial DoH discovery + system DNS resolution
fail (e.g. in LXC containers with restricted DNS).

The seed IP 149.154.167.220 was unreachable for TLS connections, even though `api.telegram.org` (149.154.166.110)
was directly reachable via `curl`, `ping`, and `python-telegram-bot` without the transport wrapper.

## Diagnosis Steps

1. **Check gateway log** for the specific error:
   ```
   tail -20 ~/.hermes/logs/gateway.log
   ```

2. **Test bot token directly** via HTTP API (bypasses Gateway transport):
   ```python
   import urllib.request, json
   token = "..."  # from .env
   url = f"https://api.telegram.org/bot{token}/getMe"
   req = urllib.request.urlopen(url, timeout=10)
   data = json.loads(req.read().decode())
   print(data["ok"])  # must be True
   ```

3. **Test python-telegram-bot directly** (bypasses Gateway completely):
   ```bash
   cd /root/.hermes/hermes-agent
   source venv/bin/activate
   python3 -c "
   import asyncio
   with open('/root/.hermes/.env') as f:
       for line in f:
           if line.startswith('TELEGRAM_BOT_TOKEN='):
               token = line.split('=', 1)[1].strip().strip(\"'\").strip('\"')
               break
   from telegram import Bot
   async def t():
       me = await Bot(token=token).get_me()
       print(f'OK: @{me.username}')
   asyncio.run(t())
   "
   ```

   If steps 2-3 work but the gateway doesn't, the `TelegramFallbackTransport` is the culprit.

4. **Test port connectivity to Telegram IPs:**
   ```bash
   timeout 5 bash -c 'echo > /dev/tcp/149.154.167.220/443' && echo "OK" || echo "FAIL"
   timeout 5 bash -c 'echo > /dev/tcp/149.154.166.110/443' && echo "OK" || echo "FAIL"
   ```

## Fix

Add to `~/.hermes/.env` (or `~/.hermes/profiles/<name>/.env` for profile gateways):
```
HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=true
```

Then reset and restart:
```bash
systemctl reset-failed hermes-gateway.service
hermes gateway restart --system
```

Verify in log:
```
[Telegram] Telegram fallback-IP transport disabled via env
[Telegram] Connected to Telegram (polling mode)
✓ telegram connected
```

## Profile-specific Gateways

Each profile with its own Telegram bot needs the same fix applied to its own `.env`:

| Profile | Service | .env path | Bot |
|---------|---------|-----------|-----|
| main | `hermes-gateway.service` | `~/.hermes/.env` | @myhermster_bot |
| news | `hermes-gateway-hermes-news.service` | `~/.hermes/profiles/hermes-news/.env` | @hermster_news |
| lang | `hermes-gateway-hermes_lang.service` | `~/.hermes/profiles/hermes_lang/.env` | (lang bot) |
| trading | `hermes-gateway-hermes_trading.service` | `~/.hermes/profiles/hermes_trading/.env` | (trading bot) |

The systemd Drop-In (99-restart-limit.conf) must also be created per-service:
```bash
mkdir -p /etc/systemd/system/hermes-gateway-<profile>.service.d
# copy 99-restart-limit.conf into it
systemctl daemon-reload
systemctl reset-failed hermes-gateway-<profile>.service
systemctl restart hermes-gateway-<profile>.service
```

## Cron Scheduler Dependency

The Hermes cron scheduler runs **inside the gateway process**. If the gateway is down:
- Profile cron jobs (news at 06:00, lang, trading scans) will NOT run
- `hermes cron list` shows jobs but they won't tick
- Delivery back to Telegram fails because the bot is disconnected

This is why a gateway watchdog is essential for profile setups with cron jobs.
