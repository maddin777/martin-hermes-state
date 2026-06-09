# Watchlist-Table-Level Dedup

Nachdem `normalize_mentions()` die `watchlist_mentions`-Tabelle bereinigt hat, bleiben in der aggregierten `watchlist`-Tabelle oft stale Duplikate zurück (gleicher Ticker, unterschiedliche Schreibweisen). Diese werden nicht automatisch gemerged, weil `INSERT ... ON CONFLICT(name) DO NOTHING` Case-Varianten als verschiedene Einträge passieren lässt.

## Script: `watchlist_dedup.py`

**Pfade:** `/root/.hermes/scripts/watchlist_dedup.py` (Cron-kompatibel) und `/root/.hermes/profiles/hermes_trading/skills/trading/scripts/watchlist_dedup.py`

**Drei Phasen:**

### Phase 1: Ticker-Varianten angleichen
Bekommt bekannte Ticker-Gruppen (NVDA + NVD.DE, SAP.DE + SAP etc.) und normalisiert den Ticker auf einen kanonischen, bevor Phase 2 greift.

Manuelles Mapping in `TICKER_GROUPS` — erweiterbar bei neuen Cross-Listing-Tickern.

### Phase 2: Ticker-basiert mergen
Gruppiert alle `watching`-Einträge mit identischem Ticker. Für jede Gruppe:

1. **Canonical-Name**: Bevorzugt den kürzesten Namen OHNE Legal-Suffix (Inc., Corp., AG, SE etc.), sonst den der exakt dem normalisierten Namen entspricht
2. **Stats-Aggregation**: Summiert `mention_count`, `bullish_count`, `bearish_count`, `neutral_count`, `conviction_score`, `conviction_score_bear`
3. **Channels**: Union aller Channel-Listen
4. **Date Range**: Frühestes first_seen, spätestes last_seen
5. **Droppen**: Alle Nicht-Canonical-Einträge → `status='dropped'`, `notes='merged into <canonical>'`

### Phase 3: Name-basiert mergen (ohne Ticker)
Für Einträge ohne Ticker: Gruppierung per `normalize_company_name()`, gleiche Merge-Logik.

## Ergebnis der Erstbereinigung (28.05.2026)

```
Vorher: 848 watching
Nachher: 749 watching (-99, 11,7%)
Zwei Durchläufe nötig (zweiter fing neu aus mentions re-aktivierte)
0 verbleibende Ticker-Duplikate
0 verbleibende Case-Varianten
```

## Cron

- **Schedule**: Sonntags 05:30 (Cron-ID: `472ace6fe18a`)
- **Script**: `/root/.hermes/scripts/watchlist_dedup.py`
- **Profil**: hermes_trading (importiert `watchlist_manager` aus trading scripts)

Manuell ausführen:
```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading/scripts
python3 watchlist_dedup.py
```

## Nach dem Dedup: Refresh

Nach dem Mergen der Watchlist-Einträge sollte eine Re-Aggregation laufen, damit die Conviction-Scores korrekt aus den Mentions neu berechnet werden (statt summiert aus alten capped-Werten).

Script: `/root/.hermes/scripts/refresh_watchlist.py`
```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading/scripts
python3 /root/.hermes/scripts/refresh_watchlist.py
```

Das Refresh nutzt bestehende Ticker aus der DB (kein yfinance-Call für bekannte Ticker) und aggregiert nur Mentions aus den letzten 14 Tagen. Die nächste 04:00-Pipeline überschreibt ohnehin alles, also ist der Refresh optional.

## Bekannte Einschränkungen

- **Conviction-Score nach Merge**: Summierte Scores (z.B. 4×1.0 → 4.0) sind interimistisch — die Pipeline am nächsten Morgen kappt auf max 1.0 via `min(round(...), 1.0)`
- **Alias-Map muss aktuell sein**: Fehlende Aliases (z.B. "take two interactive software") führen dazu, dass Mentions in Phase 3 nicht gemerged werden
- **Env-Loader**: Bei Cron-Ausführung fehlt `env_loader` im Pfad → `sys.path.insert(0, scripts_dir)` nötig