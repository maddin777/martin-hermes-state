# Watchlist Dedup — Ticker Priority System

## Problem

Die Watchlist enthält Duplikate bei denen die gleiche Firma (gleicher `name`) unter verschiedenen Exchange-Tickern geführt wird:
```
Schneider Electric S.E.  → SU.PA  (Paris) / SBGSY (US-ADR)
Samsung                  → 207940.KS (Korea) / 006400.KS (Korea)
Wise                     → WISE.L (London) / WSE (US-Primär)
```

Vor dem Fix (11.06.2026) hatte `watchlist_dedup.py` eine statische `TICKER_GROUPS`-Liste die nur 25 bekannte Paare abdeckte. Neue Duplikate wurden nie erfasst → Watchlist wuchs stetig.

## Lösung: Dynamische Ticker-Priorität

### Rangfolge (0 = beste, 5 = schlechteste)

| Prio | Kategorie | Beispiele | Regel |
|------|-----------|-----------|-------|
| 0 | US-Primär | TRI, TGT, BLK, WSE | Kein Suffix, ≤5 Zeichen, nur Buchstaben |
| 1 | US-ADR | BMPSY, POAHY, SBGSY | Suffix `.Y` oder kein Suffix mit >5 Zeichen |
| 2 | EU-Primärbörse | SU.PA, SAMPO.HE, SKA-B.ST | Suffix .DE, .PA, .AS, .HE, .BR, .VI, .SW, .ST, .CO |
| 3 | London | TATE.L, SMT.L, 0HAN.IL | Suffix .L, .IL |
| 4 | Sonstige | 207940.KS, NST.AX, P911.DE | Asiatisch, Australisch, deutsche Nebenbörsen (.MU, .F, .SG) |
| 5 | Strukturiert | DE000SL0FUQ7.SG | ISIN-ähnlich (2 Buchstaben + 10+ Zeichen) |

### Implementierung (`watchlist_dedup.py`)

```python
def _ticker_priority(ticker):
    """Bewertet Ticker nach Börsen-Herkunft. Niedriger = besser."""
    if not ticker:
        return 99
    # Strukturierte Produkte: ISIN-ähnlich
    if re.match(r'^[A-Z]{2}[0-9A-Z]{10,}\.(SG|MU|F|DE|L|PA|SW|VI|AS)$', ticker):
        return 5
    if re.match(r'^[A-Z]{2}[0-9A-Z]{10,}$', ticker):
        return 5
    suffix = ticker.split('.')[-1] if '.' in ticker else ''
    if not suffix:
        if ticker.isalpha() and len(ticker) <= 5:
            return 0
        if ticker[0].isdigit():
            return 4
        return 1
    suffix = suffix.upper()
    if suffix == 'Y' and len(ticker) <= 5:
        return 1
    if suffix in ('DE', 'PA', 'AS', 'HE', 'BR', 'VI', 'SW', 'ST', 'CO'):
        return 2
    if suffix in ('L', 'IL'):
        return 3
    return 4
```

### Merge-Phase (Phase 3) in `dedup_by_name()`

Ersetzt die statische `TICKER_GROUPS`-Liste. Gruppiert Watchlist-Einträge nach `name` (gleicher Name → gleiche Firma), bestimmt den Ticker mit bester Priorität, merged und droppt Duplikate:

```python
groups = {}
for r in rows:
    groups.setdefault(r["name"], []).append(r)

for name, group in groups.items():
    if len(group) <= 1:
        continue
    best = min(group, key=lambda r: _ticker_priority(r["ticker"]))
    if all(r["ticker"] == best["ticker"] for r in group):
        continue  # Alle haben schon den besten Ticker
    merge_group(con, group, name, "name")
```

### `rowid` statt `id` für UPDATEs

**Kritisch:** `merge_group()` nutzt `r["rowid"] or r["id"]` statt nur `r["id"]`. Die Watchlist-Tabelle hat ~166 Einträge mit `id=NULL` (fehlgeschlagene `INSERT ... ON CONFLICT DO NOTHING`). Mit `WHERE id=?` werden diese Zeilen nie getroffen → Duplikate werden nie gelöscht.

```python
# Gut:
rid = row.get("rowid") or row.get("id")
if rid:
    con.execute("UPDATE watchlist SET status='dropped' WHERE rowid=?", (rid,))
```

**Prävention:** SELECT `rowid, *` statt nur `*` für Tabellen die per id gemerged werden.

### Ergebnisse (11.06.2026)

- **Vorher:** 373 watching Einträge, 17 Duplikat-Gruppen
- **Nachher:** 356 watching, 17 gedroppt
- **Ticker-Präferenz korrekt:** US-Primär (WSE, ADRNY) > US-ADR (BMPSY, POAHY) > EU (EN.PA, SAMPO.HE) > London (TATE.L) > Asien (207940.KS)