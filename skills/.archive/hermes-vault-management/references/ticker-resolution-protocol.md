# Ticker Resolution Protocol — Watchlist "?" Cleanup

*For cleaning up unresolved ticker symbols in the trading watchlist (`trading.db`)*

---

## When to Use

The trading watchlist accumulates entries with `ticker=NULL` or `ticker='?'` because:
- LLMs hallucinate company names (typos, merged names)
- Privatfirmen ohne Aktie landen in der Watchlist
- Namen werden inkonsistent geparst ("Münchner Rück" vs "Münchener Rück")

## Workflow

### 1. Scope the Problem

```bash
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT COUNT(*) FROM watchlist WHERE ticker IS NULL OR ticker='?'"
```

Separate `watching` vs `dropped` entries:

```bash
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT COUNT(*) FROM watchlist WHERE (ticker IS NULL OR ticker='?') AND status='watching'"
```

### 2. Extract Full List

```bash
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db -json \
  "SELECT id, name, ticker, mention_count, status FROM watchlist WHERE ticker IS NULL OR ticker='?' ORDER BY mention_count DESC"
```

### 3. Categorize Each Entry

| Category | Action | Examples |
|----------|--------|----------|
| **LLM-Typos** | Map to correct name + ticker | "Palantier"→PLTR, "Reinmetall"→RHM.DE |
| **Legal-Suffix Variants** | Strip suffix, deduplicate | "D-Wave Systems Inc."→QBTS |
| **Privatfirmen** | Set `status='dropped'` with notes | N26, SpaceX, Scalable Capital |
| **Fußballvereine** | Drop | Eintracht Frankfurt, VfB Stuttgart |
| **Marken/Töchter** | Map to Mutterkonzern ticker | "Brooks Running"→BRK.B, "Hoka"→DECK |
| **Anleihen/Indizes** | Drop (keine Aktien) | Bundesanleihen, Banque de France |
| **LLM-Halluzinationen** | Drop with notes | "Poo Gold", "Dusen Anability", "Industrielle Wer Industrie" |
| **Echte unbekannte** | yfinance search | Rocketlab→RKLB, NuBank→NU |

### 4. Build Hard Map (Script)

Use a Python script with:
- **Hardcoded map** for known typos → (ticker, canonical_name)
- **yfinance Search** for unknown companies
- **DB update** with UNIQUE constraint handling

```python
HARD_MAP = {
    "Münchner Rück": ("MUV2.DE", "Münchener Rück"),
    "Palantier": ("PLTR", "Palantir Technologies"),
    # ... ~80-100 entries
}
```

For yfinance lookups:

```python
import yfinance as yf
search = yf.Search(name)
search.search()
quotes = search.quotes or []
if quotes:
    best = quotes[0]
    ticker = best.get('symbol', '?')
    longname = best.get('longname', best.get('shortname', name))
```

**Critical:** Handle `UNIQUE constraint failed: watchlist.name` — the corrected name might already exist in the DB. Check before updating:

```python
existing = cur.execute("SELECT id FROM watchlist WHERE name=? AND id!=?", (corrected_name, row_id)).fetchone()
if existing:
    cur.execute("UPDATE watchlist SET ticker=?, notes=? WHERE id=?", (ticker, f"merged into '{corrected_name}'", row_id))
else:
    cur.execute("UPDATE watchlist SET ticker=?, name=?, notes=NULL WHERE id=?", (ticker, corrected_name, row_id))
```

### 5. DB Backup Before Running

```bash
cp /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
   /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db.ticker_backup
```

### 6. Run Resolution

```bash
cd /root/.hermes/profiles/hermes_trading && \
  python3 /root/.hermes/scripts/resolve_tickers.py
```

### 7. Update NORMALIZE_ALIASES in watchlist_manager.py

After resolving, add the discovered typos to `watchlist_manager.py` so the normalization pipeline catches them going forward:

```python
# In NORMALIZE_ALIASES dict, around line 207:
"münchner rück": "Münchener Rück",
"bayersdorf": "Beiersdorf",
"kommerzbank": "Commerzbank",
# ... etc.
```

File: `/root/martin-hermes-state/profiles/hermes_trading/skills/trading/scripts/watchlist_manager.py`

## Reference Script

`/root/.hermes/scripts/resolve_tickers.py` — the bulk resolver from the 2026-05-26 cleanup. Script contains:
- 80+ hardcoded alias mappings
- yfinance search fallback
- UNIQUE constraint handling
- Status output per entry

## Expected Outcomes

| Metric | Typical Range |
|--------|--------------|
| Total "?" entries | 150–200 |
| Resolved (hard map) | ~80–100 |
| Resolved (yfinance) | ~20–40 |
| Dropped (privat/nonsense) | ~40–60 |
| Unresolved after script | 0–5 (investigate manually) |

## Pitfalls

- **yfinance rate limiting**: Add `time.sleep(0.3)` between lookups
- **Name collisions**: Watchlist has UNIQUE on `name` column. Always check before rename.
- **yfinance.Search.search() required**: Just creating `yf.Search(name)` doesn't populate quotes — must call `.search()` explicitly
- **yfinance may return wrong ticker**: Especially for generic names ("Aino Moto"→Agilent? "A"→Agilent?). Review first result sanity before committing.
- **Dropped entries remain in DB**: They're not deleted, just status='dropped'. The watchlist UI filters them.
- **watchlist_manager.py is under martin-hermes-state**: Changes land in the [martin-hermes-state](https://github.com/maddin777/martin-hermes-state) repo and get synced via the nightly GitHub cron.