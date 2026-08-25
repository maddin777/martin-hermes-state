# Deaktivierungs-Verifikation + Cleanup Stufe 1c (24.08.2026)

Nachdem eine Rausch-Quelle deaktiviert ist (z.B. `rss:share talk`, enabled=0,
19.08.), muss aktiv verifiziert werden, OB die Deaktivierung greift — sonst
bleiben Bestands-Einträge aus der toten Quelle ewig in der Watchlist stehen.

## Kern der Lücke

Eine Deaktivierung (`source_registry enabled=0`) stoppt nur NEUEN Zufluss.
Ob sie "gegriffen hat" = ob Einträge, deren EINZIGE Quelle deaktiviert ist,
aus der `watchlist` verschwinden. Das muss man explizit überwachen (Cleanup +
Alarm), nicht still annehmen.

Konkret: Cleanup Stufe 1b droppte nur `.L` **ohne** `tech_score` (`no-liquidity-gate`).
Aber **8 `.L`-Einträge MIT tech_score** (AET, AMRQ, ANTO, ATYM, FRAS, GEX,
MPAL, 80M) blieben zu 100% aus `rss:share talk` im Watchlist-Hauptteil, weil
sie als "gecastet" galten. Stufe 1c fängt genau diesen nachgelagerten Rest.

## Fix 1 — `watchlist_cleanup.py` Stufe 1c (Cron `7e364ce47b69`, Mo–Fr 22:30, `--apply`)

```python
# 1) deaktivierte Quellen (enabled=0) als lowercase-Set laden
deactivated = set()
for r in con.execute("SELECT display_name FROM source_registry WHERE enabled=0").fetchall():
    name = str(r["display_name"]).strip().lower()
    deactivated.add("rss:" + name)   # channels nutzt "rss:<display_name>"...
    deactivated.add(name)            # ...oder reinen Kanalnamen — BEIDE nötig!

# 2) channels (JSON-Array-String) parsen (try/except)
def _chans(val):
    if not val: return []
    try: return [c.strip() for c in json.loads(val) if c.strip()]
    except Exception: return []

# 3) NUR .L MIT tech_score: wenn channels ZU 100% aus deaktivierten Quellen
#    besteht → dropped. rowid-Regel! bought-Positionen NICHT anfassen.
for r in con.execute(
    "SELECT rowid, ticker, channels FROM watchlist "
    "WHERE status='watching' AND ticker LIKE '%.L' AND tech_score IS NOT NULL"
).fetchall():
    chans = _chans(r["channels"])
    if chans and all(c in deactivated for c in chans):
        con.execute("UPDATE watchlist SET status='dropped', notes='source-deactivated' WHERE rowid=?", (r["rowid"],))
```

## Fix 2 — `dq_alarm.py` Kennzahl `count_deactivated_only()` (Cron `37d505cbc47b`, Mo–Fr 22:40)

Zählt `.L`-Ticker in watching/bought, deren EINZIGE Quelle deaktiviert ist,
als eigene Kennzahl NEBEN dem DQ-Count. Regression ab Schwelle 10 →
Telegram-Alarm mit Ticker-Liste. State-File `data/dq_alarm_state.txt` bleibt.

## ❗ False-Positive-Falle (der eigentliche Lernpunkt)

Der erste naive Ansatz — "ALLE Einträge zählen, deren einzige Quelle
deaktiviert ist" — flaggte plötzlich **68** Einträge. Large-Caps wie
- **STLA** (nur aus `patrick boyle`)
- **AEM** (`urban jäkle`)
- **KKR** (`meet kevin`)
- **AXP** (`markus koch closing bell`)

wurden als "exklusiv deaktiviert" gematcht, weil ihre YouTube-Kanäle
inzwischen `enabled=0` sind. Das ist KEINE Signal-Degradierung — das sind
historische Bestands-Positionen mit nur einem Kanal.

**Regel:** Der Check muss auf den **Ticker-Namespace `.L`** begrenzt sein (die
DQ-Flut-Quelle), NICHT breit über alle Ticker laufen. Ein Large-Cap mit
einzelnem toten Kanal ist kein DQ-Problem. Durch eine `.L`-WHERE-Klausel:
False-Positives 68 → 0, echter Fund 33 (25 ohne + 8 mit Score).

## Verifikation (24.08. live)

- Cleanup droppte 27 (Stufe 1b) + 8 (Stufe 1c); danach **0** `.L` aus share
  talk in watching/bought; übrig nur legitime (the motley fool uk, pensioncraft).
- `dq_alarm.py` silent (0/0).
- Geänderte Dateien (dq_alarm.py, Erklaerung.md) in `martin-hermes-state`
  synchronisiert. `~/.hermes/scripts/watchlist_cleanup.py` hat KEINE
  State-Kopie — nur die Live-Datei (die no_agent-Cron-Quelle).

## Lehre (allgemein für DQ-/Audit-Checks)

Beim Bauen eines "deaktiviert-Quelle"-Audits IMMER den Ticker-Raum auf die
Domäne eingrenzen, die das Rauschen erzeugt. Ein Audit über den gesamten
Bestand mischt historische Bestände mit akutem DQ und alarmiert falsch.