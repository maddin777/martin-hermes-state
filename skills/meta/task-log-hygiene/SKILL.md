---
name: task-log-hygiene
description: Use after tasks to route work-logs into skills, not memory.
version: 1.0.0
author: Hermes Agent
license: MIT
category: meta
metadata:
  hermes:
    tags: [meta, memory, task-log, hygiene]
    related_skills: [task-loop, session-librarian]
---

# Task-Log-Hygiene

## When to Use
Wird **nach jedem abgeschlossenen Task (>3 Tool-Calls)** als Checkpoint ausgeführt
(bei größeren Umbauten am Ende, bei langen Sessions wenn ein Teil-Ziel erreicht ist).
Auch wenn der Memory-Store über ~90% läuft oder ein Memory-Add am Limit scheitert.

Ziel: Dauerhaftes Wissen (Memory/Skills) hoch-signal halten. Task-Logs gehören
NICHT ins Memory — das Memory-Tool lehnt sie ab und sie verstopfen den Store.

## Entscheidungslogik — selektiv, nicht "immer"

Für jedes Ergebnis, das im Task entstanden ist, eine von drei Routen wählen:

| Route | Wann | Wohin |
|-------|------|-------|
| **A: Skill-Patch** | Das Ergebnis ist eine **wiederverwendbare Prozedur**, ein Learn/Workflow/Pitfall, den ein künftiger Task wahrscheinlich braucht (Fix, Workaround, Command-Folge, API-Quirk) | `skill_manage(action='patch')` in den betroffenen Skill ODER `references/<date>-<topic>.md` |
| **B: Session-Historie** | Das Ergebnis ist ein **Einmal-Ergebnis** ("hab X gefixt am 26.08.", PR-Nummer, Backup-Pfad, Task-Erledigung) | NICHTS speichern — `session_search` findet es später. Kein Memory, kein Skill. |
| **C: Memory (nur Ausnahmen)** | **Dauer-Fakt** ohne Ablaufdatum: User-Präferenz, Korrektur, Environment-Fakt, stabile Convention | `memory` Tool — NUR in diesen Fällen |

## Filter für Route A (Skill) — muss ALLES erfüllen:
- Wiederverwendbar: Ein künftiger Task könnte es tatsächlich brauchen (nicht hypothetisch)
- Nicht in 7 Tagen stale (kein "Datei X erstellt am Datum")
- Kein reines Task-Progress ("Phase 3 done")

## Filter für Route C (Memory) — muss ALLES erfüllen:
- Kein Ablaufdatum (gilt in 3+ Monaten noch)
- Dauer-Fakt, keine Anweisung ("User bevorzugt X" statt "immer X tun")
- Nicht bereits abgedeckt (kein Duplikat zum vorhandenen Store)

## WICHTIG — nicht in Skills packen (Anti-Muster):
- Einmalige Fixes mit Datum (Route B) — Skill wird stale (65/91 sind es heute schon)
- Task-Progress-Logs ("erledigt, nächster Schritt")
- Spekulative Prozeduren ohne Kontext, in denen sie je gebraucht würden

## Output-Checkpoint
Nach der Entscheidung:
1. Soll etwas in Route A → Skill-Patch oder reference-File anlegen (nicht nur planen)
2. Route C-Einträge → Memory-Batch (konsolidieren, damit Store <Limit bleibt)
3. Wenn Memory über ~90% → **prompt entfernen/verkuerzen** statt mehr Platz zu fordern

## Warum selektiv
Vollständig automatisches "alles in Skills" erzeugt Skill-Bloat (heute 65 stale von 91).
Nur wiederverwendbare Prozeduren in Skills + Einmal-Ergebnisse in Session-Historie
+ Dauer-Fakten in Memory hält alle drei Stores gesund.
