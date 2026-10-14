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

## Stolperfallen

- Zielordner mit `mkdir -p` anlegen, bevor `shutil.move` läuft, sonst bricht der Batch mittendrin ab.
- Dateinamen mit Sonderzeichen (Emoji, Unicode-Striche) über Python-Pfade verarbeiten, nie über Shell-Strings.
