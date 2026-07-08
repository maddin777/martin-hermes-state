# Thematic Pipeline Pitfalls

## PM Scanner — `result["content"] is None` in `parse_json_response`

**Symptom:**
```
File ".../thematic/lib/llm_client.py", line 178, in parse_json_response
    text = result["content"].strip()
AttributeError: 'NoneType' object has no attribute 'strip'
```

**Root Cause:** OpenRouter liefert manchmal `content: null` (Refusal, Filter, Timing). `call_llm` gibt das ungeprüft weiter, `parse_json_response` macht `.strip()` auf None.

**Fix (eingespielt 03.07.2026):** In `llm_client.py` / `parse_json_response()` None-Check vor `.strip()`:
```python
content = result.get("content")
if content is None:
    return default or {}
text = content.strip()
```

**Diagnose:** Letzter erfolgreicher PM-Durchlauf im Log checken:
```bash
grep "PM Scanner.*DONE" /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log | tail -3
```

## Theme Discovery — `database is locked` (Kaskade nach PM-Crash)

**Symptom:**
```
File ".../thematic/theme_merge_engine.py", line 104, in insert_new_theme
    con.execute("""...""")
sqlite3.OperationalError: database is locked
```

**Root Cause:** PM Scanner crasht (z.B. None-Content) → `con.commit()` nie erreicht → offene WAL-Transaktion. Theme Discovery startet direkt danach, nutzt raw `sqlite3.connect()` OHNE `busy_timeout` → Lock beim ersten Write.

**Fix (eingespielt 03.07.2026):** `theme_discovery.py` nutzt jetzt `config.db_connect()` statt raw `sqlite3.connect()`. Die zentrale `db_connect()` hat WAL mode + `busy_timeout` (wartet und retryt statt sofort zu failen).

**Prävention:** Alle neuen thematic-Scripts müssen `from config import db_connect` verwenden, nicht raw `sqlite3.connect()`.

## Finnhub API — 403 Forbidden / Rate-Limited

**Symptom:** Alle Finnhub-API-Calls geben 403 zurück.

**Diagnose:**
```bash
curl -s "https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token=$(grep FINNHUB_API_KEY /root/.hermes/profiles/hermes_trading/.env | cut -d= -f2)"
```

**Fix:** Neuen API-Key auf finnhub.io holen und in `.env` ersetzen.

**Hinweis:** 403 tritt auch bei Rate-Limits auf (50 Calls/60s). Der Retry-Mechanismus in `factor_ranker.py` versucht 3× mit Backoff, gibt dann auf. Bei anhaltenden 403er → Key prüfen, nicht Rate-Limit vermuten.

## Thematic Pipeline Log

- **Log-Datei:** `/root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log`
- **System crontab (Mo–Fr):**
  - `30 2` — prediction_market_scanner.py (PM Scanner)
  - `0 3` — thematic_pipeline.py (Haupt-Pipeline: PM → Theme → Beneficiary → Fundamental → Factor → Technical → Thesis → Briefing)
  - `0 10` — drawdown_monitor.py
  - `30 15` — thesis_monitor.py
  - `0 8 * * 0` — weekly_review.py

  **Prüfung nach einem Lauf:**
```bash
tail -20 /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log
```