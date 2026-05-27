# Ticker Resolution Reference

Bulk lookup of stock ticker symbols for companies in a SQLite watchlist. Uses hard-coded alias mapping + yfinance Search as fallback. Developed for a 182-entry "?" ticker cleanup.

## Architecture

```
Layer 1: Hard Map        — Known typos/fixed tickers, private companies, ETFs, indices
Layer 2: yfinance Search — Fuzzy lookup for unknown companies
Layer 3: Fallback        — Drop entries that can't be resolved (LLM hallucinations)
```

## Layer 1: Hard Map

A dict mapping DB company names → `(ticker, corrected_name)` or `(None, None)` for non-tradable.

### Categories

**Typos / OCR errors** — LLM output of company names with spelling mistakes:
```python
"Münchner Rück": ("MUV2.DE", "Münchener Rück"),
"Reinmetall": ("RHM.DE", "Rheinmetall"),
"Morgen Stanley": ("MS", "Morgan Stanley"),
"Bayersdorf": ("BEI.DE", "Beiersdorf"),
"Siemens Healthys": ("SHL.DE", "Siemens Healthineers"),
"Kommerzbank": ("CBK.DE", "Commerzbank"),
"Gasprom": ("GAZP", "Gazprom"),
"Nasendeck 100": ("QQQ", "Invesco QQQ Trust"),
"Eurostocks 50": ("FEZ", "Euro Stoxx 50"),
"V Pocket EOS OS": ("VOO", "Vanguard S&P 500 ETF"),
```

**Private / non-tradable** — Mark as dropped with note:
```python
"Scalable Capital": (None, None),     # German fintech, privat
"Helsing GmbH": (None, None),         # German AI defense, privat
"Check24": (None, None),              # German comparison platform
"N26": (None, None),                  # German neobank, privat
"SpaceX (nicht börsennotiert)": (None, None),
"Robert Bosch": (None, None),
"Schwarz Gruppe": (None, None),       # Lidl parent
"Shein": (None, None),
"Everlane": (None, None),
"Audemars Piguet": (None, None),
```

**Subsidiaries / Brands** — Map to parent company ticker:
```python
"Brooks Running (Marke von Berkshire Hathaway)": ("BRK.B", "Berkshire Hathaway"),
"Hoka (Marke von Deckers)": ("DECK", "Deckers Brands"),
"Salomon Group (Teil von Amer Sports)": ("AS", "Amer Sports"),
"Magnum Eis GmbH": ("ULVR.L", "Unilever"),
```

**LLM Hallucinations** — Non-existent companies that yfinance can't find:
```python
"Dusen Anability": (None, None),
"Poo Gold": (None, None),
"Rexbiased Technology": (None, None),
"Industrielle Wer Industrie (Ininion)": (None, None),
"HS and HS": (None, None),
"Into it": (None, None),
"Bloomberg Ideal": (None, None),
```

### SQL Handling for Merged Entries

When the corrected name already exists in DB (UNIQUE constraint on `name`):
```python
existing = cur.execute(
    "SELECT id FROM watchlist WHERE name=? AND id!=?",
    (corrected_name, row_id)
).fetchone()
if existing:
    # Don't rename — just set ticker + merge note
    cur.execute(
        "UPDATE watchlist SET ticker=?, notes=? WHERE id=?",
        (ticker, f"merged into '{corrected_name}'", row_id)
    )
else:
    cur.execute(
        "UPDATE watchlist SET ticker=?, name=?, notes=NULL WHERE id=?",
        (ticker, corrected_name, row_id)
    )
```

## Layer 2: yfinance Search

For unknown companies not in the hard map:

```python
import yfinance as yf

search = yf.Search(company_name)
search.search()  # Must call .search() explicitly
quotes = search.quotes or []
if quotes:
    best = quotes[0]
    ticker = best.get('symbol', '?')
    longname = best.get('longname', best.get('shortname', name))
else:
    # No results → likely an LLM hallucination
```

**Pitfalls:**
- `yf.Search(query)` does NOT automatically execute — must call `.search()` on the object
- Rate limit: add `time.sleep(0.3)` between calls (yfinance has no official rate limit but yahoo may throttle)
- Returns results sorted by score (first = best match)
- Check `quotes` list, not `all` dict — `quotes` contains equity/instrument matches
- `shortname` is always set; `longname` may be None for some exchanges

## Layer 3: Fallback / Cleanup

Companies that yfinance can't resolve are typically:
- **LLM hallucinations** (non-existent companies the model invented)
- **Very obscure private companies** (not in yahoo finance)
- **Indices / bonds / currencies** (not individual equities)

These should be marked `status='dropped'` with a note:
```python
cur.execute(
    "UPDATE watchlist SET status='dropped', notes='LLM-Halluzination/kein reales Unternehmen' WHERE id=?",
    (row_id,)
)
```

## Verification

```sql
-- Check remaining unresolved tickers
SELECT COUNT(*) FROM watchlist WHERE (ticker IS NULL OR ticker='?') AND status='watching';

-- Spot check resolved entries
SELECT name, ticker, status FROM watchlist WHERE ticker IS NOT NULL AND ticker != '?' AND status='watching' ORDER BY mention_count DESC LIMIT 20;
```