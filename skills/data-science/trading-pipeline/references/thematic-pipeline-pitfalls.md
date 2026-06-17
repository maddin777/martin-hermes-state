# Thematic Pipeline Pitfalls

## PM Scanner — `NameError: name 'db_connect' is not defined`

**Symptom:**
```
File ".../thematic/prediction_market_scanner.py", line 26, in _db_connect
    con = db_connect()
NameError: name 'db_connect' is not defined. Did you mean: '_db_connect'?
```

**Root Cause:** `prediction_market_scanner.py` definiert eine eigene `_db_connect()`-Wrapper-Funktion die `db_connect()` aufruft, aber `from config import db_connect` fehlt in den Imports.

**Fix:** `from config import db_connect` in die Imports von `prediction_market_scanner.py` einfügen (nach `from thematic.lib import ...`).

## Theme Discovery — `database is locked` (DB-Lock-Kaskade)

**Symptom:**
```
File ".../thematic/theme_discovery.py", line 41, in _persist_news
    con.execute("""...""")
sqlite3.OperationalError: database is locked
```

**Root Cause:** Ein vorheriges Script (z.B. PM Scanner) ist gecrasht und hat eine offene SQLite-Connection hinterlassen. Theme Discovery versucht dann zu schreiben und bekommt Lock.

**Fix:** Nicht direkt behebbar — das crashed Script muss zuerst gefixt werden (siehe PM Scanner). Danach läuft Theme Discovery sauber.

## Finnhub API — 403 Forbidden

**Symptom:** Alle Finnhub-API-Calls geben 403 zurück.

**Diagnose:** Test mit:
```bash
curl -s "https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token=$(grep FINNHUB_API_KEY /root/.hermes/profiles/hermes_trading/.env | cut -d= -f2)"
```

**Fix:** Neuen API-Key auf finnhub.io holen und in der `.env` ersetzen.

## Thematic Pipeline Gesamt-Log

Log-Datei: `/root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log`

System crontab Einträge (Mo-Fr):
- `30 2` — prediction_market_scanner.py
- `0 3` — thematic_pipeline.py  
- `0 10` — drawdown_monitor.py
- `30 15` — thesis_monitor.py