# sqlite3.Row `.get()` Pitfall

## Das Problem

`sqlite3.Row` ist KEIN dict. Es unterstützt `row["key"]` und `"key" in row.keys()`, aber NICHT `row.get("key", default)`.

```python
from config import db_connect
con = db_connect()
row = con.execute("SELECT * FROM positions LIMIT 1").fetchone()

# CRASHT: AttributeError: 'sqlite3.Row' object has no attribute 'get'
val = row.get("asset_type", "STANDARD")

# FUNKTIONIERT:
val = row["asset_type"] if "asset_type" in row.keys() else "STANDARD"
```

## Reale Crashs in diesem System

### 19.06.2026 — asset_type Column neu eingeführt

**Symptom:** Signal Manager crasht mit:
```
File "signal_manager.py", line 376, in check_open_positions
    pos_asset_type = pos.get("asset_type") or "STANDARD"
AttributeError: 'sqlite3.Row' object has no attribute 'get'
```

**Auswirkung:** Signal Manager exit 1 -> keine Exit-Checks für offene Positionen (Stops, Trailing, Partial TP aktualisieren nicht). Pipeline meldet "Signal Manager fehlgeschlagen - Pipeline laeuft weiter".

**Grund:** Beim Einbau der dynamischen Exit-Regeln wurde `asset_type` per ALTER TABLE in `positions` hinzugefügt. In `check_open_positions()` dann `.get("asset_type")` verwendet — crasht weil Row kein dict ist.

**Fix (beide Dateien):**
```python
# signal_manager.py Zeile 376
pos_asset_type = pos["asset_type"] if "asset_type" in pos.keys() else "STANDARD"

# active_exit_check.py Zeile 142 - gleicher Fix
```

### 08.06.2026 — weekly_trend Spalte

**Symptom:** `AttributeError` bei Zugriff auf `weekly_trend` in `get_technical_score()`.

**Grund:** `cfg.get("weekly_trend", "neutral")` auf einem dict funktioniert. ABER `row.get("weekly_trend", "neutral")` auf einem sqlite3.Row crasht. Der Code war korrekt für Config-Dicts aber crashte auf DB-Rows.

**Fix:** `row["weekly_trend"] if "weekly_trend" in row.keys() else "neutral"`

## Warum passiert das immer wieder

Weil `sqlite3.Row` **fast** wie ein dict aussieht:
- `row["key"]` funktioniert ✅
- `list(row.keys())` funktioniert ✅
- `"key" in row.keys()` funktioniert ✅
- `row.get("key")` CRASHT ❌

Der Name `.get()` suggeriert dict-Verhalten, aber Row implementiert es nicht. Das ist ein häufiger Fallstrick weil Row dict-ähnlich ist aber nicht vollständig dict-kompatibel.

## Neue Spalten sicher hinzufügen

Wenn du eine neue Spalte per ALTER TABLE in `init_db()` hinzufügst:

```python
# 1. Migration in init_db()
if "new_col" not in cols:
    con.execute("ALTER TABLE positions ADD COLUMN new_col TEXT DEFAULT 'default'")
    print("  positions: new_col-Spalte hinzugefügt")

# 2. Zugriff AUF JEDEN FALL mit Keys-Check
row["new_col"] if "new_col" in row.keys() else "default"
```

**ALLE Stellen prüfen** wo auf diese Spalte zugegriffen wird:
- `check_open_positions()` in signal_manager.py
- `main()` in active_exit_check.py
- Evtl. `open_new_positions()` in signal_manager.py
- Evtl. `nightly_eval.py`, `dashboard.py`

## Prävention

- **Kein `row.get()` schreiben** — es gibt kein Szenario wo das auf sqlite3.Row funktioniert. Gewöhn dir an stattdessen `"col" in row.keys() else default` zu tippen.
- **Nach jeder ALTER TABLE:** grep nach `.get(` in signal_manager.py und active_exit_check.py
- **Code-Review vor Deployment:** Wenn du `sqlite3.Row` verwendest, prüfe auf `.get()` Aufrufe