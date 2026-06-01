# SQLite Concurrent Access — Full Reference

Detailed reference for setting up WAL mode, busy_timeout, and diagnosing "database is locked" errors in automated data pipeline contexts. Summarized in the umbrella skill's "Layer 0: Database Configuration for Concurrent Access"; this file preserves the full detail.

## Root Cause Analysis

"database is locked" means one connection has an active transaction (read or write) while another connection tries to access the database. The default SQLite configuration is worst-case for concurrent access:

| Setting | Default | Problem |
|---------|---------|---------|
| `journal_mode` | `delete` | Only one writer allowed; readers block writers |
| `busy_timeout` | `0` | No retry — fails immediately on lock contention |

## Fix: WAL Mode + Busy Timeout

### 1. Switch Database to WAL Mode (one-time, persists in DB file)

```bash
sqlite3 /path/to/database.db "PRAGMA journal_mode=WAL;"
```

WAL (Write-Ahead Logging) allows:
- Multiple concurrent readers while a writer is active
- The writer does not block readers
- Much better throughput for mixed read/write workloads

Also set a reasonable autocheckpoint:

```bash
sqlite3 /path/to/database.db "PRAGMA wal_autocheckpoint=500;"
```

### 2. Set Busy Timeout (per-connection, must be set at connect time)

Add `PRAGMA busy_timeout=5000` after EVERY `sqlite3.connect()` call:

```python
import sqlite3

con = sqlite3.connect("/path/to/database.db")
con.execute("PRAGMA busy_timeout=5000")  # Wait 5s instead of failing immediately
```

The `busy_timeout` is a **connection-level** setting — it does NOT persist in the DB file. Every script that opens a connection must set it.

### 3. Verification

```sql
PRAGMA journal_mode;        -- Should return 'wal'
PRAGMA busy_timeout;         -- Should return '5000' (current session only)
PRAGMA wal_autocheckpoint;   -- Should return '500'
```

## Systematic Patching Pattern

For codebases with many scripts connecting to the same DB:

### Find all connection points

```bash
grep -rn "sqlite3\.connect" /path/to/scripts/
```

### Add busy_timeout after each connect

For each file, add:
```python
con.execute("PRAGMA busy_timeout=5000")
```

Directly after the `sqlite3.connect()` line. Match indentation to surrounding code.

### Sample patch

```diff
  con = sqlite3.connect(DB_PATH)
+ con.execute("PRAGMA busy_timeout=5000")
  con.row_factory = sqlite3.Row
```

## Pitfalls

- **busy_timeout is not persistent**: It must be set on every new connection. Scripts that create connections in loops or subprocesses need the PRAGMA each time.
- **WAL mode requires file system support**: Works on ext4, xfs, btrfs, zfs. May not work on some network filesystems (NFS without lockd).
- **WAL file cleanup**: WAL creates `.db-wal` and `.db-shm` files. These are cleaned up on clean shutdown but may persist if the process crashes. They're safe to delete when the DB is not in use.
- **journal_mode=delete is still the default**: SQLite defaults to delete mode even if the DB was previously in WAL mode when opened by an old SQLite version. Verify after any SQLite upgrade.
- **Active readers prevent checkpoint**: WAL checkpoints (converting WAL back to main DB) can't run while any reader has an open transaction. Long-running queries can cause WAL files to grow unbounded. Set `wal_autocheckpoint` to a reasonable value (500 pages ≈ 2MB).