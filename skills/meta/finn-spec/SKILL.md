---
name: finn-spec
description: "Finn-loop Spec — Interviewt Martin zu einer Idee, bis die Task-Spezifikation eindeutig ist, und schreibt sie als Issue in den Vault. Interaktiv — nie unbeaufsichtigt ausführen."
---

# Finn-loop Spec Interview

Wandelt eine rohe Idee in eine Task-Spezifikation um, die ein Build-Agent nur aus der Spec heraus umsetzen kann. Du bist der Codebase-Brain, Martin ist der Product-Brain. Rate nie Product-Entscheidungen.

## 1. Vor dem Fragen: Codebase lesen

Lies den relevanten Code zuerst. Finde welche Dateien betroffen sind, welche Patterns existieren, welche Constraints gelten. Frage nie etwas, das die Codebase beantworten kann.

## 2. Interview in Runden

1-4 Fragen pro Runde, immer mit konkreten Optionen und deiner Empfehlung zuerst. Nur echte Product-Entscheidungen fragen:

- **Behavior-Forks**: Wer sieht es, was passiert genau, wo lebt es?
- **Scope-Grenzen**: Was ist explizit NICHT Teil dieses Tasks?
- **Edge Cases**: Leere Zustände, Fehlerbehandlung, Limits
- **Daten-Implikationen**: Migrationen, bestehende Records

Nach jeder Runde: **Confidence-Test** — "Könnten zwei verschiedene Entwickler diese Spec lesen und das gleiche Verhalten liefern?" Wenn nein, weitere Runde. Kein Cap.

## 3. Issue draften

Format:
```markdown
## Problem
Was für ein Problem löst das? 1-2 Sätze.

## Acceptance Criteria
- [ ] AC-1 — Beobachtbares, testbares Ergebnis
- [ ] AC-2 — ...

## Non-goals
- NG-1 — Was darf NICHT geändert werden
- NG-2 — Was ist explizit ausgeschlossen

## Relevante Dateien
- path/to/file — warum es wichtig ist

## Test-Erwartungen
- Was muss getestet werden

## Wie zu verifizieren
1. Nummerierte manuelle Schritte
```

Regeln:
- Jedes AC hat stabile `AC-N` ID, jedes NG hat `NG-N` ID
- Kein AC darf ein NG benötigen
- Größe: max 1 Tag Arbeit. Größeres → Issue-Chain

## 4. Bestätigen + Speichern

Zeige den Draft, lass Martin bestätigen. Dann:
- Speichere als `/root/obsidian-vault/wiki/tasks/<kurzname>.md`
- Füge einen Eintrag in `/root/obsidian-vault/wiki/tasks/README.md` (Task-Queue)
- Füge Frontmatter: `status: spec-done`, `agent-ready: false`, `created`, `tags`

## Hard Rule

Setze `agent-ready` NIEMALS auf `true`. Das macht Martin nach finalem Lesen — das ist das Approval-Gate zwischen "Idee" und "Agent baut es".