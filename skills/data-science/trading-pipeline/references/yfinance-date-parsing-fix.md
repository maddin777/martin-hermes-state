# yfinance „unconverted data remains" — Date-Parsing Fix

## Symptom

yfinance `ValueError: unconverted data remains` beim Download von Kursdaten.
Tritt auf, wenn Yahoo-Datumsstrings einen Zeitzonen-Suffix enthalten (z.B.
`2026-06-28 00:00:00+00:00`), der nicht zum erwarteten Format `%Y-%m-%d` passt.

Betrifft **alle** `yf.download()`-Calls. Pro Nacht ~15+ Ticker-Downloads
betroffen. **Zweite Fundstelle (11.07.2026):** `backtesting/data_client.py`
(YFinanceDataClient) — der gleiche Fix wurde dort ebenfalls eingebaut, damit
der Backtester mit yfinance funktioniert.

## Root Cause

CPython `_strptime._strptime()` (die interne Funktion hinter
`datetime.strptime`) scheitert strikt an unerwarteten Zeichen nach dem
geparsten Datum. yfinance v0.2.54+ liefert über Yahoo Finance Data API
teilweise ISO-Strings mit Zeitzonen-Suffix.

## Fix

Monkey-Patch auf `_strptime._strptime` in `fundamental_data.py`. Fängt nur
`ValueError` mit „unconverted data remains" und delegiert an
`dateutil.parser.parse()`:

```python
import _strptime as _st
from dateutil import parser as _dp

_orig_st_strptime = _st._strptime

def _safe_strptime(data_string, format="%a %b %d %H:%M:%S %Y"):
    try:
        return _orig_st_strptime(data_string, format)
    except ValueError as e:
        if "unconverted data remains" in str(e):
            try:
                parsed = _dp.parse(data_string)
                tt_base = tuple(parsed.timetuple())
                # 11er-Tuple: (y,m,d,h,m,s,wd,yd,isdst, tzname,gmtoff)
                tzname = parsed.tzname()
                gmtoff = int(parsed.utcoffset().total_seconds()) if parsed.tzinfo else None
                return tt_base + (tzname, gmtoff), parsed.microsecond, 0
            except Exception:
                pass
        raise

_st._strptime = _safe_strptime
```

### Warum `_strptime._strptime` und nicht nur `try/except` um `yf.download`?

Der Fehler liegt tief im CPython-Code (`_strptime.py`). Ein `try/except`
auf jedem `yf.download()` wäre redundant (≥25 Aufrufe) und würde das
echte Problem nicht beheben — nur den Fehler verschlucken.

### Warum `_strptime._strptime` und nicht `datetime.strptime`?

`datetime.strptime` ist eine C-gebundene `classmethod` — Monkey-Patching
funktioniert dort nicht (die Klasse ignoriert den Ersatz). Die interne
`_strptime._strptime()` ist eine reine Python-Funktion und patchbar.

### Return-Format

`_strptime()` gibt ein 3-Tupel zurück: `(tt, fraction, gmtoff_fraction)`.
- `tt`: 11-Element-Tuple (year, month, day, hour, min, sec, wday, yday, isdst, tzname, gmtoff)
- `fraction`: Mikrosekunden (int)
- `gmtoff_fraction`: Mikrosekunden des GMTOffsets (int), `None` wenn kein TZ

## Getestet

- Normale Daten (`2026-06-28`, `%Y-%m-%d`) → Original-Funktion, kein Overhead
- ISO mit TZ (`2026-06-28 00:00:00+00:00`) → dateutil-Fallback, korrekt
- ISO mit Z (`2026-06-28T10:30:00Z`) → dateutil-Fallback, korrekt
- yfinance echte Daten → funktioniert