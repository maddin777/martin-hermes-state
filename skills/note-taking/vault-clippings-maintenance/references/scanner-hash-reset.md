# Scanner-DB: Hash-Reset und Mismatch-Diagnose

Der Ingest-Scanner (`clippings-scanner.py`) vergleicht pro Eintrag `db[relpath] == sha256(vollstaendige Datei)`. Stimmt eins nicht, gilt die Datei als neu und wird erneut ingestiert.

## Diagnose: Warum meldet der Scanner N Kandidaten?

1. Scanner read-only laufen lassen und die Kandidatenliste ausgeben.
2. Pro Kandidat prüfen, ob der Schlüssel in der DB existiert:
   - Schlüssel fehlt → Pfad-Remap vergessen (Datei wurde verschoben).
   - Schlüssel existiert, Hash ungleich → Datei hat sich inhaltlich geändert ODER der gespeicherte Hash stammt aus einer anderen Quelle.
3. Bei Hash-Mismatch: `mtime` der Datei prüfen. Ein Bisync-Lauf verändert mtime ohne Verschiebung. Verschieben lässt mtime unverändert, Bisync nicht.
4. Vor einem Reset inhaltlich gegen Backup oder Remote-Original diffen. Ein Reset auf den aktuellen Hash ist nur für inhaltlich gleiche Dateien richtig.

## Reset-Prozedur

- Backup der DB vor jeder Änderung (`cp -a`, Zeitstempel im Namen).
- Nur die betroffenen Keys ändern, nicht die ganze DB neu schreiben.
- Nach dem Schreiben DB neu einlesen und jeden Wert gegen `sha256(datei)` prüfen. Zähler aus dem Schreibschritt sind kein Beleg.
- Scanner erneut laufen lassen. Erwartung: nur echte Neuzugänge bleiben.

## Pitfall: Erster Reset meldete Erfolg, Wert blieb alt

Ein Schreibschritt hat „geschrieben 50“ gemeldet, der Scanner zeigte danach trotzdem 50. Die Prüfung per Neuberechnung und Neueinlesen hat den Fehler gezeigt. Die Ursache wurde nicht eindeutig geklärt. Deshalb gilt: Immer nach dem Schreiben einzeln verifizieren, nie nur den Zähler vertrauen.

## Pitfall: Scanner-Filter für Artefakte

Wiki-Index-Dateien (`index.md`) und Systemdateien sind keine Quellen. Sie im Scanner per Namensfilter überspringen, nicht löschen. Der Filter muss vor dem Hash-Vergleich greifen, sonst entstehen Kandidaten ohne Ingest-Ziel.
