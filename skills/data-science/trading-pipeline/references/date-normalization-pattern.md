# Datum-Normalisierung (YYYYMMDD → YYYY-MM-DD)

## Problem

Zwei Felder sind betroffen:

1. **`watchlist.last_seen`** — 47 Einträge im Format `YYYYMMDD` (Juli 2026 bereinigt)
2. **`watchlist_mentions.mention_date`** — 120 Einträge im Format `YYYYMMDD`, alle vom Channel `urban jäkle` (Juli 2026 bereinigt)

Das killt automatisierte Sortierung, `MAX()/MIN()`-Aggregation und Altersanalyse in SQLite, weil String-Vergleiche bei gemischten Formaten falsche Ergebnisse liefern. Beispiel: `MAX(mention_date)` gibt `20260619` (19. Juni) zurück obwohl `2026-07-23` (23. Juli) existiert — weil der Bindestrich `-` (ASCII 45) vor der `0` (ASCII 48) alphabetisch eingeordnet wird.

## Root Cause

YouTube liefert `upload_date` im Format `YYYYMMDD`. Dieser Wert wandert unverändert durch die Pipeline:

1. **`yt_channel_monitor.py`** speichert `upload_date` von YouTube direkt in die `videos`-Tabelle → `YYYYMMDD`
2. **`signal_extractor.py`** (Zeile 631) übergibt `row['upload_date']` als `"date"` in den `source`-Dict → immer noch `YYYYMMDD`
3. **`watchlist_manager.py`** (Zeile 444) empfängt `YYYYMMDD` und versucht `strptime(str(date), "%Y%m%d")` — das funktioniert ABER NUR wenn kein Bindestrich im String ist. Der Default-Fallback war `datetime.now().strftime("%Y%m%d")` — auch ohne Trennstriche!

## Fixes (23.07.2026)

### 1. signal_extractor.py — Quelle normalisieren

```python
# Vorher: raw upload_date (YYYYMMDD)
"date": row['upload_date'],

# Nachher: normiert auf YYYY-MM-DD
"date": row['upload_date'][:4] + '-' + row['upload_date'][4:6] + '-' + row['upload_date'][6:8]
        if row['upload_date'] and len(row['upload_date']) == 8
        else row['upload_date'],
```

### 2. watchlist_manager.py — Beide Formate parsen + Default fixen

```python
# Vorher: Default %Y%m%d, strptime nur für YYYYMMDD
date = source.get("date", datetime.now().strftime("%Y%m%d"))
mention_date = datetime.strptime(str(date), "%Y%m%d").strftime("%Y-%m-%d")

# Nachher: Default %Y-%m-%d, erkennt beide Formate
date = source.get("date", datetime.now().strftime("%Y-%m-%d"))
date_str = str(date).strip()
if len(date_str) == 8 and date_str.isdigit():
    mention_date = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
else:
    mention_date = date_str[:10]
```

### 3. DB-Bereinigung (einmalig)

```sql
UPDATE watchlist_mentions
SET mention_date = substr(mention_date, 1, 4) || '-' || substr(mention_date, 5, 2) || '-' || substr(mention_date, 7, 2)
WHERE mention_date NOT LIKE '____-__-__' AND length(mention_date) = 8;

UPDATE watchlist
SET last_seen = substr(last_seen, 1, 4) || '-' || substr(last_seen, 5, 2) || '-' || substr(last_seen, 7, 2)
WHERE length(last_seen) = 8 AND last_seen GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]';
```

## Prävention

- Jeder Pipeline-Schritt der ein Datum aus YouTube (`upload_date`) oder RSS (`m[3]`) verarbeitet, muss das Format NACH dem Einlesen und VOR dem Speichern normalisieren
- `watchlist_manager.py` hat jetzt einen generischen Parser der beide Formate erkennt — als Sicherheitsnetz für Fälle wo die Normalisierung in einem vorgelagerten Schritt vergessen wurde
- Bei `MAX(mention_date)` / `ORDER BY mention_date` immer prüfen ob die Formate einheitlich sind — sonst sind die Ergebnisse (stille) falsch