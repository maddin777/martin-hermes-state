# LLM API `content: null` — NoneType `.strip()` Pattern

## Problem

OpenRouter (und andere OpenAI-kompatible APIs) liefern gelegentlich `content: null`
im `message`-Objekt der Response, z.B.:

```json
{
  "choices": [{
    "message": {
      "content": null,
      "role": "assistant"
    }
  }]
}
```

Der direkte Zugriff `data["choices"][0]["message"]["content"].strip()` crasht dann
mit `AttributeError: 'NoneType' object has no attribute 'strip'`.

## Fix-Pattern

Immer `.get("content")` + None-Guard verwenden:

```python
# ❌ CRASHT bei content: null
text = data["choices"][0]["message"]["content"].strip()

# ✅ Sicher — None-Guard
msg_content = data["choices"][0]["message"].get("content")
if not msg_content:
    log.warning("LLM content is None — skipping")
    return default_value  # je nach Kontext
text = msg_content.strip()
```

## Betroffene Files (gefixt 06.07.2026)

| File | Line | Fix |
|------|------|-----|
| `breaking_news_monitor.py` | 85 | `.get("content")` + `return 0.5, ""` |
| `social_scanner.py` | 58 | `.get("content")` + `return []` |
| `llm_validator.py` | 62 | `.get("content")` + `return "UNCERTAIN"` |
| `signal_extractor.py` | 95 | `.get("content")` + `raise KeyError` |
| `source_lifecycle.py` | 366 | `.get("content")` + `continue` |
| `thematic/weekly_review.py` | 176 | `.get("content")` + `return default` |

## Wann tritt das auf?

- OpenRouter Timeout (Modell antwortet nicht rechtzeitig)
- Rate-Limit erreicht (429 → `content: null`)
- Modell bricht intern ab (Tool-Call-Versuch, Safety-Filter)
- Provider-Wechsel (OpenRouter routet auf anderes Modell um)

## Prävention bei NEUEN Scripts

Jeder LLM-API-Call im Trading-System muss dieses Pattern verwenden.
Bei Code-Review auf `["content"].strip()` achten — das ist ein 100%iger
Crash bei null-content.