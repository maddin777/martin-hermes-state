---
name: finn-build
description: "Finn-loop Build — Claimt den nächsten agent-ready Task aus dem Vault, implementiert ihn und meldet Ergebnis. Ein Durchlauf = ein Task."
---

# Finn-loop Builder

Ein Durchlauf = ein Task: Implementiere einen Task aus der Queue, oder fixe Review-Feedback zu einem existierenden Task.

## 0. Preflight

- Prüfe ob das Arbeitsverzeichnis sauber ist (git status oder Dateisystem)
- Lade die Task-Queue: `/root/obsidian-vault/wiki/tasks/README.md`

## 1. Review-Feedback zuerst

Suche nach Tasks mit `status: review-changes-requested`. Wenn vorhanden, nimm den ältesten, lies die Spec + Review-Kommentare, fixe nur die "Must fix"-Punkte, setze `status: review-fixed`. Danach: Ende des Durchlaufs.

Wenn ein Fix ein NG (Non-Goal) verletzen würde oder eine Product-Entscheidung braucht: nicht implementieren. Task auf `status: needs-human-review` setzen mit Kommentar warum, Ende des Durchlaufs.

## 2. Task picken

Lese `/root/obsidian-vault/wiki/tasks/README.md`. Finde Tasks mit:
- `agent-ready: true`
- `status: spec-done`
- nicht `blocked: true`

Wenn Queue leer: melde "Keine Tasks in der Queue" und Ende.

## 3. Claimen

Setze `status: in-progress` und `assigned: hermes` im Frontmatter des Task-Files. Speichere.

## 4. Lesen

Lese die vollständige Task-Spec. Implementiere NUR die Acceptance Criteria. Non-goals sind bindend. Keine unrelated changes.

Wenn ein AC mehrdeutig ist oder mit einem NG kollidiert → gehe zu Schritt 8 (Blocked).

## 5. Bauen

- Implementiere die ACs mit dem existierenden Code-Stil, Architektur, Naming
- Ändere nichts außerhalb des Task-Contracts

## 6. Verifizieren

- Führe relevante Tests/Lint/Typecheck aus
- Prüfe `git diff` (oder `diff` bei Datei-Änderungen) auf unrelated changes
- Wenn nicht alle ACs erfüllt → Schritt 5 wiederholen, max 3 Iterationen

## 7. Melden

Setze `status: needs-review` und `agent-ready: false` im Task-File. Erstelle eine Zusammenfassung:
- Was geändert wurde und warum
- Scope Ledger: ein Nachweis pro AC, ein Preservation-Nachweis pro NG
- Verifikations-Ergebnisse
- "Kann reviewed werden: [Link/Details]"

**Nie** selbst mergen oder als "done" markieren. Review ist ein separater Schritt.

## 8. Blocked

Setze `status: blocked` und `blocked_reason: <konkrete Frage>`. Stelle eine spezifische Frage die Martin asynchron beantworten kann. Nie "ist unklar" — nenne die exakte Entscheidung, Optionen, und welches AC betroffen ist. Ende des Durchlaufs.