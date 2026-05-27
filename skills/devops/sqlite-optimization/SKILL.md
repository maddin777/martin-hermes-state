---
name: sqlite-optimization
description: >-
  Optimize SQLite for concurrent access in automated data pipelines (cron jobs,
  agent workflows). Covers WAL mode, busy_timeout, journal configuration, and
  systematic fixes for "database is locked" errors.
trigger:
  - "Error: 'database is locked' in SQLite"
  - "Multiple scripts access same SQLite database concurrently"
  - "Cron jobs or agents report SQLite lock contention"
  - "Setting up a new SQLite-backed pipeline"
  - "User asks 'fix database locking' or 'database locked problem'"
---
# SQLite Optimization for Concurrent Access

Configure SQLite for reliable concurrent access in agent-driven pipelines and cron jobs.

## Root Cause Analysis for "database is locked"

The error means one connection has an active transaction (read or write) while another connection tries to access the database. The default SQLite configuration (`journal_mode=delete`, `busy_timeout=0`) is **worst-case** for concurrent access:

| Setting | Default | Problem |
|---------|---------|---------|
| `journal_mode` | `delete` | Only one writer allowed; readers block writers |
| `busy_timeout` | `0` | No retry — fails immediately on lock contention |

## Fix: WAL Mode + Busy Timeout

### 1. Switch Database to WAL Mode (one-time, persists)

```bash
sqlite3 /path/to/database.db "PRAGMA journal_mode=WAL;"
```

WAL (Write-Ahead Logging) allows:
- Multiple concurrent readers while a writer is active
- The writer doesn't block readers
- Much better throughput for mixed read/write workloads

Also consider:
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

For codebases with many scripts connecting to the same DB, the `name-normalization-dedup` skill covers the bulk-patching approach. Key insights:

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

## Related

- `name-normalization-dedup` — entity name normalization and ticker resolution (often paired with DB optimization)
- `hermes-profile-management` — profile-level configuration that may include DB connection settings