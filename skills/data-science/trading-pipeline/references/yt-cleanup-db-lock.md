# YouTube Cleanup DB Lock: Inter-Cron-Job Cascade

## Problem

`yt_channel_monitor.py` crasht mit `sqlite3.OperationalError: database is locked`, obwohl `config.db_connect()` WAL mode + `busy_timeout=30000` setzt.

**Ursprüngliches Symptom (10.07.):** YouTube Scan rot, restliche Pipeline läuft durch.

**Erweitertes Symptom (13.07.):** YouTube Scan rot → **Screener Source, Watchlist Update, Signal Manager ebenfalls rot**. Der YouTube Scan-Crash im Haupt-Loop (INSERT) lässt eine offene Transaktion zurück → **Cascading DB Locks killen die gesamte Pipeline**. 4 von 7 Pipeline-internen Jobs sind ❌ in cron-health-daily.

## Root Cause

Die Pipeline-Jobs laufen als **separate systemd-Crontab-Jobs**, nicht als Subprozesse des Orchestrators:

```
02:00 fundamental_data.py  → 03:00 social_scanner.py  → 03:30 trading_pipeline.py
```

Wenn `fundamental_data.py` eine DB-Transaktion zu lange offen hält (z.B. durch Transaction-in-Loop-Pattern mit API-Calls), blockiert das den `social_scanner.py`. Wenn der `social_scanner.py` dann crasht oder seine letzte Transaktion nicht committed, **pöpelt der Lock weiter**. Die Pipeline startet um 03:30 und crasht.

**Kaskade:**
1. `fundamental_data.py` (02:00) → hält Lock zu lange → `social_scanner.py` crasht
2. `social_scanner.py` (03:00) → crasht mit Lock → **lässt offene Transaktion**
3. `trading_pipeline.py` (03:30) → `yt_channel_monitor.py` crasht

**Zwei Crash-Stellen im YouTube Scan (wichtig für Diagnose):**

| Stelle | Funktion | Hat Retry? | Folgen |
|--------|----------|-----------|--------|
| **cleanup_db()** (Zeile 148-174) | UPDATE/DELETE alte Videos | ✅ Ja, 3 Retries + 120s busy_timeout | Graceful skip → Pipeline läuft weiter |
| **INSERT in main()** (Zeile 218) | INSERT neuer Videos | ❌ Nein, kein try/except | **CRASH** → offene Transaktion → **Cascading DB Lock** |

**Der `cleanup_db()`-Fix (10.07.) deckt nur die erste Stelle ab.** Wenn cleanup_db() graceful skipped, läuft die Pipeline weiter zum INSERT bei Zeile 218 — und crasht dort ohne Retry. Der Crash hinterlässt eine offene Transaktion, die alle nachfolgenden Pipeline-Schritte (Screener Source, Watchlist Update, Signal Manager) mit `database is locked` killt.

**Symptom-Unterschied:**

| Szenario | cron-health-daily | Ursache |
|----------|-------------------|---------|
| Crash in cleanup_db() | 1 ❌ (YouTube Scan) | cleanup_db() 3 Retries erschöpft |
| Crash in INSERT (Zeile 218) | **4 ❌** (YouTube Scan + Screener + Watchlist + Signal Manager) | Cascading Lock nach INSERT-Crash |

## Diagnose

```bash
# 1. Prüfen ob social_scanner sauber beendet wurde
grep -A100 "YYYY-MM-DD 03:00:01.*social_scanner START" cron.log | grep -E "DONE|ERROR|✅|❌|database is locked"

# 2. Prüfen ob fundamental_data sauber beendet wurde
grep -A200 "YYYY-MM-DD 02:00:01.*fundamental_data START" cron.log | grep -E "DONE|ERROR|abgeschlossen|database is locked"

# 3. YouTube Scan Traceback — welche Stelle crasht?
grep -B5 -A15 "YouTube Scan ERROR" cron.log | grep -E "cleanup_db|Traceback|INSERT|line 218|database is locked"

# 4. Cascading Lock erkennen: wenn 2+ Pipeline-Schritte rot sind, ist es ein INSERT-Crash (Zeile 218)
#    1 ❌ = cleanup_db() Crash (nur YouTube Scan)
#    4 ❌ = INSERT Crash (YouTube Scan + Screener + Watchlist + Signal Manager)
grep -E "❌|ERROR" cron.log | grep -v "⚠️"
```

**Unterscheidung zum Transaction-in-Loop-Pattern:** Der Fehler tritt beim **ersten** Pipeline-Schritt auf (YouTube Scan), nicht mittendrin. Das deutet auf einen Lock von einem **vorherigen Cron-Job** hin, nicht auf einen internen Loop-Bug.

## Fix (vollständig, 13.07.2026)

**4-Ebenen-Prävention, alle implementiert:**

### Ebene 1: `busy_timeout=120s` in `init_db()`

```python
def init_db():
    con = db_connect()
    # 120s busy_timeout — der Default (30s aus config.db_connect) reicht nicht
    # wenn vorgelagerte Prozesse (social_scanner, fundamental_data) den Lock halten
    con.execute("PRAGMA busy_timeout=120000;")
    ...
```

**Wirkung:** Der INSERT bei Zeile 218 wartet jetzt 120s statt 30s auf Lock-Freigabe. Kurze Locks von vorgelagerten Prozessen werden überbrückt.

### Ebene 2: WAL-Checkpoint am Pipeline-Start

In `trading_pipeline.py` main(), direkt nach TRADING PIPELINE START:

```python
import sqlite3
from config import db_connect
con = db_connect()
con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
con.close()
```

**Wirkung:** Räumt stale WAL-Einträge von gecrashten Vorgängerprozessen auf. Wenn `social_scanner` oder `fundamental_data` eine offene Transaktion im WAL hinterlassen haben, wird diese beim Checkpoint bereinigt.

### Ebene 3: `finally: con.rollback()` in allen DB-Scripts

```python
finally:
    con.rollback()  # Offene Transaktion schließen — verhindert DB-Lock für nachfolgende Prozesse
    con.close()
```

**Wirkung:** Selbst wenn ein Script crasht (z.B. social_scanner bei API-Timeout), wird die offene Transaktion gerollbackt bevor die Verbindung geschlossen wird. Kein Lock-Bleeding mehr.

**Betroffene Scripts:** `social_scanner.py`, `fundamental_data.py`

### Ebene 4: Schedule-Puffer

```diff
- fundamental_data: 02:00 → 01:30  (90min Puffer vor social_scanner)
- social_scanner:    03:00 → 02:00  (90min Puffer vor Pipeline 03:30)
```

**Wirkung:** Jeder Job hat 90min Zeit zum Durchlaufen bevor der nächste startet. Kein Overlap mehr, selbst wenn ein Job 30min länger braucht als erwartet.

### Verifikation

```bash
# Zeigt "✅ WAL-Checkpoint: offene Transaktionen bereinigt" am Pipeline-Start
grep "WAL-Checkpoint" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log

# Alle 7 Pipeline-Schritte sollten ✅ sein
grep -E "❌|✅" /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10

# System crontab checken
crontab -l | grep -E "fundamental|social|trading_pipeline"
# → Sollte 01:30, 02:00, 03:30 zeigen
```

## Prävention

- Pipeline-Jobs zeitlich staffeln: `fundamental_data` (02:00) → `social_scanner` (03:00) → `trading_pipeline` (03:30) — 60min Abstand pro Schritt
- `busy_timeout` in `db_connect()` ist 30s — für manche Lock-Szenarien zu kurz. **Alle Scripts, die INSERT/UPDATE/DELETE machen, brauchen entweder try/except oder `busy_timeout>60000` in `init_db()`.**
- Jeder Pipeline-Schritt sollte try/except um seine DB-Writes haben, nicht nur `cleanup_db()` in `yt_channel_monitor.py`
- **Cascading Lock erkennen:** Wenn 4 Pipeline-Schritte rot sind → nicht einzeln debuggen, sondern den YouTube Scan INSERT-Crash als Ursache suchen
- Langfristig: alle Pipeline-Schritte in den Orchestrator integrieren (statt separate Cron-Jobs), damit Lock-Kaskaden vermieden werden