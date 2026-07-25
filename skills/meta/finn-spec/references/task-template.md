# Task-Spec Template

Standard-Vorlage für Finn-loop Specs. In `finn-spec` Schritt 3 verwenden.

```markdown
## Problem
Was für ein Problem löst das? 1-2 Sätze.

## Acceptance Criteria
- [ ] AC-1 — Beobachtbares, testbares Ergebnis
- [ ] AC-2 — ...
- [ ] AC-N — ...

## Non-goals
- NG-1 — Was darf NICHT geändert werden
- NG-2 — Was ist explizit ausgeschlossen
- NG-N — ...

## Relevante Dateien
- path/to/file — warum es wichtig ist

## Test-Erwartungen
- Was muss getestet werden, manuell oder automatisch

## Wie zu verifizieren
1. Nummerierte manuelle Schritte die jeder befolgen kann
2. Jeden Schritt mit erwartetem Output
3. Deckt alle ACs ab
```

## Regeln für gute Specs

- **Jedes AC hat stabile `AC-N` ID** — der Build und Review nutzen diese IDs als Contract
- **Jedes NG hat stabile `NG-N` ID** — Non-goals sind bindend
- **Kein AC darf ein NG benötigen** — wenn doch, vor dem Filing mit Martin klären
- **Größe: max 1 Tag Arbeit** — Größeres wird eine Issue-Chain: kleine, baubare Issues
- **Issue-Chain ordnen** — so dass jedes Issue nur auf gemergten Code der vorherigen aufbaut

## Confidence-Test

Nach jeder Interview-Runde: 
> Könnten zwei verschiedene Entwickler diese Spec lesen und das gleiche Observable Behavior liefern?

Wenn nein → weitere Runde. Kein Cap.