# Deaktivierungs-Verifikation — Restbestände + False-Positive-Falle (24.08.2026)

Teil der DQ-.L-Kette (siehe `uk-microcap-liquidity-gate.md` für den Gate-/Cleanup-/Deaktivierungs-Hintergrund 14.–19.08.).

## Problem
Eine Quellen-Deaktivierung (`source_registry SET enabled=0`) stoppt den **neuen** Zufluss (Scan nur für `enabled=1`), aber **Bestands-Einträge, die bereits aus der Quelle stammen, bleiben in der `watchlist` stehen**. Nach der Share-Talk-Deaktivierung (19.08.) zeigte der Check: Cleanup Stufe 1b droppte nur `.L` **ohne** tech_score, aber 8 `.L` **mit** tech_score (AET, AMRQ, ANTO, ATYM, FRAS, GEX, MPAL, 80M) blieben zu 100% aus der deaktivierten `rss:share talk` im Hauptteil.

## Fix — Zwei-Kennzahlen-Watchdog (`dq_alarm.py`, Cron `37d505cbc47b`)
Neue Kennzahl `count_deactivated_only()` zählt `.L`-Ticker in watching/bought, deren **EINZIGE** Quelle deaktiviert ist. Kombiniert mit dem DQ-Count, Regression-Alarm ab Schwelle 10.

```python
# Kernlogik: channels (JSON-Array) gegen die Menge deaktivierter Quellen
deactivated = set()
for r in con.execute("SELECT display_name FROM source_registry WHERE enabled=0").fetchall():
    n = str(r["display_name"]).strip().lower()
    deactivated.add("rss:" + n); deactivated.add(n)   # channels ist "rss:<lower>" ODER nackter Kanalname

# .L begrenzt! NICHT pauschal auf alle watching/bought.
... WHERE status IN ('watching','bought') AND ticker LIKE '%.L'
# "EINZIGE Quelle": all(c in deactivated for c in chans) — NICHT "irgendeine Quelle deaktiviert"
```

## Cleanup Stufe 1c (`~/.hermes/scripts/watchlist_cleanup.py`, Cron `7e364ce47b69`)
Droppt `.L` **mit** tech_score, wenn 100% aus deaktivierten Quellen stammen → `status='dropped', notes='source-deactivated'`. Lädt die deaktivierte Menge dynamisch aus `source_registry` (kein Hardcode der Quellenliste). **Bought-Positionen werden NICHT angefasst.** Chronologie: läuft nach Export (22:15), vor DQ-Alarm (22:40).

**Pitfall beim Patch:** `watchlist_cleanup.py` hat mehrere fast identische UPDATE-Blöcke (Stufe 1b/1c). Beim Einfügen IMMER eine eindeutige Kontext-Zeile (`WHERE status='watching' AND ticker LIKE '%.L'` + `tech_score IS NULL` vs `IS NOT NULL`) mitnehmen und nach dem Patch mit `read_file` verifizieren, dass nicht der falsche Block getroffen wurde. Diese Datei hatte bereits einen doppelten-Patch-Bug (19.08.): doppelte dropped-Statements + überzähliges `"""` → `IndentationError`.

## Die False-Positive-Falle (der eigentliche Design-Lesson)
Die naive Logik "Eintrag, dessen einzige Quelle deaktiviert ist" auf **alle** watching/bought angewandt flaggt **68 Einträge** — darunter echte Large-Caps wie:
- STLA → nur `patrick boyle` (deaktiviert)
- AEM → nur `urban jäkle` (deaktiviert)
- KKR → nur `meet kevin` (deaktiviert)
- AXP → `markus koch closing bell`, `financial education` (beide deaktiviert)

Deren einziger Kanal ist zwar deaktiviert, aber das sind **historische Bestands-Positionen, keine Signal-Degradierung**. Fix: auf `.L` begrenzen (die DQ-Flut-Quelle). Noch schlimmer wäre ein Check, der "irgendeine deaktivierte Quelle im channels-Mix" zählt: AAPL hat 15 Quellen, darunter mehrere alte deaktivierte rss-Feeds, und würde ewig falsch-alarmen.

## Verifikations-Rezept (24.08., live)
```bash
# Deaktivierungs-Check + DQ-Count: silent wenn keine Regression
cd /root/.hermes/profiles/hermes_trading/skills/trading && PYTHONPATH=. python3 scripts/dq_alarm.py
# Nach dem Cleanup: keine .L aus share talk mehr
sqlite3 data/trading.db \
  "SELECT COUNT(*) FROM watchlist WHERE status IN ('watching','bought') AND ticker LIKE '%.L' AND channels LIKE '%share talk%';"
```
Verifiziert: vorher 27 `.L` ohne Score + 8 mit Score aus share talk → nachher **0** `.L` aus share talk in watching/bought; DQ 16→0; dq_alarm silent. Übrig bleiben nur legitime `.L` (the motley fool uk, pensioncraft — beide enabled=1).

## Lehre (generalisierbar)
Bei "greift die Deaktivierung / wer hängt noch an toten Quellen?" nie pauschal über alle Zeilen zählen — der exklusiv-deaktiviert-Check muss auf die **Klasse** begrenzt sein, die tatsächlich die Datenqualitäts-Flut erzeugt. Ein Check mit breitem Kriterium + Schwellenwert erzeugt Dauer-False-Positives auf gesunden Bestands-Positionen, die er nie "abarbeitet", und betäubt den Alarm.
