---
name: telegram-voice-stt
description: Empfängt Telegram Voice Messages (@hermster base/profiles), transkribiert mit faster-whisper (local), sendet Text-Reply. Poll latest.
trigger: TG Voice STT, Sprachnachricht transkribieren
requirements:
  - faster-whisper (installiert)
  - jq (apt install jq)
  - TELEGRAM_BOT_TOKEN in ~/.hermes/.env oder profile .env
output: Transcript → TG Reply + Console
---

# Telegram Voice STT Skill

**Status**: Fertig. Base @hermster (Token ~/.hermes/.env).

## 1. Trigger
- "TG Voice transkribieren"
- `terminal("~/.hermes/skills/social-media/telegram-voice-stt/scripts/tg_voice_stt.sh")`

## 2. Workflow
1. Poll `getUpdates?limit=1` → Latest Voice file_id/chat_id.
2. Download OGG `/tmp/tg_voice.ogg`.
3. `faster-whisper --model base --language de` → Transcript.
4. `sendMessage` Reply: "STT: ...".
5. Cleanup.

## 3. Test
1. **Schick Voice-Nachricht** an @hermster (base).
2. Hier: `terminal("~/.hermes/skills/social-media/telegram-voice-stt/scripts/tg_voice_stt.sh")`
3. Erwartet: "Transcript: Hallo Welt (sent to -ID)"

## 4. Profiles (hermes-news/lang)
```
TOKEN=$(grep TELEGRAM_BOT_TOKEN= ~/.hermes/profiles/hermes-news/.env | cut -d= -f2-)
~/.hermes/skills/social-media/telegram-voice-stt/scripts/tg_voice_stt.sh "$TOKEN"
```

## Pitfalls
- No jq: `apt install jq`.
- STT langsam (~30s/min Audio).
- Multi-Voice: Manuell offset=-1 → -2.
- Auto-Hook: Cron `*/1 * * * * tg_voice_stt.sh` (heavy).
- Logs: `journalctl -u hermes-gateway -f | grep voice`
