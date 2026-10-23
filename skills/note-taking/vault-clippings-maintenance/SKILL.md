---
name: vault-clippings-maintenance
description: "Use for vault conflict or Clippings cleanup."
metadata:
  hermes:
    tags: [obsidian, clippings, bisync, dedupe, scanner]
---

# Vault-Clippings-Wartung

Umbrella für Konflikt-Cleanup nach rclone bisync, Clippings-Einsortierung und Ingest-Scanner-Pflege. Die Obsidian-Basics stehen im Skill `obsidian`. Dieser Skill beschreibt nur die Wartungs-Workflows.

## Grundregeln (immer)

- **Klassifizieren vor Löschen.** Jede Kopie gegen das Original prüfen. Das Original darf nie allein auf Verdacht gelöscht werden.
- **Backup vor jeder Veränderung**, auch vor Verschiebungen. Der Vault ist kein Git-Repo.
- **Dry-run, dann Ausführung.** Plan als Liste (alt → neu bzw. Datei → Entscheidung) zeigen, bei unklaren Dateien den User entscheiden lassen.
- **Verify-after-write.** Eine Erfolgsmeldung wie „N geschrieben“ ist kein Beleg. Den geschriebenen Wert neu einlesen und gegen den Soll-Wert vergleichen, bevor der nächste Schritt startet. Batch-Schreiber können Einträge zählen, die nie gespeichert wurden, weil die Zählung vor dem Schreiben passiert.

## Workflow A: Bisync-Konflikte (`*.conflict1..N`)

1. **Erfassen, lokal und remote.** Remote nur Dateien listen: `rclone lsf -R --files-only gdrive:<pfad>/ | grep -E '\.conflict[0-9]+$'`. `rclone lsf -R --include` gibt Ordnernamen aus und ist zum Filtern ungeeignet.
2. **Remote-Originale einmal komplett listen** und lokal abgleichen. Pro-Datei-Abfragen (`lsjson`) laufen bei 100+ Dateien in den Terminal-Timeout.
3. **Klassifizieren pro Konflikt:**

| Befund | Aktion |
|---|---|
| Original fehlt | nicht anfassen, Kopie ist eventuell die einzige |
| sha256 identisch | sicher löschbar |
| Alle Zeilen der Kopie stehen im Original | sicher löschbar (Teilmenge) |
| Mindestens eine Zeile fehlt im Original | nicht löschen, mergen oder behalten |

   - Keinen Längen- oder Zeichen-Schwellenwert als Rauschfilter einbauen. Kurze Dateien können echten Inhalt tragen.
   - Zeitstempel sind kein Kriterium. Die jüngere Datei kann die kleinere Teilmenge sein.
4. **Mergen nur bei strukturierten Dateien:**
   - JSON-State: Union der Schlüssel, bei Wertkonflikt das Original gewinnt.
   - Link-Indizes: vor dem Vergleich normalisieren (Alias nach `|` abschneiden, Präfix `wiki/` entfernen, lowercase). Ohne Normalisierung meldet der Vergleich hunderte fehlende Ziele, die vorhanden sind.
   - Fließtext (Notizen, Transkripte, Wiki-Seiten): nicht automatisch mergen, Liste an den User.
   - `.obsidian/workspace.json`: nie mergen, Original behalten.
5. **Remote löschen** mit `rclone delete --files-from <textdatei>`, eine Datei pro Zeile. Eine JSON-Liste als Eingabe wird ohne Fehler als Filter gelesen und löscht nichts, der Lauf meldet trotzdem Erfolg.
6. **Verifizieren:** `rclone lsf gdrive:<remote>/<datei>` muss leer sein. Erst danach Erfolg melden.
7. **Ursache prüfen:** Konflikte entstehen, wenn Dateien lokal und remote gleichzeitig geändert wurden. Nicht nur aufräumen.

## Workflow B: Clippings einsortieren

1. **Heuristik mit Wortgrenzen (`\b`).** Ohne sie matchen Substrings (`hof` trifft Hoffmann, `ki` trifft fast alles).
2. **Ausschluss vor Zuweisung.** Trading- und Projekt-Zuordnung zuerst ausschließen, dann Zielordner. Hardware- oder Hobby-Clippings fallen sonst in Trading. Vor dem Verschieben `ls Projekte/` prüfen und den Inhalt lesen.
3. **Mehrdeutige Dateien** nicht still verschieben. Als Liste mit Vorschlag an den User, bei Einzelfragen lieber eine Entscheidungsliste mit Feldern.
4. **Move-Manifest als JSON** schreiben. Es ist die einzige Rollback-Grundlage.
5. **Scanner-DB remappen** (Workflow C), dann Scanner-Testlauf.

## Workflow C: Ingest-Scanner-Pflege

- Der Scanner dedupliziert über **Pfad + vollen sha256**. Ein Eintrag zählt nur, wenn beides stimmt.
- **Remap bei Verschiebung:** Schlüssel `alt → neu` umbenennen, Werte unverändert lassen. Ohne Remap werden alle verschobenen Dateien erneut Kandidaten, mit doppelten LLM-Kosten und doppelten Wiki-Einträgen.
- **Hash-Reset** nur für inhaltlich gleiche Dateien (mtime-Änderung durch Sync reicht als Grund nicht). Vor dem Reset gegen Backup oder Remote-Original diffen.
- **Verify-after-write** nach jedem DB-Schreiben. Der Scanner-Testlauf muss die erwartete Kandidatenzahl liefern. Eine plötzlich große Zahl bedeutet Pfad- oder Hash-Mismatch.
- **Artefakte ausschließen:** `index.md` in Clippings ist ein Wiki-Index, keine Quelle. Per Namensfilter im Scanner überspringen.
- **Vor dem Überschreiben** einer Datei prüfen, ob ein Cron sie aktiv beschreibt: Zielpfad im Cron-Prompt suchen, `enabled` und `last_run_at` in der `jobs.json` lesen. Memory-Notizen zum Cron-Status sind nicht verlässlich.
- **Ersetzen durch Entwurf** nur, wenn der Entwurf eine Obermenge des Originals ist. Einzelne Einträge (z.B. Lektionen) pro Block vergleichen.
- **Ingest-Kopien erkennen:** Eine Clippings-Datei, die sich vom Vault-Original nur im Frontmatter (`origin`) unterscheidet, ist eine Ingest-Kopie und kann weg. Hat sie zusätzliche Inhaltszeilen, gehört sie per Merge ins Original, nicht gelöscht.

Diagnose und Reset-Prozedur für Hash-Mismatches: `references/scanner-hash-reset.md`.

## Verwandte Skills

- `obsidian` — Vault-Basics, Wikilinks, Health-Check, LLM-Wiki-Pattern
