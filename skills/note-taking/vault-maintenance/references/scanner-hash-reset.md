# Scanner-DB: Hash-Reset und Mismatch-Diagnose

Detail zu W5 des Skills `vault-maintenance`. Der Ingest-Scanner (`clippings-scanner.py`) vergleicht pro Eintrag `db[relpath] == sha256(vollständige Datei)`. Stimmt eins nicht, gilt die Datei als neu und wird erneut ingestiert.

## Diagnose: Warum meldet der Scanner N Kandidaten?

1. Scanner read-only laufen lassen und die Kandidatenliste ausgeben.
2. Pro Kandidat prüfen, ob der Schlüssel in der DB existiert:
   - Schlüssel fehlt → Pfad-Remap vergessen (Datei wurde verschoben).
   - Schlüssel existiert, Hash ungleich → Datei inhaltlich geändert ODER gespeicherter Hash stammt aus anderer Quelle.
3. Bei Hash-Mismatch die `mtime` prüfen: Ein Bisync-Lauf verändert mtime ohne Verschiebung; ein Move lässt sie unverändert.
4. Vor einem Reset inhaltlich gegen Backup oder Remote-Original diffen. Ein Reset auf den aktuellen Hash ist nur für inhaltlich gleiche Dateien richtig.

## Reset-Prozedur

- Backup der DB vor jeder Änderung (`cp -a` mit Zeitstempel im Namen).
- Nur die betroffenen Keys ändern, nicht die ganze DB neu schreiben.
- Nach dem Schreiben die DB neu einlesen und jeden Wert gegen `sha256(datei)` prüfen. Zähler aus dem Schreibschritt sind kein Beleg — ein Lauf hat „geschrieben 50“ gemeldet, während der Scanner weiter 50 Kandidaten zeigte.
- Scanner erneut laufen lassen. Erwartung: nur echte Neuzugänge bleiben.

## Filter für Artefakte

Wiki-Index-Dateien (`index.md`) und Systemdateien sind keine Quellen. Im Scanner per Namensfilter überspringen, nicht löschen. Der Filter muss vor dem Hash-Vergleich greifen, sonst entstehen Kandidaten ohne Ingest-Ziel.
