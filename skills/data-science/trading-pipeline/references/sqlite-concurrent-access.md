# SQLite Locking: WAL, busy_timeout, Lock-Kaskaden

Topic-Referenz für `database is locked`. Das Pipeline-Prinzip steht in `SKILL.md`
(`config.db_connect()` setzt WAL + `busy_timeout=30s` + `row_factory` zentral).

## 1. Config-Grundlage

`database is locked` heißt: eine Verbindung hält eine aktive Transaktion, während eine andere
zugreifen will. Defaults sind Worst-Case: `journal_mode=delete` (nur ein Writer, Reader
blockieren Writer) und `busy_timeout=0` (kein Retry).

```bash
sqlite3 /path/to/database.db "PRAGMA journal_mode=WAL;"      # einmalig, persistent
sqlite3 /path/to/database.db "PRAGMA wal_autocheckpoint=500;"
```

```python
con = sqlite3.connect("/path/to/database.db")
con.execute("PRAGMA busy_timeout=5000")   # connection-level, NICHT persistent
con.row_factory = sqlite3.Row
```

Verification: `PRAGMA journal_mode;` → `wal`, `PRAGMA busy_timeout;` → `5000` (nur Session),
`PRAGMA wal_autocheckpoint;` → `500`.

Pitfalls: `busy_timeout` bei jeder neuen Verbindung setzen (auch in Loops/Subprozessen); WAL
braucht Dateisystem-Support (ext4/xfs/btrfs/zfs ok, NFS ohne lockd nicht); `.db-wal`/`.db-shm`
nach Crash löschbar, wenn keine Verbindung offen ist; offene Reader verhindern Checkpoints.

## 2. Transaction-in-Loop mit API-Calls (häufigste Ursache)

```python
# FALSCH: Transaction bleibt über den API-Call offen → Lock für Minuten
for item in items:
    data = requests.get(url, timeout=10)
    con.execute("INSERT INTO t VALUES (?)", (data,))
con.commit()

# RICHTIG: commit pro Item, keine offene Transaction während des API-Calls
for item in items:
    data = requests.get(url, timeout=10)
    con.execute("INSERT INTO t VALUES (?)", (data,))
    con.commit()
```

Trade-off: keine Batch-Atomicität — bei Crash nach Item 3 von 20 sind 3 committed. Für
Logging-/Scraping-Daten irrelevant.

Review-Checkliste für neue Scripts:
1. Schleife mit `INSERT/UPDATE/DELETE`? → `commit()` **innerhalb** der Schleife.
2. API-Call (`requests`, yfinance, LLM) zwischen `execute` und `commit`? → sofort fixen.
3. `commit()` erst am Funktionsende, aber API-Calls im Loop? → obiges Pattern.

Historisch betroffene Funktionen (alle gefixt): `fundamental_data.fetch_fred_data`,
`fetch_insider_trades`, `fetch_pcr`; `social_scanner.fetch_rss_feeds`, `fetch_twitter`.
Bereits korrekt: `yt_channel_monitor` (commit per Video), `signal_extractor` (per Video),
`active_exit_check` (per Position-Close).

## 3. Inter-Cron-Job-Kaskade

Die Pipeline-Jobs sind **getrennte Crontab-Jobs**, keine Subprozesse des Orchestrators. Hält
`fundamental_data` (01:30) oder `social_scanner` (02:00) eine Transaktion offen und crasht,
blockiert das den nächsten Job — bis hin zur ganzen Pipeline.

Zwei Crash-Stellen im YouTube-Scan, unterscheidbar am Schadensbild:

| Stelle | Verhalten | Symptom |
|--------|-----------|---------|
| `cleanup_db()` | 3 Retries + 120 s busy_timeout | 1 ❌ (nur YouTube Scan) |
| INSERT in `main()` | kein try/except | **4 ❌** (YouTube + Screener + Watchlist + Signal Manager) |

**Regel:** 4 rote Pipeline-Schritte nicht einzeln debuggen — den INSERT-Crash als Ursache
suchen. Der Fehler tritt beim **ersten** Schritt auf, nicht mittendrin; das unterscheidet ihn
von einem internen Loop-Bug.

Vier Ebenen, die zusammen greifen (alle implementiert):

1. `busy_timeout=120000` in `init_db()` der Lock-anfälligen Scripts (30 s Default reicht nicht,
   wenn vorgelagerte Jobs den Lock halten).
2. `PRAGMA wal_checkpoint(TRUNCATE)` am Pipeline-Start — räumt Transaktionen gecrashter
   Vorgänger aus dem WAL.
3. `finally: con.rollback()` + `close()` in allen DB-Scripts — kein Lock-Bleeding nach Crash.
4. Schedule-Puffer: 01:30 / 02:00 / 03:30 statt 02:00 / 03:00 / 03:30 (90 min pro Schritt).

Verifikation:

```bash
grep "WAL-Checkpoint" data/cron.log
grep -E "❌|✅" data/cron.log | tail -10
crontab -l | grep -E "fundamental|social|trading_pipeline"   # 01:30, 02:00, 03:30
```

Langfristig: Pipeline-Schritte in den Orchestrator integrieren, statt als parallele Cron-Jobs.
Post-Mortem-Hintergrund: `trading-post-mortem-juli-2026.md`.
