# Sector Blacklist + Probation-Mechanismus (DB-backed, seit 30.07.2026)

## Konzept

Sektoren können manuell oder automatisch auf eine Blacklist gesetzt werden.
Nach einem Cooldown (Default: 14 Tage) öffnet sich ein Probation-Fenster für
genau einen Trade. Bei Gewinn → Sektor frei, bei Verlust → erneuter Cooldown.

## Architektur

**Single Source of Truth:** `sector_blacklist`-Tabelle in `trading.db`.

```sql
CREATE TABLE sector_blacklist (
    sector TEXT PRIMARY KEY,
    blocked_at DATE NOT NULL,
    cooldown_days INTEGER DEFAULT 14,
    probation_entry_id INTEGER,
    probation_entry_ticker TEXT,
    probation_opened_at DATE,
    probation_status TEXT DEFAULT NULL,  -- NULL/active/success/failed
    probation_pnl REAL,
    re_entry_threshold_pnl REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT
);
```

### Lebenszyklus

| Phase | probation_status | Cooldown Rest | Bedeutung |
|-------|-----------------|---------------|-----------|
| Gesperrt | NULL | > 0 | Keine Entries. Cooldown läuft. |
| Probation offen | NULL | ≤ 0 | Cooldown abgelaufen, 1 Trade erlaubt. |
| Probation aktiv | 'active' | — | Trade läuft, kein weiterer Entry. |
| Bestanden | 'success' | — | Sektor frei. |
| Fehlgeschlagen | 'failed' | — | Neuer Cooldown ab heute. |

### Komponenten

| Komponente | Datei | Funktion |
|------------|-------|----------|
| Helper | `watchlist_manager.py` | `get_sector_blockade_info(con)` → Dict sector→Status |
| Migration | `watchlist_manager.py` main() | Legt Tabelle an, migriert alte JSON-Einträge |
| Export | `export_watchlist.py` | Liest aus DB, zeigt Status in Watchlist-Markdown |
| Dashboard | `dashboard.py` | Liest aus DB, farbcodierte Anzeige |
| Pipeline-Output | `watchlist_manager.py` main() | Gibt Blockade-Status am Ende aus |

## Manuelle Bedienung

### Sektor blockieren (14d Cooldown ab heute)

```python
from config import db_connect
from datetime import datetime
con = db_connect()
con.execute("""
    INSERT OR REPLACE INTO sector_blacklist (sector, blocked_at, cooldown_days)
    VALUES (?, ?, ?)
""", ('Industrials', datetime.now().strftime('%Y-%m-%d'), 14))
con.commit()
```

### Cooldown sofort abgelaufen (Probation-Fenster offen)

```python
from datetime import timedelta
blocked_at = (datetime.now() - timedelta(days=19)).strftime('%Y-%m-%d')
con.execute("""
    INSERT OR REPLACE INTO sector_blacklist (sector, blocked_at, cooldown_days, probation_status)
    VALUES (?, ?, 14, NULL)
""", ('Industrials', blocked_at))
con.commit()
```

### Probation-Trade erfassen

```python
con.execute("""
    UPDATE sector_blacklist
    SET probation_status='active', probation_entry_ticker=?, probation_opened_at=?
    WHERE sector=?
""", ('TICKER', datetime.now().strftime('%Y-%m-%d'), 'Industrials'))
con.commit()
```

### Probation evaluieren

```python
# Erfolg: Sektor freigeben
con.execute("""
    UPDATE sector_blacklist
    SET probation_status='success', probation_pnl=?
    WHERE sector=?
""", (pnl_value, 'Industrials'))
con.commit()

# Fehlschlag: Neuer Cooldown ab heute
con.execute("""
    UPDATE sector_blacklist
    SET probation_status='failed', blocked_at=?, probation_pnl=?
    WHERE sector=?
""", (datetime.now().strftime('%Y-%m-%d'), pnl_value, 'Industrials'))
con.commit()
```

### Sektor komplett freigeben

```python
con.execute("DELETE FROM sector_blacklist WHERE sector=?", ('Industrials',))
con.commit()
```

## Integration in watchlist_manager.py

Die `get_sector_blockade_info()`-Funktion berechnet den Status jedes Sektors:

```python
def get_sector_blockade_info(con):
    rows = con.execute("""
        SELECT sector, blocked_at, cooldown_days,
               probation_opened_at, probation_status, probation_entry_ticker
        FROM sector_blacklist
    """).fetchall()
    today = datetime.now().date()
    result = {}
    for r in rows:
        blocked = datetime.strptime(r["blocked_at"], "%Y-%m-%d").date()
        cooldown_end = blocked + timedelta(days=r["cooldown_days"])
        remaining = (cooldown_end - today).days
        probation = r["probation_status"]
        if probation is None and remaining <= 0:
            probation = "open"  # Cooldown abgelaufen, Fenster offen
        result[r["sector"]] = {
            "blocked": True,
            "cooldown_remaining": max(0, remaining),
            "cooldown_end": cooldown_end.isoformat(),
            "probation_status": probation,
            "probation_entry_ticker": r["probation_entry_ticker"],
        }
    return result
```

## Migration von strategy_config.json (30.07.2026)

Die alte `sector_blacklist` in `strategy_config.json` wurde durch die DB-Tabelle
ersetzt. Die Migration läuft automatisch in `watchlist_manager.py` main():

1. `CREATE TABLE IF NOT EXISTS sector_blacklist`
2. Liest `sector_blacklist` aus `strategy_config.json`
3. `INSERT OR IGNORE` in DB
4. Leert `sector_blacklist: {}` in JSON (Daten sind jetzt in DB)

## Status-Ausgabe im Pipeline-Output

```
🚫 GEBLOCKTE SEKTOREN (1):
  🚫 Industrials: Cooldown noch 5 Tage (bis 2026-07-25)
  🟡 Industrials: Probation-Fenster OFFEN – ein Trade möglich
  🟢 Industrials: Probation-Trade aktiv (TICKER)
  ✅ Industrials: Probation bestanden – Sektor wieder freigegeben
  ❌ Industrials: Probation fehlgeschlagen – Cooldown resettet
```

## Bekannte Limitationen (30.07.2026)

- **`signal_manager.py`** nutzt noch die alte `strategy_config.json`-Logik
  (`update_sector_blacklist()`, `is_sector_allowed()`). Nach dem nächsten
  watchlist_manager-Lauf sind die alten Daten migriert, aber die automatische
  Blacklist-Auswertung (14d P&L pro Sektor) muss separat auf die DB umgestellt werden.
- **Kein Cron für automatische Evaluierung** — Probation-Status muss manuell gesetzt
  werden (oder via nightly_eval / signal_manager).

## Verwandte Referenzen

- `references/adapt-strategy-regime-blindness.md` — Regime-bewusste SL/TP-Anpassung
- `references/other-sector-private-companies.md` — Sektor-Mapping für Private Companies