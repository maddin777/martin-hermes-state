# Datum-Normalisierung (YYYYMMDD → YYYY-MM-DD)

## Problem

Die Watchlist-DB speichert `last_seen` uneinheitlich:
- **1278 Einträge** im ISO-Format `YYYY-MM-DD`
- **47 Einträge** als `YYYYMMDD` (keine Trennzeichen)

Das killt automatisierte Sortierung und Altersanalyse im Dashboard/Export.

## Betroffene Ticker (Stand 03.07.2026)

```
20260503: NEM, 278A.T
20260512: FMV.F, B, CGAU, SSRM, TECK
20260604: YPF.F, ERO
20260607: 45E.MU, DEO, UROY, DC, VZLA
20260611: ABNB, GS, MO, O8M.SG, EGO, OGC
20260614: NFLX
20260616: SII.DE, RGLD
20260619: AAPL, CSCO, DY6.SG, IE00BKVD2N49.SG, NESN.SW, NOK, ORC.DE, SAP.DE, WDC, XOM, HOOD, EQNR, VRT, FSLR
20260621: AEM, BTG, CA29446Y5020.SG, CCJ, PA2.SG, GFI, UEC, FNV, KAP.IL, YCA.L
```

## Implementierung

Die Funktion `_normalize_date()` in `scripts/export_watchlist.py`:

```python
def _normalize_date(val: str | None) -> str | None:
    """Wandelt YYYYMMDD → YYYY-MM-DD, lässt andere Formate passieren."""
    if not val:
        return val
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", val)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return val
```

### Edge Cases (alle getestet)

| Input | Output | Begründung |
|-------|--------|------------|
| `20260621` | `2026-06-21` | YYYYMMDD → ISO |
| `2026-06-19` | `2026-06-19` | Bereits ISO → unverändert |
| `2026-04-20` | `2026-04-20` | Bereits ISO → unverändert |
| `None` | `None` | Null-safe |
| `""` | `""` | Leerstring passiert |
| `"garbage"` | `"garbage"` | Nicht-Datum passiert |
| `"123"` | `"123"` | Zu kurz für YYYYMMDD → passiert |
| `"123456789"` | `"123456789"` | Zu lang für YYYYMMDD → passiert |

## Ursache

Der `last_seen`-Wert kommt aus `watchlist_manager.update_watchlist()`. Die Pipeline-Scripts speichern teils `datetime.date.isoformat()` (YYYY-MM-DD), teils `datetime.strftime("%Y%m%d")` (YYYYMMDD) — kein konsistenter Pfad.

## Root-Cause Fix (optional)

Statt nur beim Export zu normalisieren, kann die DB selbst bereinigt werden:

```sql
UPDATE watchlist
SET last_seen = substr(last_seen, 1, 4) || '-' || substr(last_seen, 5, 2) || '-' || substr(last_seen, 7, 2)
WHERE length(last_seen) = 8
  AND last_seen GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]';
```

Das verhindert dass neue Exporte das Problem je wieder sehen. Der Export-Fix bleibt als Sicherheitsnetz.