# LLM Pipeline: Empty Extraction Results

## Scenario

An LLM-powered extraction pipeline processes input (transcripts, articles, feeds) and returns 0 entities/companies/results — even though the input clearly contains them (e.g. company name in video title).

## Checklist

### Phase 1: Has the Pipeline Actually Run?

Check if data ingestion happened:

```sql
-- Check raw data table vs extraction table
SELECT upload_date, status, LENGTH(transcript)
FROM videos WHERE channel = 'target_channel'
ORDER BY upload_date DESC LIMIT 5;

SELECT channel, mention_date, COUNT(*)
FROM watchlist_mentions WHERE channel = 'target_channel'
GROUP BY mention_date ORDER BY mention_date DESC;
```

- Raw data ingested? → Pipeline ran
- Extraction table older than raw data? → Extractor ran but found nothing
- Both tables empty? → Data collection failed/hasn't run

### Phase 2: Is the Model Capable?

Cheap/small models often skip borderline cases:

| Model | JSON Reliability | Entity Finding | Cost |
|-------|-----------------|----------------|------|
| `gemini-2.5-flash-lite` | Medium | Too strict, misses borderline names | ~$0.015/M |
| `deepseek/deepseek-v4-flash` | Good | Finds obscure companies | ~$0.10/M |
| `gpt-4o-mini` | Excellent | Very thorough | ~$0.15/M |
| `gpt-4o` | Excellent | Maximum recall | ~$1/M |

**Fix**: Upgrade model and test one sample input. If the upgrade returns entities, the previous model was the bottleneck.

### Phase 3: Check max_tokens

Most common root cause for truncated/malformed JSON:

```python
# BAD — too low, model cuts off JSON
"max_tokens": 2000

# GOOD — enough room for full JSON
"max_tokens": 4000
```

Symptoms of token truncation:
- JSON ends mid-string (`Unterminated string starting at: line N`)
- JSON ends mid-object
- `Expecting value` at unexpected position
- Random `}` or `]` in output

**Fix**: Increase to 4000+.

### Phase 4: Is the Prompt Too Restrictive?

Compare old vs aggressive prompt patterns:

| Too Restrictive | Better |
|-----------------|--------|
| "Nur explizit erwähnte Unternehmen" | "Auch Unternehmen im Videotitel berücksichtigen" |
| "Wenn keine erkennbar: leeres Array" | "SEI GROSSZÜGIG: Lieber falsches Positives als verpasstes Unternehmen" |
| "Nur börsennotierte" (strict mode) | "JEDES börsennotierte Unternehmen, auch obskure/kleine/unbekannte" |
| Cold, factual tone | Warm, specific instructions about behavior |

**Fix**: Remove "empty array if unsure" clauses. Add "be generous" instructions. Consider entities mentioned in metadata (title, description), not just body text.

### Phase 5: JSON Parsing Robustness

LLMs produce malformed JSON. The pipeline must handle this gracefully:

1. **Basic**: Single `json.loads()`, return empty on failure (LOSES DATA)
2. **Better**: Regex repair before parsing:
   ```python
   import re
   fixed = re.sub(r",\s*}", "}", text)          # trailing comma
   fixed = re.sub(r",\s*]", "]", fixed)          # trailing comma in array
   fixed = re.sub(r"(?<!\\)'(?=[^']*':)", '"', fixed)  # 'key' → "key"
   fixed = re.sub(r":\s*'([^']*)'", r': "\1"', fixed)  # : 'val' → : "val"
   fixed = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', fixed)  # control chars
   ```
3. **Best**: Fallback chain — Primary model → regex repair → fallback model

### Phase 6: Check Logs for API Errors

```bash
grep -E "Fehler|Error|Warn|rate.limit|429|500|timeout|JSON.*Fehler" pipeline.log | tail -20
```

- 429 → rate limited, add delay or quota
- 500 → OpenRouter/provider issue, retry or switch provider
- `JSON Parse Fehler` → malformed model output (see Phase 3 + 5)

## Full Fix Chain (from real session)

```
Symptom: 3 finance videos → 0 companies extracted (signal_extractor.py)
  ├─ Step 1: Checked DB — videos ingested, status=done, no watchlist_mentions → extractor ran, found nothing
  ├─ Step 2: Increased max_tokens 2000→4000 → didn't help alone
  ├─ Step 3: Switched gemini-2.5-flash-lite → deepseek/deepseek-v4-flash → 17 companies for 1/3 videos
  ├─ Step 4: Added JSON regex repair → same 2 videos still failed (malformed JSON from model)
  └─ Step 5: Added gpt-4o-mini fallback (never needed — root cause was max_tokens all along)
```

**Actual root cause**: `max_tokens=2000` truncated the JSON output. `max_tokens=4000` + competent model (DeepSeek V4 Flash) solved it. The fallback chain and aggressive prompt were safety nets.

## Architecture Pattern

```
Data Source (YouTube) → yt-dlp scan → SQLite (raw)
  → LLM extractor (DeepSeek, max_tokens=4000)
    → JSON parse → [fail?] → regex repair → [fail?] → GPT-4o-mini fallback
      → watchlist_mentions table → dashboard
```

Each layer has its own failure mode:
1. **Data collection**: scheduler (Mo-Fr vs weekend), URL format, API access
2. **LLM extraction**: model capability, token limit, prompt design
3. **JSON parsing**: output format, truncation, encoding errors
4. **Pipeline orchestration**: sequential dependencies, error propagation