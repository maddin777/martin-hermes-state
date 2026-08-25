---
name: finn-review
description: "Finn-loop Review — Delegiert den Review an den REVIEWER-Bot (eigenes Profil, Option 2) gegen die Spec, postet das Verdict und setzt Status-Labels. Nie merge oder push."
---

# Finn-loop Reviewer (Option 2 — REVIEWER-Bot via CLI)

Ein Durchlauf = ein Task reviewed. Reviewt NUR gegen die Task-Spec.

## Architektur (Option 2)

Der Orchestrator (dieses default-Profil) **delegiert den Review** an den
eigenständigen REVIEWER-Bot (`hermes -p reviewer`). Der reviewer-Bot läuft in
seinem eigenen Profil (eigene Skills, Memories, SOUL), reviewed die
Task-Spec + Build-Zusammenfassung gegen die ACs/NGs, postet ein 3-stufiges
Verdict und setzt das Status-Label.

**Wrapper nutzen, nie selbst reviewen:**
```bash
/root/.hermes/scripts/finn_review.sh <taskfile>
```

Der Wrapper:
1. Startet `hermes -p reviewer -z "<Prompt>"` (headless, eigenes Profil)
2. Der reviewer-Bot prüft die Implementierung gegen jede AC/NG, postet das
   Verdict in stdout, setzt `status:`-Label (review-approved /
   review-changes-requested / needs-human-review)
3. Gibt das Verdict zurück

**Du reviewst NICHT mehr selbst.** Deine Rolle als Orchestrator:
Task finden → Wrapper aufrufen → Verdict/Status prüfen → Martin berichten.

## 1. Finde einen Task zum Reviewen

Lese `/root/obsidian-vault/wiki/tasks/README.md`. Finde Tasks mit `status: needs-review`.

Wenn nichts reviewed werden muss: melde "Keine Tasks im Review-Queue" und Ende.

## 2. Delegieren (statt selbst reviewen)

Rufe den Wrapper auf:
```bash
/root/.hermes/scripts/finn_review.sh /root/obsidian-vault/wiki/tasks/<task>.md
```

Der Wrapper-Prompt enthält bereits: Treue zur Spec, AC/NG-Bewertung,
Must-Fix-Prefixes ([AC-N]/[DEFECT]/[SECURITY]), Scope-Conflict-Erkennung,
Verdict-Format, Status-Label-Setzung, Hard-Limits (nie merge/push/implementieren).

## 3. Orchestrator-seitige Prüfung

Nach dem Wrapper-Lauf:
- Lies das Reviewer-Verdict aus stdout
- Prüfe das gesetzte `status:`-Label im Task-File
- Wenn Scope-Conflict → `needs-human-review` → Martin muss entscheiden

## 4. Berichten

Gib Martin das Reviewer-Verdict gekürzt weiter:
- Summary
- Must-fix / Should-fix Findings (oder "None")
- Safe to merge: Yes/No
- Setzes Status-Label als Hinweis

**Nie mergen, nie pushen, nie selbst implementieren.** review-approved ist
Evidenz für Martin, nicht Merge-Autorisierung.

## 5. Review-Feedback

Wenn der Reviewer `review-changes-requested` gesetzt hat: das ist der Trigger
für den nächsten finn-build-Durchlauf (der den Fix an den coder-Bot delegiert).
