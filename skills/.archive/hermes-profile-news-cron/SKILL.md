---
name: hermes-profile-news-cron
description: Create isolated hermes-news profile + daily Cron for int. DE News-Briefing. Covers .env setup, gateway conflict resolution, TG channel config, cron syntax. Reusable for any isolated profile.
category: productivity
---

# hermes-news Profile + Cron Setup

**Trigger:** User wants isolated daily agent profile (News, Lang, Trading, etc.) with Telegram delivery.

## CRITICAL Execution Order

```
# 1. Create profile
hermes profile create <name>

# 2. Copy .env FIRST (empty by default, gateway needs it!)
cp /root/.hermes/.env /root/.hermes/profiles/<name>/.env
# Edit: TELEGRAM_BOT_TOKEN=<SEPARATE_BOT>  # MUST differ from main!
# Edit: TELEGRAM_HOME_CHANNEL=<id>  # Must include -100 prefix for channels
# Ensure OPENROUTER_API_KEY is set (actual key, not comment)

# 3. Set model (interactive-only command needs workaround)
<name> model set <model> --provider openrouter

# 4. Write SOUL.md (no restart needed)
# 5. Kill conflicting gateways first
pkill -f gateway

# 6. Install + start gateway service
sudo <name> gateway install --system --run-as-user root
sudo systemctl restart hermes-gateway-<name>

# 7. Create cron (schedule positional first!)
<name> cron create "0 6 * * *" "<prompt>" --name <job> --deliver telegram

# 8. Test
<name> cron run <job_id>
```

## PITFALLS (earned through hours of debugging)

1. **Telegram bot token CONFLICT:** Two gateways CANNOT share one bot token. Error: "Telegram bot token already in use (PID XXXX)". Fix: kill old gateway or use separate bot per profile.

2. **Profile .env is EMPTY by default.** Cron fails with "No inference provider configured" until OPENROUTER_API_KEY exists in profile .env. Main .env does NOT auto-apply to profiles.

3. **TG Channel ID needs -100 prefix:** Channel IDs like `1003687061880` must be `-1003687061880`. Get via @userinfobot in channel. Private DM IDs are just numeric (e.g. 216051232).

4. **Bot must be Admin in channel** with "Nachrichten posten" permission. Kicked bot = Forbidden errors on send.

5. **Gateway systemd vs manual:** PID 1106 running manual gateway blocks systemd service. Always `pkill -f gateway` before starting service.

6. **Cron needs gateway RUNNING.** Cron silently fails if gateway down. Verify with gateway status command.

7. **`hermes model` is interactive-only.** Use `hermes-news model set <model> --provider openrouter` for scripts.

8. `Cron create` syntax strict: Schedule positional FIRST, prompt SECOND. No --schedule flag. No --repeat flag (omit for forever).
9. **Provider‑specific API key**: Wenn ein Provider wie `xiaomi` verwendet wird, muss in `.env` ein gültiger `XIAOMI_API_KEY` stehen. Ohne diesen Schlüssel kommt ein 401‑Fehler (Invalid API Key) und der Cron‑Job erzeugt kein Ergebnis.
10. **Delivery‑Einstellung**: Für Telegram‑Ausgabe muss im Cron‑Job‑Eintrag `"delivery": "telegram"` (oder `--deliver telegram` beim `cron create`) gesetzt sein, sonst bleibt das Ergebnis nur als Datei liegen.
11. **Gateway‑Neustart nach Änderungen**: Nach Änderungen an `.env`, `config.yaml` oder `jobs.json` immer `systemctl restart hermes-gateway-<profile>` ausführen, sonst nutzt der laufende Prozess alte Werte.

## Debugging Sequence

1. Bot works? Test with curl sendMessage to channel.
2. Gateway running? Check ps/grep and gateway status.
3. Cron last run error? Check cron list output.
4. Cron output files? Check profile cron output dir.
5. Gateway logs? Check service journal last 20 lines.
6. Profile .env has OPENROUTER_API_KEY and correct TELEGRAM_BOT_TOKEN?
