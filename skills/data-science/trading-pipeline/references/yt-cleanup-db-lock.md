# YouTube Cleanup DB Lock: Inter-Cron-Job Cascade

## Problem

`yt_channel_monitor.py` crasht in `cleanup_db()` mit `sqlite3.OperationalError: database is locked`, obwohl `config.db_connect()` WAL mode + `busy_timeout=30000` setzt.

**Symptom im Dashboard:** YouTube Scan rot, restliche Pipeline (KI Analyse, Screener, Watchlist, Technicals) läuft durch.

## Root Cause

Die Pipeline-Jobs laufen als **separate systemd-Crontab-Jobs**, nicht als Subprozesse des Orchestrators:

```
02:00 fundamental_data.py  → 03:00 social_scanner.py  → 03:30 trading_pipeline.py
```

Wenn `fundamental_data.py` eine DB-Transaktion zu lange offen hält (z.B. durch Transaction-in-Loop-Pattern mit API-Calls), blockiert das den `social_scanner.py`. Wenn der `social_scanner.py` dann crasht oder seine letzte Transaktion nicht committed, **pöpelt der Lock weiter**. Die Pipeline startet um 03:30 und `yt_channel_monitor.py`'s `cleanup_db()` (der erste DB-Write der Pipeline) crasht sofort mit `database is locked`.

**Kaskade:**
1. `fundamental_data.py` (02:00) → hält Lock zu lange → `social_scanner.py` crasht
2. `social_scanner.py` (03:00) → crasht mit Lock → **lässt offene Transaktion**
3. `trading_pipeline.py` (03:30) → `yt_channel_monitor.py` → `cleanup_db()` → `database is locked`

## Diagnose

```bash
# 1. Prüfen ob social_scanner sauber beendet wurde
grep -A100 "YYYY-MM-DD 03:00:01.*social_scanner START" cron.log | grep -E "DONE|ERROR|✅|❌|database is locked"

# 2. Prüfen ob fundamental_data sauber beendet wurde
grep -A200 "YYYY-MM-DD 02:00:01.*fundamental_data START" cron.log | grep -E "DONE|ERROR|abgeschlossen|database is locked"

# 3. YouTube Scan Traceback
grep -B5 -A15 "YouTube Scan ERROR" cron.log | grep -E "cleanup_db|Traceback|database is locked"
```

**Unterscheidung zum Transaction-in-Loop-Pattern:** Der Fehler tritt beim **ersten** Pipeline-Schritt auf (YouTube Scan), nicht mittendrin. Das deutet auf einen Lock von einem **vorherigen Cron-Job** hin, nicht auf einen internen Loop-Bug.

## Fix (10.07.2026)

`cleanup_db()` in `yt_channel_monitor.py` hat jetzt:

```python
def cleanup_db(con):
    # Hoher busy_timeout + Retry
    con.execute("PRAGMA busy_timeout=120000;")  # 120s statt 30s
    max_retries = 3
    for attempt in range(max_retries):
        try:
            result1 = con.execute("""UPDATE videos SET transcript=NULL ...""")
            result2 = con.execute("""DELETE FROM videos WHERE created_at < ...""")
            con.commit()
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                print(f"⚠ DB-Lock beim Cleanup (Versuch {attempt+2}/{max_retries}), warte 10s...")
                con.rollback()
                time.sleep(10)
            else:
                # Letzter Versuch fehlgeschlagen — gracefully skip
                con.rollback()
                return
```

**Was der Fix macht:**
- `busy_timeout` auf 120s erhöht (wartet länger auf den Lock)
- 3 Retry-Versuche mit 10s Pause — falls der Lock nach 30s+ immer noch besteht
- `rollback()` im Fehlerfall — keine offenen Transaktionen mehr
- Wenn alle 3 Versuche fehlschlagen → `return` (cleanup wird übersprungen, kein Crash)

## Prävention

- Pipeline-Jobs zeitlich staffeln: `fundamental_data` (02:00) → `social_scanner` (03:00) → `trading_pipeline` (03:30) — 60min Abstand pro Schritt
- `busy_timeout` in `db_connect()` ist 30s — für manche Lock-Szenarien zu kurz
- Jeder Pipeline-Schritt sollte `cleanup()` mit Retry-Logik haben, nicht nur `yt_channel_monitor.py`
- Langfristig: alle Pipeline-Schritte in den Orchestrator integrieren (statt separate Cron-Jobs), damit Lock-Kaskaden vermieden werden