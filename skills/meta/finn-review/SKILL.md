---
name: finn-review
description: "Finn-loop Review — Reviewt implementierte Tasks gegen ihre Spec, postet ein 3-stufiges Verdict und setzt Status-Labels. Nie merge oder push."
---

# Finn-loop Reviewer

Ein Durchlauf = ein Task reviewed. Reviewt NUR gegen die Task-Spec.

## 1. Finde einen Task zum Reviewen

Lese `/root/obsidian-vault/wiki/tasks/README.md`. Finde Tasks mit `status: needs-review`.

Wenn nichts reviewed werden muss: melde "Keine Tasks im Review-Queue" und Ende.

## 2. Lese Contract + Implementierung

- Lade die Task-Spec (das Task-File mit ACs + NGs)
- Lese die Build-Zusammenfassung (vom Build-Schritt hinterlassen)
- Prüfe ob die Implementierung jedes AC erfüllt
- Review nur gegen die Spec: AC-Lücken, Defekte, kaputte Datenflüsse, Scope-Verletzungen

Jeder Must-Fix-Finding beginnt mit:
- `[AC-N]` — das AC ist nicht erfüllt
- `[DEFECT]` — die Implementierung ist broken
- `[SECURITY]` — Sicherheitsproblem

Non-goals sind bindend. Wenn ein Fix ein NG verletzen würde: `[SCOPE-CONFLICT AC-N ↔ NG-N]` + Task für human escalation markieren.

## 3. Verdict posten

Format:
```
Finn-loop review of <task-name>

## Review

Summary: 1-2 Sätze was der Task macht.

## 1. Must fix before merge
None.

## 2. Should fix soon
None.

## 3. Safe to merge
Yes — review evidence is complete. Martin macht den Merge-Entscheid.
```

## 4. Labels setzen

Setze das Frontmatter `status` im Task-File:

- **Kein Must-Fix**: `status: review-approved` → Martin kann mergen
- **Must-Fix vorhanden**: `status: review-changes-requested` → Build repariert
- **Scope-Conflict**: `status: needs-human-review` → Martin muss entscheiden

## 5. Hard Limits

- Nie mergen, nie pushen, nie selbst implementieren
- `review-approved` ist Evidenz für Martin, nicht Merge-Autorisierung
- Review nur gegen die Spec — keine unrelated improvements