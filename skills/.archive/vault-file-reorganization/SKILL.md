---
name: vault-file-reorganization
description: "Use when moving vault files an ingest scanner reads."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [vault, obsidian, reorganize, clippings, ingest, dedupe]
---

# Vault-Dateien umsortieren (ingest-sicher)

## When to Use

- Dateien aus einem Root-Ordner (z.B. `Clippings/`) in Themenordner verschoben werden sollen
- Ein Scanner oder Cron den Ordner ingestiert und Duplikate oder Neu-Erkennung droht
- Keyword-basierte Zuordnung ansteht (dann gelten Schritt 3 und 5)

Gilt, wenn Dateien in einem Vault-Ordner in Unterordner verschoben werden und ein Pipeline-Scanner diesen Ordner liest (z.B. Clippings-Ingest). Ein Move ist kein harmloser Umzug: der Scanner erkennt verschobene Dateien als neu.

## Reihenfolge

1. **Backup zuerst.** Vaults sind oft kein Git-Repo. `tar -czf <scratch>/<ordner>_backup_<ts>.tgz <ordner>` vor dem ersten Move.
2. **Projekte vor Themen prüfen.** Vor jeder Keyword-Klassifikation die Projektordner ansehen (`Projekte/*`). Eine Datei, die zu einem Projekt gehört (Software-Doku, Manuskript, Hardware-Build), geht dorthin, nicht nach Thema. Projektzugehörigkeit schlägt Stichwort.
3. **Keyword-Regex mit Wortgrenzen.** Teilstring-Matches sind falsch: `hof` trifft Hoffmann und Bischoff, `gold` trifft Goldie, `signal` trifft Segelelektronik-Titel wie „Signal K“. Jedes Pattern mit `\b` verankern.
4. **Finanz-/Trading-Inhalte nie allein per Keyword verschieben.** Nur nach Sichtprüfung der Titel zuordnen.
5. **Mehrdeutiges nicht verschieben.** Vor dem Move eine Liste mit Gruppen (eindeutig / Projekt / unklar) vorlegen und auf Zuordnung warten. Systemdateien (index, Templates, Root-Notizen) nur verschieben, nie löschen; Löschen nur auf explizite Freigabe.
6. **Manifest schreiben.** Jede Zeile `{old, new}` als JSON. Das ist der Rollback.
7. **Ingest-DB remappen (Pflicht).** Der Scanner dedupliziert über den relativen Pfad plus Hash. DB-Format: dict `{relpath: hash}` oder list `[{path, sha256}]`. Ohne Remap werden bereits ingestierte, verschobene Dateien beim nächsten Lauf erneut verarbeitet: doppelte LLM-Kosten und doppelte Wiki-Quellen. Keys mit dem Manifest umbenennen und die Zahl der remappten Einträge prüfen. Manifest VOR dem Remap schreiben, sonst fehlt nach einem Abbruch die Zuordnung.
8. **Nie existierende Ziele überschreiben.** Kollision: skippen und melden.
9. **Verifizieren.** Scanner read-only laufen lassen. Er darf nur noch noch nicht verarbeitete Dateien melden. Zählen: verbleibend = vorher − verschoben.
10. **Sync-Hinweis.** Liegt der Ordner in einem Bisync (GDrive), spiegelt sich der Move dorthin. Andere Geräte zeigen bis zum nächsten Sync den alten Stand.
11. **Eingehende Links in derselben Runde umbiegen.** Ein Move ohne Link-Update lässt jede Wiki-Seite, die auf die Datei zeigt, ins Leere laufen. Vorher alle Verweise auf das alte Ziel sammeln (`grep -rl` nach Basename über den GANZEN Vault, nicht nur Wiki, sonst bleiben Links aus `Projekte/` oder `Clippings/` stehen), dann im selben Batch auf den neuen Pfad setzen und prüfen, dass jeder neue Link auflöst. Verschieben und Verlinken nie als getrennte Schritte laufen lassen.
12. **Ordner-Umbenennung = Move aller Inhalte.** Beim Umbenennen eines Projektordners gilt dieselbe Regel für jede enthaltene Datei und jeden Verweis, auch Pfad-Teile in Frontmatter (`source:`) und Wikilinks mit Ordnernamen. Vorher zählen, wie viele Dateien auf den Ordnernamen verweisen, nachher denselben Zähler gegen Null prüfen. Gegenprüfung mit Dateisystem (Dateizahl Ordner vor/nach) ist Pflicht.

## Link-Umbiegen (Schritt 11 im Detail)

- **Relativ neu berechnen, nicht Basename ersetzen.** `str.replace(alter_name, neuer_name)` lässt die alten Pfadteile stehen und erzeugt `../../Clippings/../../Tech/…`. Stattdessen `os.path.relpath(neuer_vault_pfad, os.path.dirname(wiki_datei))` berechnen und den gesamten Link-Ausdruck ersetzen. Mechanismus: ein Replace auf den Namen ändert nur den Namen, nicht die Pfadtiefe, also stimmt die Relativbasis nicht mehr.
- **Alias und Anker erhalten.** Bei Wikilinks `[[ziel|alias]]` und `[[ziel#abschnitt]]` die Teile nach dem Ziel mitnehmen, sonst verschwindet der Anzeigetext.
- **Wikilinks ohne `.md`, Markdown-Links mit `.md`.** `[[pfad.md]]` wird in Obsidian nicht aufgelöst. Die Endung beim Wikilink strippen, Alias (`|Text`) und Anker (`#…`) erhalten, schließendes `]]` mitnehmen. Regex-Gruppen so bauen, dass `]]` nicht verschluckt wird.
- **Vor dem Schreiben prüfen.** Den neu berechneten Link aus der Quelldatei heraus auflösen (`normpath(join(dirname, link))`, Datei oder `.md` muss existieren). Nur schreiben, wenn er auflöst. Sonst Zeile unverändert lassen und melden.
- **Pro Datei sichern, Zählung vorher/nachher.** Vor dem Schreiben Kopie anlegen. Zahl der defekten Pfadmuster (`../../X/../../`, `.md.md`) vor und nach dem Lauf vergleichen. Steigt sie, sofort aus der Sicherung zurücksetzen, nicht weiter reparieren.
- **Mehrfachverweise zusammenfassen.** Derselbe kaputte Name steht oft in 5–30 Wiki-Seiten. Ein Entscheidungslauf pro Ziel, dann auf alle Vorkommen anwenden. Pro Einzelfall nachfragen ist unnötig, wenn die Entscheidung für das Ziel schon feststeht.
- **Zielordner vor dem Mapping prüfen.** Ordnernamen mit Umlaut vs. ASCII (`Börse/` vs. `boerse/`) und Tippfehler kommen vor. `os.path.isdir` für jedes Ziel, bevor ein Link darauf zeigt. Zieldatei existiert? Nicht raten, sondern melden.
- **Duplikate nur nach Inhaltsvergleich löschen.** Gleicher Titel heißt nicht gleicher Inhalt. Vor dem Löschen `cmp` oder Frontmatter-Vergleich, und Sicherung in den Scratch-Ordner.

## Frontmatter nach Move/Umsortierung

- Pflichtfelder: `kind` (source | concept | entity | recipe | note | index), `origin` (hermes | claude | clipping | manuell), `topic` (Themenschlüssel aus `references/topic-mapping.md`).
- Feld entfernen oder umbenennen ist eine Schema-Migration. Diese Reihenfolge einhalten:
  1. Schreiber zuerst umstellen: Ingest-Scripte (`.hermes/scripts/*.py`, Vault-`.hermes/*.py`), Cron-Prompts (Feld `prompt` in `cron/jobs.json`) und Skill-Templates (SKILL.md mit Frontmatter-Beispiel) in allen Profilen. Sicherung jeder geänderten Konfig vorher.
  2. Gate: null Schreib-Vorgaben für das alte Feld. Greppe nach Frontmatter-Kontext (`^type:`, Template-Zeilen). Breit gegreppt treffen JSON-Schemas und API-Dokus jedes `"type":`, das ist kein Befund.
  3. Erst dann das Feld aus den Dateien entfernen, mit Sicherung pro Datei.
  Ohne Schritt 2 schreibt der nächste Ingest das alte Schema wieder hinein.
- Dateien ohne Frontmatter: Ordnerregel zuerst. Nur in `wiki/` (kein verlässliches Ordnersignal) darf der Inhalt entscheiden, und auch dort nur bei mehreren klaren Treffern. Sonst `topic: sonstiges` setzen, nicht raten.
- Index-Seiten (`index.md`, Ordnerübersichten) bekommen `kind: index`, nie ein Thema aus dem Inhalt.

## Themen-Zuordnung (vor jedem Move prüfen)

Die Entscheidungstabelle steht in `references/topic-mapping.md`. Vor jedem Move dort die Themengrenzen nachschlagen.

Reihenfolge bei der Zuordnung ohne klare Ordnerregel (`topic` setzen):
1. Ordner-Vorrang: Ordner mit eindeutigem Thema gewinnt (Tabelle in `frontmatter-schema.md`). Längster Ordner-Präfix zuerst prüfen.
2. Stichwort-Score über Titel, Beschreibung und Textanfang (Wikilinks und Breadcrumbs vorher entfernen). Nur zuordnen, wenn Score ≥ 2 UND der Sieger einen klaren Vorsprung hat. Sonst `sonstiges`.
3. Gegenprobe per Stichprobe (10 Zufälle pro Gruppe) vor dem Schreiben. Ein Keyword wie "Server" oder "Modell" zieht Themen in `tech`, die dort nicht hingehören. Solche Begriffe aus der Liste nehmen oder mit Mehrwort-Phrasen ersetzen.
4. Personen, Creator und Autoren sind kein Thema. Sie bleiben `sonstiges`, außer der Inhalt ist eindeutig.
5. Systemdateien und Infrastruktur (z. B. Fleet-Referenz, SPEC, Index) nicht nach Thema einsortieren.

Die Gruppen-Zahl nach dem Lauf melden, nicht nur "erledigt". Bei mehr als einem Drittel `sonstiges` ist die Regel zu grob, nicht die Datei zu schwer.

- Entscheidungen, die der Nutzer treffen soll, als nummerierte md-Tabelle vorlegen. Rückfragen bündeln, nicht einzeln stellen.
- Sagt der Nutzer, er will die Liste nicht prüfen: Regel festlegen, anwenden, und Regel plus Zählung berichten.
- Rückfrage-Tools können leer zurückkommen. Dann die Frage als Klartext-Tabelle in den Chat schreiben, nicht den Batch darauf warten lassen.
- Nach klarer Freigabe direkt umsetzen, mit Backup und Gates.
- Frontmatter nach dem Move prüfen: `kind`, `origin`, `topic` gesetzt, `topic` passt zum neuen Ordner. 

- Trading/Börse-Ordner nur für Anlage- und Aktienbezug. Auswanderung, Plan-B, Nebengewerbe und Grundstück gehören nicht dorthin, auch wenn ein Keyword-Match das vorschlägt.
- Sync-Konflikt-Dateien (`*.conflict*`) sind nicht automatisch Duplikate. Oft ist die Konflikt-Version die neuere, strukturierte Fassung. Vor dem Löschen Frontmatter und Länge beider Versionen vergleichen, Original sichern, bei Inhalt auf beiden Seiten den User fragen.

## Stolperfallen

- Index-Seiten bekommen `kind: index`, nie ein Thema aus dem Inhalt. Ein Thema an eine Ordner-Übersicht zu hängen ist falsch, auch wenn das Keyword passt.
- Ein Schema-Feld, das in Ingest-Scripten, Cron-Prompts oder Skill-Templates noch geschrieben wird, bricht die Migration: der nächste Lauf schreibt es wieder rein. Vor dem Entfernen die Schreiber umstellen, dann prüfen, dass kein Schreiber mehr übrig ist.
- Ein Regex-Lauf über Frontmatter-Dateien mit ungeschlossenen Wikilinks (`[[Name` ohne `]]`) kann Zeilen verstümmeln. Nach jedem Batch alle Dateien auf gültiges Frontmatter prüfen (genau ein Block zwischen `---`-Zeilen), nicht nur die Wikilinks zählen.
- Entfernen eines kaputten Wikilinks: Linktext als Klartext stehen lassen, nicht die ganze Zeile löschen. Sonst verschwinden Sätze mit echtem Inhalt.

- Zielordner mit `mkdir -p` anlegen, bevor `shutil.move` läuft, sonst bricht der Batch mittendrin ab.
- Ein Batch-Fehler nach dem Move (z. B. beim Link-Schritt) ist kein Fehler des Moves. Erst prüfen, wo die Datei wirklich liegt (`find -name`), dann den Rest fortsetzen. Sonst entstehen Doppel-Moves oder verlorene Verweise.
- Ein Verschieben in den falschen Themenordner ist teurer als ein Nachfragen. Themen mit Zukunftsbezug oder Projektbezug vorher gegen die Ordnerregeln in obsidian prüfen.
- Dateinamen mit Sonderzeichen (Emoji, Unicode-Striche) über Python-Pfade verarbeiten, nie über Shell-Strings.
- Keyword-Klassifikation trifft Systemdateien (SPEC.md, README, Berichte mit Trefferwörtern). Systemdateien vorab per Name ausschließen. Inhalt nur bei mehreren klaren Treffern nutzen, sonst `sonstiges`.
- Wikilinks und Markdown-Links vor dem Lesen für die Klassifikation entfernen. Breadcrumb-Navigation (`[[Ordner]] → [[Datei]]`) am Dateianfang erzeugt sonst falsche Treffer.
- Zählungen nur über die Dateiart, die du änderst (Markdown). Nicht-Markdown-Dateien verfälschen die Zahlen und erzeugen Scheinlücken.
