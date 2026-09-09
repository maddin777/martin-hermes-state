# Export-Watchlist Channel-Determinismus + DB-Test-Pitfall (08.09.2026)

## Problem: Quellen-Attributions-Oszillation (Tag 9)

Der vault-insights-daily zählte die Quellen-Attribution ("mario lochner 20→7,
techaktien 6→24") aus der **Kanäle-Spalte der exportierten `Trading/Watchlist.md`**.
Die Zählung oszillierte über 9 Tage wild, obwohl die Rohdaten (watchlist_mentions)
stabil waren.

## Root-Cause

`export_watchlist.py` rendert die Kanäle-Spalte als:
```python
channels_str = ", ".join(list(set(channels_raw))[:3])
```
`list(set(x))` ist **per-Prozess nicht-deterministisch** — Python randomisiert den
Hash-Seed pro Interpreter-Start (PYTHONHASHSEED). Derselbe Kanalsatz ergibt in
verschiedenen Prozess-Läufen **andere** Top-3-Kanäle. Der Export lief als no_agent
Cron (neuer Prozess je Lauf) → jede Nacht andere Kanäle gerendert → die daraus
abgeleitete Quellen-Zählung oszillierte, obwohl die Daten nie verändert wurden.

Beweis im Session-Test: 5 identische `list(set(chans))[:3]`-Läufe lieferten 5
verschiedene Top-3.

## Fix (verifiziert)

Deterministisch sortieren + volle Kanalliste statt Top-3-Kürzung (damit die
Quellen-Zählung die komplette Kanal-Attribution erfasst):
```python
channels_str = ", ".join(sorted(set(channels_raw)))
```
In `export_watchlist.py` an BEIDEN Stellen (Haupt-Tabelle + DQ-Block), sowie in der
State-Backup-Kopie unter `/root/martin-hermes-state/profiles/hermes_trading/skills/trading/scripts/`
(`cp` der Live-Datei nach dem Patch).

Verifikation: zwei Export-Läufe in separaten Prozessen → Kanäle-Spalte byte-identisch.

## Allgemeine Regel

**NIE `list(set(x))[:n]` oder `set(x)` für geordnete/attributierte Ausgabe verwenden**
wenn mehrere Läufe dieselbe Ausgabe erzeugen sollen. Wenn Reihenfolge egal ist aber
Bestandteil einer Statistik/Ausgabe: IMMER `sorted(set(x))`. Das betrifft besonders
no_agent-Crons, die als frischer Prozess je Lauf laufen.

## DB-Test-Pitfall: db_connect-Pfad-Override per sed scheitert

Beim Testen eines neuen Watchlist-Scripts versuchte ich, die Produktiv-DB durch eine
Kopie zu ersetzen, indem ich den Zeichenstring `data/trading.db` per `sed` im Script
überschrieb. Das **griff nicht**: Das Script importiert `db_connect` aus `config.py`
(`db_connect()` → benutzt `DB_PATH` mit hartkodiertem Pfad), sodass der sed am
Script-String wirkungslos war und der "Test" unbeabsichtigt auf die **Live-DB** schrieb.

**Fix:** `config.db_connect()` hat einen optionalen Parameter `db_connect(path=None)`.
Neue Scripts MÜSSEN einen `--db`-Argument-Parameter bekommen:
```python
parser.add_argument("--db", default=DB_PATH, help="DB-Pfad (default: Produktiv). Tests: Kopie-Pfad.")
...
con = db_connect(args.db)
```
Dann ist ein echter Kopie-Test möglich: `--apply --db /tmp/copy.db`. Das verhindert
unbeabsichtigte Produktiv-Writes beim Testen. Bei allen 25 Pipeline-Scripts gilt: zum
Testen IMMER den optionalen DB-Pfad verwenden, nie sed-Override am Script-String.
