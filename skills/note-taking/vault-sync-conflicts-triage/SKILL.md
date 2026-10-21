---
name: vault-sync-conflicts-triage
description: Use for Obsidian sync conflicts and Clippings sorting.
---

# Vault-Sync-Konflikte und Clippings-Triage

Gilt für den Obsidian-Vault im GDrive-Bisync. Reihenfolge einhalten, nichts ohne Backup und Prüfung löschen oder verschieben.

## Konflikt-Dateien (rclone bisync)

rclone bisync erzeugt bei gleichzeitigen Änderungen Kopien mit Suffix `.conflictN`. Die Originale sind nicht betroffen.

1. **Lokal finden:** `find . -type f -name '*.conflict[0-9]*'`
2. **Remote finden:** `rclone lsf -R --files-only gdrive:<remote-pfad>/ | grep -E '\.conflict[0-9]+$'`. Ohne `--files-only` listet rclone auch Ordner, und `--include` filtert dann falsch.
3. **Sichern vor jeder Löschung:** lokal `tar -czf` der Konfliktdateien; remote `rclone copy --files-from <liste>` in ein Scratch-Verzeichnis. Bei großen Mengen im Hintergrund laufen lassen, Foreground-Timeouts sprengen sonst den Download.
4. **Pro Konflikt prüfen:**
   - Byte-identisch zum Original → löschbar.
   - Zeilen-Teilmenge des Originals (jede Zeile der Kopie steht im Original) → löschbar.
   - Eindeutige Zeilen → nicht blind löschen. Vergleich per Zeilenmenge, dann entscheiden.
5. **Original fehlt remote:** Die Konfliktdatei kann die einzige Kopie sein. Nicht löschen ohne Entscheidung.
6. **Remote löschen** erst nach lokaler Verifikation und Freigabe.

### Inhalts-Regeln

- Das Original ist meist der neuere Stand. Export-Header und `updated:`-Felder prüfen, nicht nur Dateigröße oder mtime.
- JSON-Pfad-Listen (z. B. Scanner-DB): Keys-Union, Original gewinnt bei Konflikt.
- Wiki-Index mit Link-Listen: Link-Ziele normalisieren (Präfix `wiki/` weg, Alias nach `|` abschneiden) vor dem Vergleich. Ohne Normalisierung meldet der Vergleich hunderte falsche Fehlende.
- `.obsidian/workspace.json` ist nur UI-Zustand, löschbar.

## Clippings-Triage

### Regeln

- Trading-Clippings bleiben im Trading-Flow. Alles andere raus aus dem Clippings-Root in passende Zielordner.
- Segeln, Boot und Hardware gehören in das Projekt (z. B. `Projekte/MarineIT/`), nicht ins Trading. Keyword-Treffer wie `signal`, `chart` sind bei Segel-Themen Fehlzuordnungen.
- Unklare Dateien nie blind verschieben. Liste erstellen, Entscheidung beim User.
- Projekt-Manuskripte (Kapitel, Gutachten) bleiben im Clippings-Root.

### Ablauf

1. **Backup** des Clippings-Ordners als tgz.
2. **Dry-Run** mit Keyword-Regeln, Ergebnis als Liste ausgeben, bevor verschoben wird.
3. **Regex mit Wortgrenzen** (`\b`). Ohne sie matcht `hof` in `Hoffmann`/`Bischoff`, `gold` in `Goldie`, `hebel` in Business-Titeln.
4. **Verschieben** per `shutil.move`, Manifest alt→neu schreiben für Rollback.
5. **Scanner-DB remappen:** Der Clippings-Ingest dedupliziert über den Pfad (`.hermes/clippings_processed.json`). Ohne Remap werden verschobene Dateien erneut ingestiert (doppelte LLM-Kosten, doppelte Wiki-Einträge). Keys auf den neuen Pfad umschreiben.
6. **Verifizieren:** Scanner read-only laufen lassen. Erwartung: nur noch nicht ingestierte Dateien als Kandidaten.
7. **Rest-Liste** in drei Gruppen: bleibt (Trading/Projekt), offen (User entscheidet), Systemdateien (Vault-Root, nicht verschieben).

### Entscheidungsdatei für den User

Markdown mit Checkbox pro offene Datei, Vorschlag und Feld `Ziel: →`. Der User trägt den Zielordner ein. Danach verschieben, Scanner-DB remappen, Manifest schreiben.
