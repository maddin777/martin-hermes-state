---
name: vault-maintenance
description: "Obsidian vault upkeep: Bisync conflicts, moves, Clippings."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [obsidian, vault, clippings, bisync, conflicts, moves, link-rewrite, frontmatter, scanner]
---

# Vault-Wartung (Obsidian, GDrive-Bisync)

Umbrella für alle Vorgänge, die den Vault **verändern**: Bisync-Konflikt-Cleanup, Clippings-Einsortierung, ingest-sichere Moves, Link-Umbiegen, Frontmatter-Schema, Ingest-Scanner-DB. Vault-Basics (Lesen, Wikilinks, Health-Check, MOC, LLM-Wiki) stehen im Skill `obsidian` — hier nicht duplizieren.

## When to Use

- Sync-Konflikt-Dateien (`*.conflictN`) nach einem `rclone bisync`-Lauf aufräumen
- Clippings aus einem Root-Ordner in Themenordner einsortieren (manuell oder per Cron)
- Dateien oder ganze Ordner im Vault verschieben/umbenennen, wenn ein Ingest-Scanner den Ordner liest
- Wikilinks/Markdown-Links nach einem Move reparieren
- Frontmatter-Felder (`kind`, `origin`, `topic`) prüfen, setzen oder migrieren
- Ingest-Scanner-DB (Pfad+sha256) remappen oder einen Hash-Mismatch diagnostizieren

## Grundregeln (gelten für jeden Workflow)

1. **Klassifizieren vor Löschen.** Jede Kopie gegen das Original prüfen; das Original nie allein auf Verdacht löschen.
2. **Backup vor jeder Veränderung**, auch vor Moves. Der Vault ist kein Git-Repo. tgz mit Zeitstempel in den Scratch-Ordner.
3. **Dry-run, dann Ausführung.** Plan als Liste (alt → neu bzw. Datei → Entscheidung) zeigen. Unklares entscheidet der User, nicht der Batch.
4. **Verify-after-write.** „N geschrieben“ ist kein Beleg: den geschriebenen Wert neu einlesen und gegen den Soll-Wert prüfen, bevor der nächste Schritt startet. Batch-Schreiber zählen oft vor dem Schreiben.
5. **Ein Move ist ein DB-Ereignis, kein Umzug.** Jeder Move braucht Manifest + Scanner-DB-Remap, sonst doppelte LLM-Kosten und doppelte Wiki-Einträge.
6. **Zeitstempel und Dateigröße sind keine Kriterien.** Die jüngere Datei kann die kleinere Teilmenge sein; die Konflikt-Version kann die neuere Fassung sein.
7. **Zählungen nur über die Dateiart, die du änderst** (Markdown). Nicht-Markdown verfälscht die Zahlen.

## W1 — Bisync-Konflikte (`*.conflict1..N`)

rclone bisync erzeugt bei gleichzeitigen Änderungen Kopien mit Suffix `.conflictN`; die Originale sind unberührt.

1. **Erfassen, lokal und remote.** Remote nur Dateien listen: `rclone lsf -R --files-only gdrive:<pfad>/ | grep -E '\.conflict[0-9]+$'`. `--include` listet auch Ordner und filtert dann falsch. Remote-Originale einmal komplett listen — `lsjson` pro Datei läuft bei 100+ Dateien in den Terminal-Timeout.
2. **Sichern** vor jeder Löschung (lokal `tar -czf`, remote `rclone copy --files-from <liste>`). Große Mengen im Hintergrund starten, sonst sprengt der Foreground-Timeout den Download.
3. **Pro Konflikt klassifizieren:**

| Befund | Aktion |
|---|---|
| Original fehlt | nicht anfassen — die Kopie ist eventuell die einzige |
| sha256 identisch | sicher löschbar |
| Jede Zeile der Kopie steht im Original | sicher löschbar (Teilmenge) |
| Mindestens eine Zeile fehlt im Original | nicht löschen — mergen oder behalten |

Kein Längen- oder Zeichen-Schwellenwert als Rauschfilter: kurze Dateien können echten Inhalt tragen.

4. **Mergen nur bei strukturierten Dateien:** JSON-State → Union der Keys, bei Wertkonflikt gewinnt das Original. Link-Indizes → Ziele vorher normalisieren (`wiki/`-Präfix weg, Alias nach `|` abschneiden, lowercase), sonst meldet der Vergleich hunderte vorhandene Ziele als fehlend. Fließtext (Notizen, Transkripte) → nicht automatisch mergen, Liste an den User. `.obsidian/workspace.json` → nie mergen, Original behalten.
5. **Remote löschen:** `rclone delete --files-from <textdatei>`, eine Datei pro Zeile. Eine JSON-Liste wird ohne Fehler als Filter gelesen, löscht nichts — und der Lauf meldet trotzdem Erfolg.
6. **Verifizieren:** `rclone lsf gdrive:<remote>/<datei>` muss leer sein. Erst danach Erfolg melden.
7. **Ursache prüfen, nicht nur aufräumen:** Konflikte entstehen bei gleichzeitiger lokaler und remote Änderung.

## W2 — Clippings einsortieren

1. **Projekte vor Themen.** Vor jeder Keyword-Klassifikation die Projektordner ansehen (`Projekte/*`): Software-Doku, Manuskripte, Hardware-Builds gehen ins Projekt, nicht nach Thema. Projektzugehörigkeit schlägt Stichwort.
2. **Ausschluss vor Zuweisung.** Trading- und Projektzuordnung zuerst ausschließen, dann Zielordner — sonst fallen Hardware- oder Hobby-Clippings ins Trading.
3. **Regex mit Wortgrenzen (`\b`).** Ohne sie matcht `hof` in Hoffmann/Bischoff, `gold` in Goldie, `signal` in Segel-Titeln („Signal K“), `hebel` in Business-Titeln.
4. **Finanz-/Trading-Inhalte nie allein per Keyword verschieben** — nur nach Sichtprüfung der Titel.
5. **Mehrdeutiges nicht still verschieben.** Als nummerierte md-Tabelle vorlegen (Felder: Datei, Vorschlag, `Ziel: →`) und die Zuordnung des Users eintragen lassen. Rückfragen bündeln. Rückfrage-Tools können leer zurückkommen — dann die Frage als Klartext-Tabelle in den Chat schreiben, nicht den Batch warten lassen.
6. **Move-Manifest als JSON** schreiben (`{old, new}`) — die einzige Rollback-Grundlage. Manifest VOR dem DB-Remap schreiben, sonst fehlt nach einem Abbruch die Zuordnung.
7. **Nie existierende Ziele überschreiben** — Kollision: skippen und melden.
8. **Scanner-DB remappen** (W5) und Scanner read-only testen.
9. **Frontmatter nach dem Move prüfen:** `kind`, `origin`, `topic` gesetzt und passend zum neuen Ordner.

Zielwahl-Regeln: Index-Seiten (`index.md`, Ordnerübersichten) bekommen `kind: index`, nie ein Thema aus dem Inhalt. Personen, Creator und Autoren sind kein Thema. Trading nur für Anlage/Aktien — Auswanderung, Nebengewerbe, Grundstück gehören nie dorthin. Systemdateien und Infrastruktur (SPEC, README, Fleet-Referenz) nicht nach Thema einsortieren. Bei mehr als einem Drittel `sonstiges` ist die Regel zu grob, nicht die Datei zu schwer.

## W3 — Dateien umsortieren und Ordner umbenennen (ingest-sicher)

Gilt, wenn ein Pipeline-Scanner den Ordner liest. Reihenfolge: Backup → Projektcheck → Keyword-Regex mit `\b` → Entscheidungsliste → Move per `shutil.move` (Zielordner vorher `mkdir -p`) → Manifest → Link-Umbiegen (W4) → DB-Remap (W5) → Verifikation.

- **Zielordner vor dem Mapping prüfen** (`os.path.isdir`): `boerse/` vs. `Börse/`, Tippfehler. Zieldatei existiert? Nicht raten, melden.
- **Dateinamen mit Sonderzeichen** (Emoji, Unicode-Striche) über Python-Pfade verarbeiten, nie über Shell-Strings.
- **Verschieben und Verlinken nie als getrennte Schritte** laufen lassen — sonst zeigt jede Wiki-Seite ins Leere.
- **Ordner-Umbenennung = Move jeder enthaltenen Datei** plus jedes Verweises, auch Pfadteile in Frontmatter (`source:`) und Wikilinks mit Ordnernamen. Vorher zählen, nachher denselben Zähler gegen Null prüfen; Dateizahl im Ordner vor/nach als Gegenprobe. Ein Projektordner wird nicht aufgelöst.
- **Verifikation:** Scanner read-only laufen lassen; erwartet wird „nur noch nicht verarbeitete Dateien“. Zählung: verbleibend = vorher − verschoben.
- **Sync-Hinweis:** Bei GDrive-Bisync spiegelt sich der Move dorthin; andere Geräte zeigen bis zum nächsten Sync den alten Stand.
- **Batch-Fehler ≠ Move-Fehler:** erst `find -name` prüfen, wo die Datei wirklich liegt, dann fortsetzen — sonst Doppel-Moves oder verlorene Verweise.
- **In den falschen Themenordner zu verschieben ist teurer als Nachfragen.** Themen mit Projekt- oder Zukunftsbezug vorher gegen die Ordnerregeln prüfen.
- **Systemdateien** (index, Templates, Root-Notizen) nur verschieben, nie löschen; Löschen nur auf explizite Freigabe.

## W4 — Link-Umbiegen

Formeln und Sonderfälle: `references/link-rewriting.md`. Kernregeln:

- **Relativ neu berechnen, nicht Basename ersetzen.** `str.replace(alter_name, neuer_name)` lässt die Pfadtiefe stehen und erzeugt `../../Clippings/../../Tech/…`. `os.path.relpath(neuer_vault_pfad, os.path.dirname(wiki_datei))` berechnen und den ganzen Link-Ausdruck ersetzen.
- **Vorher alle Verweise auf das alte Ziel sammeln** — `grep -rl` nach dem Basename über den GANZEN Vault, nicht nur Wiki, sonst bleiben Links aus `Projekte/` oder `Clippings/` stehen.
- **Alias (`|Text`) und Anker (`#…`) erhalten.** Wikilinks ohne `.md`, Markdown-Links mit `.md` — `[[pfad.md]]` löst Obsidian nicht auf. `]]` nicht verschlucken.
- **Vor dem Schreiben auflösen:** den neu berechneten Link aus der Quelldatei heraus prüfen (`normpath(join(dirname, link))`, Datei oder `.md` muss existieren). Nur schreiben, wenn er auflöst; sonst Zeile unverändert lassen und melden.
- **Pro Datei sichern, defekte Muster vor/nach zählen** (`../../X/../../`, `.md.md`). Steigt die Zahl: sofort aus der Sicherung zurücksetzen, nicht weiterreparieren.
- **Mehrfachverweise zusammenfassen:** derselbe kaputte Name steht oft in 5–30 Wiki-Seiten. Eine Entscheidung pro Ziel, dann auf alle Vorkommen anwenden.
- **Kaputten Wikilink entfernen heißt Linktext als Klartext behalten** — nie die ganze Zeile löschen.
- **Duplikate nur nach Inhaltsvergleich löschen** (`cmp` oder Frontmatter), Sicherung in den Scratch-Ordner. Gleicher Titel heißt nicht gleicher Inhalt.
- Regex-Läufe können Dateien mit ungeschlossenen Wikilinks (`[[Name` ohne `]]`) verstümmeln: nach jedem Batch gültiges Frontmatter prüfen (genau ein Block zwischen `---`-Zeilen), nicht nur Wikilinks zählen.

## W5 — Ingest-Scanner-DB pflegen

Der Scanner dedupliziert über **relativen Pfad + vollen sha256**. Ein Eintrag zählt nur, wenn beides stimmt. DB-Format: dict `{relpath: hash}` oder list `[{path, sha256}]`.

- **Remap bei Verschiebung:** Keys `alt → neu` umbenennen, Werte unverändert lassen. Ohne Remap werden alle verschobenen Dateien erneut Kandidaten — doppelte LLM-Kosten, doppelte Wiki-Einträge. Die Zahl der remappten Einträge prüfen.
- **Hash-Reset nur für inhaltlich gleiche Dateien.** Eine mtime-Änderung durch Sync ist kein Grund; vorher gegen Backup oder Remote-Original diffen. Eine plötzlich große Kandidatenzahl heißt Pfad- oder Hash-Mismatch.
- **Artefakte ausschließen:** `index.md` in Clippings ist ein Wiki-Index, keine Quelle — per Namensfilter überspringen. Der Filter muss vor dem Hash-Vergleich greifen.
- **Vor dem Überschreiben** einer Datei prüfen, ob ein Cron sie aktiv beschreibt: Zielpfad im Cron-Prompt suchen, `enabled` und `last_run_at` in `jobs.json` lesen. Memory-Notizen zum Cron-Status sind nicht verlässlich.
- **Ersetzen durch Entwurf** nur, wenn der Entwurf eine Obermenge des Originals ist — Block für Block vergleichen (z. B. Lektionen).
- **Ingest-Kopien erkennen:** unterscheidet sich eine Clippings-Datei vom Vault-Original nur im Frontmatter (`origin`), ist sie eine Ingest-Kopie und kann weg. Hat sie zusätzliche Inhaltszeilen, gehört sie per Merge ins Original, nicht gelöscht.
- Diagnose und Reset-Prozedur: `references/scanner-hash-reset.md`.

## Frontmatter-Schema und Themen-Zuordnung

Pflichtfelder jeder Markdown-Datei (außer `claude/index.md`, `claude/log.md`): `kind` (source | concept | entity | recipe | note | index), `origin` (hermes | claude | clipping | manuell), `topic`. Das Feld `type` ist abgeschafft und wird nicht wieder eingeführt, auch nicht in Templates. Ordnerregel schlägt Inhalt; `topic: sonstiges` ist der sichere Default. Nicht-Markdown-Dateien tragen kein Frontmatter.

**Schema-Migration** (Feld entfernen oder umbenennen) — Reihenfolge zwingend:
1. **Schreiber zuerst umstellen:** Ingest-Scripte (`.hermes/scripts/*.py`), Cron-Prompts (`prompt` in `cron/jobs.json`) und Skill-Templates in allen Profilen. Jede geänderte Konfig vorher sichern.
2. **Gate:** null Schreib-Vorgaben für das alte Feld. Nach Frontmatter-Kontext greppen (`^type:`, Template-Zeilen), nicht breit — JSON-Schemas und API-Dokus treffen sonst falsch.
3. **Erst dann** das Feld aus den Dateien entfernen, Sicherung pro Datei. Ohne Schritt 2 schreibt der nächste Ingest das alte Schema wieder hinein.

Entscheidungstabelle, Ordner→`topic`-Mapping und Migrationsmapping alt→neu: `references/frontmatter-and-topics.md`.

## Referenzen

- `references/frontmatter-and-topics.md` — Themen-Entscheidungstabelle, Ordner→`topic`, Pflichtfelder, Migration `type` → `kind`/`origin`
- `references/link-rewriting.md` — Link-Umbiegen im Detail (Formeln, Alias/Anker, Mehrfachverweise, Sicherung)
- `references/scanner-hash-reset.md` — Scanner-Hash-Mismatch-Diagnose und Reset-Prozedur

## Verwandte Skills

- `obsidian` — Vault-Basics, Wikilinks, Health-Check, LLM-Wiki-Pattern
