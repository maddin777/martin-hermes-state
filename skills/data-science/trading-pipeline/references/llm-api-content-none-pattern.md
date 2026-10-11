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

## Reasoning-Modelle: Budget-Falle (die häufigere Ursache)

Reasoning-Modelle (z.B. DeepSeek v4 / v4.1-flash) zählen das interne Denken gegen
`max_tokens`. Ist das Budget klein, endet die Antwort mit `finish_reason: length` und
`content` ist leer oder abgeschnitten — derselbe Crash-Pfad wie oben.

**Regel:**
- Reine JSON-Extraktion / Klassifikation: `"reasoning": {"enabled": false}` setzen UND `max_tokens` ≥ 1000.
  Ohne Reasoning-Abschaltung reichen selbst 400 Tokens bei langen Prompts nicht.
- Komplexe Analyse (Scout/Analyst): Reasoning bewusst lassen, aber `max_tokens` groß genug wählen und
  `finish_reason == "length"` als eigenen Fehlerfall behandeln (nicht als leeres Ergebnis).
- Smoke-Test vor Rollout mit dem echten Payload des Scripts, nicht mit `max_tokens=20`:
  ein 20-Token-Call zeigt nur, dass das Modell antwortet, nicht dass das Budget reicht.

## Modell-Swap-Verify (Trading)

Vor dem Swap: jede geänderte Datei sichern (`cp` nach `~/.hermes/cache/scratch/`), damit Rollback ein `cp` ist.
Nach dem Swap:
1. Grep auf die alte ID, Live-Dateien filtern. Logs, Caches, `.bak`, Curator-Backups und Migrations-Doku ausschließen (die beschreiben Vergangenheit).
2. Syntax-Gate: `python3 -m py_compile` für Scripts, `json.load` für `jobs.json` und JSON-Configs.
3. Live-Call mit dem echten Payload (Modell, `max_tokens`, Reasoning-Setting) des Scripts. Ein 20-Token-Ping reicht nicht.
4. Nach 1–2 Cron-Läufen `agent.log` auf `PAID lane` / `fallback model` mit altem Namen prüfen. Der Auxiliary-Client kann den alten Modellnamen aus dem Katalog-Cache wählen, obwohl keine Config-Datei ihn enthält. Ein Grep auf Config-Dateien findet das nicht.

## Wann tritt das auf?

- OpenRouter Timeout (Modell antwortet nicht rechtzeitig)
- Rate-Limit erreicht (429 → `content: null`)
- Modell bricht intern ab (Tool-Call-Versuch, Safety-Filter)
- Provider-Wechsel (OpenRouter routet auf anderes Modell um)

## Prävention bei NEUEN Scripts

Jeder LLM-API-Call im Trading-System muss dieses Pattern verwenden.
Bei Code-Review auf `["content"].strip()` achten — das ist ein 100%iger
Crash bei null-content.