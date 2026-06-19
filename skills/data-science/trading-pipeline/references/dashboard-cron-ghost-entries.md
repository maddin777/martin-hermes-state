# Dashboard Ghost Entries: Status Determination

## Wie der Dashboard Cron-Tab Status zeigt

`dashboard.py` `get_cron_jobs()` (ca. Zeile 132–190):

### Schritt 1: Crontab parsen
```python
# Filtert crontab-Zeilen nach fest codierten Script-Namen
if not any(k in line for k in [
    "yt_channel","signal_",
    "watchlist_manager","strategy_optimizer","trading_db",
    "fundamental_data","social_scanner","export_watchlist",
    "active_exit_check","trading_pipe","nightly_eval"
]): continue
```

**Hinweis:** `technical_validator` wurde am 11.06.2026 aus diesem Filter entfernt, da es keinen eigenen Cron-Job mehr hat (läuft embedded in trading_pipeline.py).

### Schritt 2: Status aus cron.log extrahieren
```python
def get_last_run(script_name):
    LOG_ALIASES = {
        "watchlist_manager": "Watchlist Update",
        "signal_extractor": "KI Analyse",
    }
    # Sucht nach "Technical Analysis" im Log für technical_validator
    # Findet "=== 05:01:58 Technical Analysis DONE ===" → Status OK
    # Findet "=== Technical Analysis ERROR" → Status Fehler
    # Findet GAR NICHTS → Status "–" (default) → gelb
```

### Schritt 3: Farbe bestimmen
```python
sc = "color:#00e676" if j['last_status']=="OK"        # grün
    else "color:#ff5252"  if j['last_status']=="Fehler"  # rot
    else "color:#ffd740"                                 # gelb (fallback)
```

### Ghost-Entstehung

1. Ein Script wird in `trading_pipeline.py` absorbiert und aus der crontab entfernt
2. `descriptions`-Dict in `dashboard.py` hat noch den Eintrag (z.B. `"technical_validator": "Technische Analyse ..."`)
3. `get_cron_jobs()` erstellt einen Job-Eintrag mit diesem Namen
4. `get_last_run(script_name)` sucht nach dem Log-Eintrag
5. Findet keinen DONE/ERROR-Eintrag → Status "–" → gelb (#ffd740)

### Angewendeter Fix (11.06.2026) — technical_validator

**Problem:** `technical_validator` zeigte gelb "–" weil es keinen eigenen Cron-Job mehr hatte.

**Fix in dashboard.py:**
1. `descriptions`-Dict: `"technical_validator"`-Eintrag durch Kommentar ersetzt
2. Crontab-Filter: `"technical_validator"` aus der `any()`-Liste entfernt
3. Dashboard neugestartet

### Angewendeter Fix (18.06.2026) — watchlist_manager

**Problem:** `watchlist_manager` zeigte ebenfalls gelb "–" (gleiche Ursache: läuft embedded in trading_pipeline.py, kein eigener Cron-Job).

**Fix in dashboard.py:**
1. `descriptions`-Dict: `"watchlist_manager"`-Eintrag durch Kommentar ersetzt (Zeile 137)
2. Crontab-Filter: `"watchlist_manager"` aus der `any()`-Liste entfernt (Zeile 164)
3. Dashboard neugestartet: `pkill -f dashboard.py` (Watchdog startet neu) oder `cd /root/.hermes/profiles/hermes_trading/skills/trading && python3 dashboard.py &`

**Hinweis:** `LOG_ALIASES` (Zeile 102) für `watchlist_manager` wurde nicht entfernt — ist inaktiver Dead Code, da der Name nicht mehr im `descriptions`-Dict referenziert wird. Nicht störend, aber bei nächster Bereinigung entfernbar.

### Checkliste für zukünftige Absorptionen

Wenn ein weiteres Script in `trading_pipeline.py` absorbiert wird:

- [ ] Aus `descriptions`-Dict entfernen (ca. Zeile 133)
- [ ] Aus crontab-Filter-String entfernen (ca. Zeile 164)
- [ ] Dashboard neustarten (pkill + Watchdog oder manuell)
- [ ] Prüfen ob der Ghost noch im Tab auftaucht (Browser-Refresh)