# DB Lock: Transaction-in-Loop-Pattern

## Problem

SQLite "database is locked" tritt auf, wenn zwei Prozesse gleichzeitig schreiben. In WAL-Mode + `busy_timeout=30000` (30s) wartet SQLite 30s, dann gibt's den Error.

**Häufigste Ursache im Pipeline-Code:** Die Transaction wird über eine Schleife mit API-Calls offen gehalten.

### Schlechtes Pattern (Lock für Minuten)

```python
def fetch_something(con, items):
    for item in items:
        # ← Transaction OFFEN während API-Call
        data = requests.get(f"https://api.example.com/{item}", timeout=10)
        con.execute("INSERT INTO table VALUES (?)", (data,))
    con.commit()  # ← Erst NACH allen API-Calls committed
```

**Problem:** Python's sqlite3 startet automatisch eine Transaction beim ersten `con.execute("INSERT...")`. Diese Transaction bleibt offen, bis `con.commit()` aufgerufen wird. Wenn zwischen INSERT und commit ein API-Call liegt (10-30s), ist die DB für **alle anderen Writer** blockiert.

### Richtiges Pattern (Lock für 1µs)

```python
def fetch_something(con, items):
    for item in items:
        data = requests.get(f"https://api.example.com/{item}", timeout=10)
        # ← KEINE offene Transaction — API-Call ist lock-frei
        con.execute("INSERT INTO table VALUES (?)", (data,))
        con.commit()  # ← Lock sofort wieder freigegeben
```

**Trade-off:** Keine Batch-Atomicität. Wenn der Loop nach dem 3. von 20 Items crasht, sind die ersten 3 committed. Für Logging/Scraping-Daten ist das irrelevant.

## Betroffene Funktionen (gefixt 08.07.2026)

| File | Funktion | API-Call im Loop | Lock vorher | Lock nachher |
|------|----------|-----------------|-------------|--------------|
| `fundamental_data.py` | `fetch_fred_data` | FRED API (10s × ~10 Indikatoren) | ~100s | 1µs |
| `fundamental_data.py` | `fetch_insider_trades` | SEC EDGAR (10s × ~20 Ticker) | ~200s | 1µs |
| `fundamental_data.py` | `fetch_pcr` | yfinance (5s × ~15 Ticker) | ~75s | 1µs |
| `social_scanner.py` | `fetch_rss_feeds` | LLM (30s × ~10 Artikel/Feed) | ~300s/Feed | 1µs |
| `social_scanner.py` | `fetch_twitter` | LLM (30s × ~20 Tweets) | ~600s/Account | 1µs |

## Bereits korrekte Funktionen

- `yt_channel_monitor.py` — commit per Video (line 208)
- `signal_extractor.py` — commit per Video (lines 253, 263)
- `active_exit_check.py` — commit per Position-Close (lines 234, 306)

## Review-Checkliste bei neuen Scripts

1. **Gibt es eine Schleife mit `con.execute("INSERT/UPDATE/DELETE...")`?**
   → `con.commit()` MUSS **innerhalb** der Schleife sein, nicht danach
2. **Gibt es API-Calls (requests.get, yfinance, LLM) zwischen execute und commit?**
   → Sofort fixen. API-Calls gehören **nie** in eine offene Transaction
3. **Gibt es `con.commit()` am Ende einer Funktion, aber API-Calls im Loop?**
   → Pattern wie oben beschrieben. Commit nach jedem Item

## Prävention

- Neue Pipeline-Scripts vor Deployment auf dieses Pattern prüfen
- `database is locked`-Fehler im Log sind oft Indikator für dieses Pattern (nicht nur "zu viele gleichzeitige Zugriffe")