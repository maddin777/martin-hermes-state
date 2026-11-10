---
name: name-normalization-dedup
description: >-
  Normalize entity names AND resolve stock ticker symbols in SQLite. Four-layer
  approach: DB config for concurrent access, alias map fixes LLM typos, regex
  strips legal suffixes, SQL merge handles UNIQUE conflicts. Extended by yfinance
  Search for bulk ticker lookup of unknown companies. Covers private-company
  detection, subsidiary→parent mapping, LLM hallucination cleanup, and SQLite
  WAL mode / busy_timeout configuration for pipeline reliability.
trigger:
  - "User says 'deduplicate', 'normalize names', 'clean up duplicates'"
  - "User says 'resolve tickers', '? ticker', 'abräumen', 'fix tickers'"
  - "Database has variant names for same entity (e.g. 'Meta'/'Meta Platforms'/'Meta Platforms Inc.')"
  - "Database has entries with NULL or '?' ticker symbols"
  - "LLM output contains typos, inconsistent name formatting, or hallucinated companies"
  - "Working with company names, stock tickers, or entity identifiers"
  - "Error: 'database is locked' in SQLite"
  - "Multiple scripts access same SQLite database concurrently"
  - "Setting up a new SQLite-backed pipeline"
---

# Name Normalization & Deduplication (SQLite)

A reusable three-layer approach to normalize entity names in a SQLite database and merge duplicates.

## Architecture

```
Layer 0: DB Config        — WAL mode + busy_timeout for concurrent access
Layer 1: Alias Map        — LLM typo fixups + known variants → canonical
Layer 2: Regex Pipeline   — Strip legal suffixes, annotation brackets, prefixes
Layer 3: SQL Merge        — UPDATE or DELETE with UNIQUE constraint handling
```

## Layer 0: Database Configuration for Concurrent Access

Configure SQLite for reliable concurrent access before running any normalization or merge operations. The default SQLite configuration (`journal_mode=delete`, `busy_timeout=0`) is worst-case for concurrent pipeline access and causes the dreaded "database is locked" errors.

### Root Cause: Why "database is locked"

The error means one connection has an active transaction while another connection tries to access the database.

| Setting | Default | Problem |
|---------|---------|---------|
| `journal_mode` | `delete` | Only one writer allowed; readers block writers |
| `busy_timeout` | `0` | No retry — fails immediately on lock contention |

### Fix: WAL Mode + Busy Timeout

**One-time DB setup (persists in DB file):**

```bash
sqlite3 /path/to/database.db "PRAGMA journal_mode=WAL;"
sqlite3 /path/to/database.db "PRAGMA wal_autocheckpoint=500;"
```

WAL (Write-Ahead Logging) allows multiple concurrent readers while a writer is active — the writer does not block readers.

**Per-connection busy_timeout (must set at connect time on EVERY script):**

```python
import sqlite3
con = sqlite3.connect("/path/to/database.db")
con.execute("PRAGMA busy_timeout=5000")  # Wait 5s instead of failing immediately
```

The `busy_timeout` is connection-level — it does NOT persist in the DB file. Every script that opens a connection must set it.

### Verification

```sql
PRAGMA journal_mode;        -- Should return 'wal'
PRAGMA busy_timeout;         -- Should return '5000' (current session only)
PRAGMA wal_autocheckpoint;   -- Should return '500'
```

### Systematic Patching Pattern

For codebases with many scripts connecting to the same DB:

```bash
# Find all connection points
grep -rn "sqlite3\.connect" /path/to/scripts/
```

For each file, add `con.execute("PRAGMA busy_timeout=5000")` directly after each `sqlite3.connect()` line, matching indentation.

### Pitfalls

- **busy_timeout is not persistent**: Set on every new connection, including inside loops and subprocesses.
- **WAL mode requires file system support**: Works on ext4, xfs, btrfs, zfs. May fail on NFS without lockd.
- **WAL file cleanup**: `.db-wal` and `.db-shm` files persist after a crash. Safe to delete when DB is not in use.
- **journal_mode=delete is still the default**: SQLite defaults to delete mode even if the DB was previously in WAL when opened by an old SQLite version — verify after upgrades.
- **Long-running queries prevent WAL checkpoint**: Set `wal_autocheckpoint` to ~2MB. See `references/sqlite-concurrent-access.md` for full detail.

## Layer 1: Alias Map

A dict mapping lowercase variant keys → canonical display names. Covers:

- **LLM typos**: `Palantier→Palantir`, `Reimmetall→Rheinmetall`, `Enhropic→Anthropic`
- **Name variants**: `Meta Platforms→Meta`, `D-Wave Systems→D-Wave Quantum`
- **Case normalization**: `nvidia→NVIDIA`, `amd→AMD`
- **Known wrong forms**: `Morgen Stanley→Morgan Stanley`

**Convention**: keys are `.lower().strip()`. Values are the canonical display name.

## Layer 2: Regex Pipeline

Stripping pipeline applied in order:

1. **Bracket notes**: `(nicht börsennotiert)`, `(Marke von …)`, `(privat gehalten)` → removed
2. **Legal suffixes** (iterative, for nested forms like "DWS Group GmbH & Co. KGaA"): 
   - German: `AG`, `SE`, `GmbH`, `GmbH & Co. KGaA`, `AG & Co. KGaA`
   - English: `Inc.`, `Inc`, `Corporation`, `Corp.`, `Corp`, `Ltd.`, `Limited`, `LLC`, `LLP`, `LP`, `PLC`, `plc`
   - Other: `NV`, `N.V.`, `SA`, `S.A.`, `AB`, `OY`, `Sp. z o.o.`
   - Structural: `Holdings`, `Group`, `Co.`, `Company`, `Class [A-E]`
3. **"The " prefix** → stripped
4. **Whitespace normalization** → collapse multiple spaces
5. **Alias resolution** → canonical form from map

**Pitfall**: Suffix regex must be applied iteratively (while-loop) because "DWS Group GmbH & Co. KGaA" needs multiple passes: first strip "GmbH & Co. KGaA" → "DWS Group" → then strip "Group" → "DWS".

## Layer 3: SQL Merge Strategy

```python
def normalize_mentions(con):
    # 1. Get all distinct names from table
    rows = con.execute("SELECT DISTINCT name FROM table ORDER BY name").fetchall()
    
    # 2. Group by normalized form
    groups = {}  # normalized -> [original_names]
    for n in names:
        norm = normalize(n)
        groups.setdefault(norm, []).append(n)
    
    # 3. Pick canonical (shortest, or exact match to normalized form)
    for norm, originals in groups.items():
        if len(originals) <= 1:
            continue
        canonical = ...  # logic: prefer name matching norm exactly, else shortest
        
        # 4. CRITICAL: DELETE conflicting rows FIRST, then UPDATE
        #    A bulk-UPDATE fails on ALL rows if ANY row has a UNIQUE conflict.
        #    Always delete conflicts before updating.
        for orig in originals:
            if orig == canonical:
                continue
            # Step 1: Delete rows where same video_id already has canonical
            con.execute(
                "DELETE FROM table WHERE name=? AND "
                "EXISTS (SELECT 1 FROM table AS w2 "
                "WHERE w2.name=? AND w2.video_id=table.video_id)",
                (orig, canonical)
            )
            # Step 2: Bulk-UPDATE remaining non-conflicting rows
            con.execute("UPDATE table SET name=? WHERE name=?", (canonical, orig))
```

**CRITICAL BUG**: A single `UPDATE table SET name=X WHERE name=Y` that affects multiple rows fails ENTIRELY if ANY row causes a UNIQUE constraint violation. The `try/except IntegrityError → DELETE` pattern does NOT work because the UPDATE is atomic across all rows — once it fails, no rows are changed. **Always DELETE conflicting rows BEFORE the UPDATE**, not after.

## Watchlist-Table-Level Dedup

After normalizing the mentions table, the aggregated `watchlist` table often has stale duplicate entries with the same ticker but different names (e.g., "Meta", "Meta Platforms", "Meta Platforms Inc." as separate watching entries). Use a separate dedup script that:

1. **By ticker**: Group watching entries by same ticker → merge conviction scores, mention counts, channels
2. **By normalized name**: Group entries without tickers → merge
3. **Followed by a re-aggregation run** to recalculate proper conviction scores

**Key insight for UNIQUE conflicts**: When `(name, video_id)` has a UNIQUE constraint, renaming "Meta Platforms"→"Meta" for video X fails if "Meta" already exists for video X. The duplicate row should be DELETED, not kept — it's the same entity mention from the same source video.

## Pitfalls

- **Iterative suffix stripping required**: One pass of the LEGAL_SUFFIX_RE is not enough for "DWS Group GmbH & Co. KGaA" → need while-loop until stable
- **Order matters**: Strip brackets BEFORE suffixes (a suffix regex might eat part of the bracket content)
- **Case variants**: "Nvidia" and "NVIDIA" are different after normalize unless you have a case-normalizing alias. Either add `"nvidia": "NVIDIA"` to aliases, or handle case generically
- **Watchlist/Rollup tables**: After normalizing the source table (mentions), old duplicate rows in the aggregated table (e.g., watchlist) remain stale. They get cleaned up on the next full aggregation run. For a deeper clean specific to the trading pipeline, see the `trading-pipeline` skill's `references/watchlist-table-dedup.md` (three-phase script: ticker-variant, ticker, name).
- **Canonical name selection**: Prefer the normalized form's exact match, then the shortest name. **Bug to avoid**: do NOT reset the canonical after selecting it — old code had `canonical = min(originals, key=len)` that overwrote the preferred selection.
- **`WHERE id=?` bricht bei NULL-Primärschlüsseln**: SQLite-Tabellen können `id=NULL` haben (z.B. watchlist-Tabelle mit 166/373 Einträgen ohne PRIMARY-KEY-Wert). Ein `UPDATE ... WHERE id=?` mit NULL-id matcht KEINE Zeilen. `DELETE FROM table WHERE id=?` mit NULL-id ist ebenso wirkungslos. **Fix: `rowid` als Fallback verwenden.** SQLite hat immer eine implizite `rowid`-Spalte (außer bei `WITHOUT ROWID`-Tabellen):
  ```python
  # Statt:
  con.execute("UPDATE watchlist SET status='dropped' WHERE id=?", (entry_id,))
  # rowid als Fallback:
  rid = row.get("rowid") or row.get("id")
  if rid:
      con.execute("UPDATE watchlist SET status='dropped' WHERE rowid=?", (rid,))
  ```
  **Prävention**: SELECT immer `rowid, *` statt nur `*` wenn die Tabelle später per id gemerged werden soll. `rowid` ist in SQLite immer verfügbar und nie NULL. Betrifft insbesondere Tabellen die per `INSERT ... ON CONFLICT DO NOTHING` befüllt werden (wie `watchlist`), weil fehlgeschlagene INSERTS keinen Primärschlüssel vergeben.

## Verification

After running dedup:
```sql
-- Check for remaining duplicates
SELECT name, COUNT(*) FROM table GROUP BY name HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC LIMIT 10;

-- Check normalized coverage
SELECT name, COUNT(*) FROM table WHERE name IN (
  -- known old variant names
  'Meta Platforms', 'Alphabet Inc. (Google)'
) GROUP BY name;
```

## Extending the Alias Map

Add new entries when:
- LLM produces a new typo variant for an existing company
- A company appears with both "as-a-Service" and "AaaS" forms
- User reports "X and Y should be the same company"

Pattern:
```python
# typo → canonical
"corweef": "CoreWeave",
# variant → canonical
"meta platforms inc.": "Meta",
# case normalization
"nvidia": "NVIDIA",
```

## Ticker Resolution

After names are normalized, bulk-resolve ticker symbols using the three-layer approach documented in `references/ticker-resolution.md`:

1. **Hard Map** → known typos, private companies, indices, subsidiaries
2. **yfinance Search** → fuzzy lookup for unknown companies
3. **Drop** → unresolvable entries (hallucinations)

### Mention Date Handling

When writing resolved tickers to a signal/mention tracking pipeline, use the **processing date** (datetime.now()), NOT the original publication date. This ensures daily reports show what was processed today:

```python
# BAD: uses original publication date
mention_date = source.get("date", datetime.now().strftime("%Y%m%d"))

# GOOD: always uses processing date
mention_date = datetime.now().strftime("%Y-%m-%d")
```

The publication-date approach causes daily reports to show 0 new companies when all processed content was published on prior days. The signal-pipeline report typically runs at 05:00 and compares today vs yesterday — it needs the processing date to show meaningful results.