# sqlite3.Row .get() — wiederkehrende Falle

## Problem

`sqlite3.Row` unterstützt dict-ähnlichen Zugriff (`row["key"]`, `key in row.keys()`), aber **nicht** `row.get("key", default)`.

```python
c = con.execute("SELECT * FROM watchlist LIMIT 1").fetchone()
type(c)  # → <class 'sqlite3.Row'>
c.get("weekly_trend", "neutral")  # → AttributeError!
```

## Korrektes Pattern

```python
# STATT:
c.get("weekly_trend", "neutral")

# IMMER:
c["weekly_trend"] if "weekly_trend" in c.keys() else "neutral"
```

## Alle Fundstellen (Stand 16.06.2026)

| Datei | Zeile | Fix angewendet? | Datum |
|-------|-------|:---:|:-----:|
| `scripts/signal_manager.py` | 1031 (`weekly_trend`) | ✅ Ja | 16.06. |
| `scripts/signal_manager.py` | 1076 (`conviction_score`) | ✅ Ja | 16.06. |
| `scripts/technical_validator.py` | 322 (`source`) | ✅ Ja | 16.06. |

## Prävention

Bei neuem Code IMMER `row["key"]` statt `row.get("key")` für `sqlite3.Row`-Objekte.
Nur echte dicts (cfg, DEFAULT_CONFIG, channel_weights) haben `.get()`.

**Vollscan bei Verdacht:**
```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading
grep -rn '\.get(' scripts/*.py
# Jeden Treffer prüfen: ist das Objekt ein sqlite3.Row oder ein dict?
```

## Warum passiert das immer wieder

1. `sqlite3.Row` ist dict-ähnlich — Entwickler nehmen fälschlich an es hätte `.get()`
2. Fehler tritt erst zur Runtime auf, nicht beim Syntax-Check
3. Spalten existieren meist → `.get()` würde ohnehin den selben Wert liefern → fällt in Tests nicht auf
4. Neue Spalten (weekly_trend, conviction_score) werden per Migration hinzugefügt → nicht alle Zeilen haben sie → `.get()` mit Fallback wirkt sinnvoll, crasht aber