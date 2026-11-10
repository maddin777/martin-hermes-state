# Ticker-Resolution (Hard Map + yfinance Search)

Bulk-Auflösung von Tickersymbolen für Watchlist-Einträge ohne Ticker (`NULL` oder `'?'`).
Drei Layer: Hard Map (bekannte Fixes, Private, Indizes, Töchter) → yfinance Search → Drop.

## Layer 1: Hard Map

Dict `Name → (ticker, korrigierter_name)` bzw. `(None, None)` für nicht handelbar.

**Typos / OCR-Fehler (LLM-Output):**
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

**Privat / nicht handelbar → dropped:** Scalable Capital, Helsing, Check24, N26,
SpaceX, Robert Bosch, Schwarz Gruppe, Shein, Everlane, Audemars Piguet.

**Töchter / Marken → Muttergesellschaft:**
```python
"Brooks Running (Marke von Berkshire Hathaway)": ("BRK.B", "Berkshire Hathaway"),
"Hoka (Marke von Deckers)": ("DECK", "Deckers Brands"),
"Salomon Group (Teil von Amer Sports)": ("AS", "Amer Sports"),
"Magnum Eis GmbH": ("ULVR.L", "Unilever"),
```

**LLM-Halluzinationen → dropped:** „Dusen Anability“, „Poo Gold“, „Rexbiased Technology“,
„Industrielle Wer Industrie (Ininion)“, „HS and HS“, „Into it“, „Bloomberg Ideal“.

### Merge auf bestehenden Namen (UNIQUE auf `name`)

```python
existing = cur.execute("SELECT id FROM watchlist WHERE name=? AND id!=?",
                       (corrected_name, row_id)).fetchone()
if existing:
    cur.execute("UPDATE watchlist SET ticker=?, notes=? WHERE id=?",
                (ticker, f"merged into '{corrected_name}'", row_id))
else:
    cur.execute("UPDATE watchlist SET ticker=?, name=?, notes=NULL WHERE id=?",
                (ticker, corrected_name, row_id))
```

## Layer 2: yfinance Search

```python
search = yf.Search(company_name)
search.search()            # PFLICHT: wird nicht automatisch ausgeführt
quotes = search.quotes or []
best = quotes[0]           # nach Score sortiert, erster = bester Treffer
ticker = best.get('symbol', '?')
longname = best.get('longname', best.get('shortname', company_name))
```

Pitfalls: `quotes` prüfen (nicht `all`); `shortname` ist immer gesetzt, `longname` oft `None`;
`time.sleep(0.3)` zwischen Calls gegen Throttling.

## Layer 3: Drop

Nicht auflösbar = meist Halluzination, sehr obskure Privatfirma, oder Index/Anleihe/Währung:

```python
cur.execute("UPDATE watchlist SET status='dropped', "
            "notes='LLM-Halluzination/kein reales Unternehmen' WHERE id=?", (row_id,))
```

## Verification

```sql
SELECT COUNT(*) FROM watchlist WHERE (ticker IS NULL OR ticker='?') AND status='watching';
SELECT name, ticker, status FROM watchlist
WHERE ticker IS NOT NULL AND ticker != '?' AND status='watching'
ORDER BY mention_count DESC LIMIT 20;
```

Für Börsen-Mirror-Kanonisierung (US > .DE > Nebenboersen, `.SG`/`.MU`/`.F`-Fallen) siehe
`canonical-ticker-mirrors-attribution.md`.
