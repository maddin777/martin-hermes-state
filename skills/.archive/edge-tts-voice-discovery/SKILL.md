---
name: edge-tts-voice-discovery
description: List and test Microsoft Edge TTS voices via Python edge-tts. Useful for finding voices for specific languages (German DE, etc.), testing quality, and configuring Hermes TTS.
---

# Edge TTS Voice Discovery

## List all voices

```python
python3 -c "
import asyncio, edge_tts
async def f():
    v = await edge_tts.list_voices()
    for x in v: print(x['ShortName'], '|', x['Locale'], '|', x.get('Gender',''))
asyncio.run(f())
"
```

Filter by locale (German):
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

## Install edge-tts if missing

```bash
pip install edge-tts
```

## Test a voice (save to file)

```python
python3 -c "
import asyncio, edge_tts
async def tts():
    c = edge_tts.Communicate('Test text here', voice='VOICE_SHORT_NAME')
    await c.save('/root/.hermes/audio_cache/test_voice.ogg')
asyncio.run(tts())
"
```

## Known good German voices (as of 2026-04)

| ShortName | Locale | Gender | Notes |
|-----------|--------|--------|-------|
| de-DE-FlorianMultilingualNeural | de-DE | Male | Best quality, multilingual |
| de-DE-SeraphinaMultilingualNeural | de-DE | Female | Multilingual |
| de-DE-ConradNeural | de-DE | Male | Standard |
| de-DE-KatjaNeural | de-DE | Female | Standard |
| de-DE-KillanNeural | de-DE | Male | Standard |
| de-AT-IngridNeural | de-AT | Female | Austrian |
| de-AT-JonasNeural | de-AT | Male | Austrian |
| de-CH-JanNeural | de-CH | Male | Swiss |
| de-CH-LeniNeural | de-CH | Female | Swiss |

## Configure in Hermes config.yaml

```yaml
tts:
  provider: edge
  edge:
    voice: de-DE-FlorianMultilingualNeural
voice:
  auto_tts: true  # auto-reply with TTS on Telegram
```

## Pitfalls

- **YAML patch with `\n` strings:** Using `\n` inside quoted YAML strings produces literal backslash-n, not a newline. Full file rewrite is safer than patch for multiline YAML edits.
- **MultilingualNeural voices:** Generally better quality and more natural intonation than standard voices. Prefer these when available.
- **edge-tts is free, no API key needed.**
