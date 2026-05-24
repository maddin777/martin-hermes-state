---
name: hermes-voice
description: Voice processing for Hermes — TTS provider configuration, voice discovery/testing, and Telegram voice message STT transcription. Covers edge-tts setup, faster-whisper, and Telegram bot integration.
category: media
---

# Hermes Voice

Umbrella for all voice-related Hermes workflows: text-to-speech (TTS) configuration/voice discovery and speech-to-text (STT) transcription from Telegram voice messages.

---

## 1. TTS: Voice Discovery & Configuration

Discover, test, and configure Microsoft Edge TTS voices for Hermes.

### List all voices

```python
python3 -c "
import asyncio, edge_tts
async def f():
    v = await edge_tts.list_voices()
    for x in v: print(x['ShortName'], '|', x['Locale'], '|', x.get('Gender',''))
asyncio.run(f())
"
```

### Filter by locale (German)

```python
python3 -c "
import asyncio, edge_tts
async def f():
    v = await edge_tts.list_voices()
    de = [x for x in v if x['Locale'].startswith('de-')]
    for x in de: print(x['ShortName'], '|', x['Locale'], '|', x.get('Gender',''))
asyncio.run(f())
"
```

### Install edge-tts

```bash
pip install edge-tts
```

### Test a single voice

```python
python3 -c "
import asyncio, edge_tts
async def tts():
    c = edge_tts.Communicate('Test text here', voice='de-DE-FlorianMultilingualNeural')
    await c.save('/root/.hermes/audio_cache/test_voice.ogg')
asyncio.run(tts())
"
```

### Known good German voices

See `references/german-tts-voices.md` for a full table of German voices (DE, AT, CH) with notes.

### Configure in Hermes config.yaml

```yaml
tts:
  provider: edge
  edge:
    voice: de-DE-FlorianMultilingualNeural
voice:
  auto_tts: true  # generates TTS audio file on every response, but does NOT auto-attach to Telegram
```

### Telegram Voice Bubble Delivery

`auto_tts: true` **generates the audio file** to `audio_cache/` on every response but does NOT embed it as a Telegram voice bubble — the MEDIA: tag must be included explicitly in the response text.

**To send a voice bubble to Telegram:**
1. Use the `text_to_speech` tool (returns file_path + `[[audio_as_voice]]` tag)
2. Include `MEDIA:/path/to/file.ogg` in the response text
3. The file must be `.ogg` format for Telegram voice bubble compatibility

**Martin's preference (recorded):**
- Voice bubbles **ONLY** on explicit request ("sag das als Sprachnachricht")
- Voice bubbles **ONLY** when Martin sends a voice message himself (reply in kind)
- Never auto-attach voice bubbles to every response — text is the default delivery

### TTS Pitfalls

- **YAML patch with `\n` strings:** Using `\n` inside quoted YAML strings produces literal backslash-n, not a newline. Full file rewrite is safer than patch for multiline YAML edits.
- **MultilingualNeural voices:** Generally better quality and more natural intonation than standard voices. Prefer these when available.
- **edge-tts is free, no API key needed.**
- **auto_tts + Telegram:** auto_tts generates the file silently — no voice bubble appears unless MEDIA: is explicitly in the response. This is a common confusion point.
- **[[audio_as_voice]] tag:** The `text_to_speech` tool adds this tag automatically. Don't strip it — it's what signals the Telegram gateway to send as a native voice bubble rather than an audio file attachment.

---

## 2. STT: Telegram Voice Message Transcription

Transcribe incoming Telegram voice messages locally using `faster-whisper` and reply with the transcript.

### Trigger

```bash
~/.hermes/skills/media/hermes-voice/scripts/tg_voice_stt.sh
```

The script polls the latest Telegram voice message, downloads it, transcribes with faster-whisper (German `de`), and sends the transcript back as a reply.

### Profiles (hermes-news/lang)

```bash
TOKEN=$(grep TELEGRAM_BOT_TOKEN= ~/.hermes/profiles/hermes-news/.env | cut -d= -f2-)
~/.hermes/skills/media/hermes-voice/scripts/tg_voice_stt.sh "$TOKEN"
```

### Requirements

- `faster-whisper` (installed via pip)
- `jq` (`apt install jq`)
- `TELEGRAM_BOT_TOKEN` in `~/.hermes/.env` or profile `.env`

### STT Pitfalls

- No `jq`: `apt install jq`.
- STT is slow (~30s per minute of audio).
- Multi-voice: manually adjust offset to -1 → -2.
- Auto-hook via cron `*/1 * * * * tg_voice_stt.sh` is heavy on resources.
- Logs: `journalctl -u hermes-gateway -f | grep voice`

---

## 3. Testing the Voice Pipeline

1. Configure TTS in `~/.hermes/config.yaml` as shown above.
2. Test TTS: `text_to_speech(text="Hallo Welt")`
3. For STT: send a voice message to your Telegram bot (@hermster), then run the script.
