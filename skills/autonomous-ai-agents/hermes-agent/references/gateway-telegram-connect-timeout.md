# Telegram Gateway connect timeout — diagnostic transcript

## Symptom

Gateway status shows `failed`, gateway.log repeats:

```
Connecting to telegram...
DoH discovery yielded no new IPs (system DNS: unknown); using seed fallback IPs 149.154.167.220
Telegram fallback IPs active: 149.154.167.220
telegram connect timed out after 30s
Disconnected from Telegram
Gateway failed to connect any configured messaging platform: telegram: telegram connect timed out after 30s
```

## Root cause

The Gateway uses `gateway/platforms/telegram_network.py` → `TelegramFallbackTransport`
to handle cases where `api.telegram.org` isn't reachable directly. The transport:

1. Calls `discover_fallback_ips()` which tries Google DoH + Cloudflare DoH + system DNS
2. When all fail, falls back to the hardcoded seed IP `149.154.167.220` (line 43)
3. The `httpcore` connection to that IP succeeds at TCP level, but the TLS handshake
   through the IP-rewriting transport (`_rewrite_request_for_ip` on line 232) can time out

The core `python-telegram-bot` library works fine over plain `api.telegram.org` —
it's specifically the IP-rewriting fallback transport that fails.

## Diagnosis steps

### 1. Is the bot token valid?

```bash
curl -s "https://api.telegram.org/bot$(grep '^TELEGRAM_BOT_TOKEN=' ~/.hermes/.env | cut -d= -f2)/getMe"
```

Expected: `{"ok":true,"result":{"id":...,"username":"..."}}`
Error `401 Unauthorized` → token expired or wrong.

### 2. Can python-telegram-bot connect directly?

```bash
cd ~/.hermes/hermes-agent
source venv/bin/activate
python3 -c "
import asyncio
with open('/root/.hermes/.env') as f:
    for line in f:
        if line.startswith('TELEGRAM_BOT_TOKEN='):
            token = line.split('=', 1)[1].strip().strip(\"'\").strip('\"')
            break
from telegram import Bot
async def test():
    me = await Bot(token=token).get_me()
    print(f'OK: @{me.username}')
asyncio.run(test())
"
```

### 3. Is the seed IP reachable at TCP level?

```bash
timeout 5 bash -c 'echo > /dev/tcp/149.154.167.220/443' 2>&1 && echo "OK" || echo "FAIL"
```

TCP may succeed while the httpx transport still times out.

### 4. What does the log say?

```bash
grep -i "telegram\|fallback\|DoH\|connect time" ~/.hermes/logs/gateway.log | tail -20
```

Key lines to look for:
- `Auto-discovered Telegram fallback IPs` — what IPs were found
- `Telegram fallback-IP transport disabled via env` — fix is active
- `Connected to Telegram` — success
- `telegram connect timed out` — failure

## Fix

Add to `~/.hermes/.env`:

```
HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=true
```

This forces the Gateway to use plain `api.telegram.org` without the
IP-rewriting fallback transport. The transport is only needed on networks
where `api.telegram.org` DNS resolves to a blocked IP (e.g., Russia, China).

Then:

```bash
systemctl reset-failed hermes-gateway
hermes gateway restart --system
```

## Verification

1. `hermes gateway status` → `active (running)`
2. `grep "Connected" ~/.hermes/logs/gateway.log | tail -3` → `Connected to Telegram`
3. `hermes doctor` → `✓ messaging` instead of `⚠ messaging (system dependency not met)`
4. Send a message to your bot on Telegram → should respond

## Source code references

| File | Purpose |
|------|---------|
| `gateway/platforms/telegram_network.py` | `TelegramFallbackTransport`, `discover_fallback_ips()`, `_SEED_FALLBACK_IPS` |
| `gateway/platforms/telegram.py` (lines 1160-1212) | Builds `HTTPXRequest` with or without fallback transport |
| `tools/send_message_tool.py` (lines 1759-1770) | `_check_send_message()` — gates on `is_gateway_running()` |
| `gateway/status.py` | `is_gateway_running()` — checks `{HERMES_HOME}/gateway.pid` |

## Related

- `hermes doctor` shows `messaging (system dependency not met)` when gateway is
  stopped or failed — see `references/doctor-system-dependencies.md`
- Profile-isolated setups (Martin): each profile runs its own gateway with its
  own PID file. The main profile's gateway can be disabled without impacting
  profile gateways.