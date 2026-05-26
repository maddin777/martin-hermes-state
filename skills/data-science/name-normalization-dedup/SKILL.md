---
name: name-normalization-dedup
description: >-
  Normalize entity names (company names, person names, product names) in SQLite
  for deduplication. Regex strips legal suffixes and annotation brackets;
  alias map resolves LLM typos and canonical-form variants; SQL merge handles
  UNIQUE-constraint conflicts gracefully.
trigger:
  - "User says 'deduplicate', 'normalize names', 'clean up duplicates'"
  - "Database has variant names for same entity (e.g. 'Meta'/'Meta Platforms'/'Meta Platforms Inc.')"
  - "LLM output contains typos or inconsistent name formatting"
  - "Working with company names, stock tickers, or entity identifiers"
---

# Name Normalization & Deduplication (SQLite)

A reusable three-layer approach to normalize entity names in a SQLite database and merge duplicates.

## Architecture

```
Layer 1: Alias Map        — LLM typo fixups + known variants → canonical
Layer 2: Regex Pipeline   — Strip legal suffixes, annotation brackets, prefixes
Layer 3: SQL Merge        — UPDATE or DELETE with UNIQUE constraint handling
```

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
        
        # 4. UPDATE or DELETE each duplicate
        for orig in originals:
            if orig == canonical:
                continue
            try:
                con.execute("UPDATE table SET name=? WHERE name=?", (canonical, orig))
            except sqlite3.IntegrityError:
                # UNIQUE(name, video_id) conflict — same video already has canonical name
                # Delete the now-redundant duplicate row
                con.execute(
                    "DELETE FROM table WHERE name=? AND EXISTS "
                    "(SELECT 1 FROM table AS t2 WHERE t2.name=? AND t2.video_id=table.video_id)",
                    (orig, canonical)
                )
```

**Key insight for UNIQUE conflicts**: When `(name, video_id)` has a UNIQUE constraint, renaming "Meta Platforms"→"Meta" for video X fails if "Meta" already exists for video X. The duplicate row should be DELETED, not kept — it's the same entity mention from the same source video.

## Pitfalls

- **Iterative suffix stripping required**: One pass of the LEGAL_SUFFIX_RE is not enough for "DWS Group GmbH & Co. KGaA" → need while-loop until stable
- **Order matters**: Strip brackets BEFORE suffixes (a suffix regex might eat part of the bracket content)
- **Case variants**: "Nvidia" and "NVIDIA" are different after normalize unless you have a case-normalizing alias. Either add `"nvidia": "NVIDIA"` to aliases, or handle case generically
- **Watchlist/Rollup tables**: After normalizing the source table (mentions), old duplicate rows in the aggregated table (e.g., watchlist) remain stale. They get cleaned up on the next full aggregation run
- **Canonical name selection**: Prefer the normalized form's exact match, then the shortest name, then the most descriptive (prefer "Technologies"/"Systems" suffix if it helps ticker resolution)

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