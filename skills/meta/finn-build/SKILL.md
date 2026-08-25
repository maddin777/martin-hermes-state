---
name: finn-build
description: "Finn-loop Build — Claimt den nächsten agent-ready Task aus dem Vault, delegated die Implementierung an den CODER-Bot (eigenes Profil, Option 2) und meldet Ergebnis. Ein Durchlauf = ein Task."
---

# Finn-loop Builder (Option 2 — CODER-Bot via CLI)

Ein Durchlauf = ein Task: Implementiere einen Task aus der Queue, oder fixe Review-Feedback zu einem existierenden Task.

## Architektur (Option 2)

Der Orchestrator (dieses default-Profil) **delegiert die Implementierung** an den
eigenständigen CODER-Bot (`hermes -p coder`). Der coder-Bot läuft in seinem
eigenen Profil (eigene Skills, Memories, SOUL), liest die Task-Datei als
Vertrag, implementiert die ACs, verifiziert sie und setzt das Status-Label.

**Wrapper nutzen, nie selbst implementieren:**
```bash
/root/.hermes/scripts/finn_build.sh <taskfile> [workdir]
```

Der Wrapper:
1. Startet `hermes -p coder -z "<Prompt>"` (headless, eigenes Profil)
2. Der coder-Bot implementiert + verifiziert + schreibt Build-Zusammenfassung
   ans Task-File-Ende + setzt `status: needs-review`
3. Gibt das Bot-Output zurück für Debug/History

**Du implementierst NICHT mehr selbst.** Deine Rolle als Orchestrator:
Task picken → Wrapper aufrufen → Ergebnis prüfen → Martin berichten.

## 0. Preflight

- Prüfe ob das Arbeitsverzeichnis sauber ist (git status oder Dateisystem)
- Lade die Task-Queue: `/root/obsidian-vault/wiki/tasks/README.md`
- Stelle sicher das coder-Profil existiert: `hermes -p coder status` (nicht "run")

## 1. Review-Feedback zuerst

Suche nach Tasks mit `status: review-changes-requested`. Wenn vorhanden, nimm
den ältesten, lies die Spec + Review-Kommentare, und **delegiere den Fix an den
CODER-Bot** mit `finn_build.sh` (der Prompt wird um die Review-Must-Fix-Punkte
angereichert — übergib sie als goal-Kontext im `.sh`-Aufruf). Danach: Ende des Durchlaufs.

Wenn ein Fix ein NG verletzen würde oder eine Product-Entscheidung braucht:
nicht implementieren. Task auf `status: needs-human-review` setzen mit
Kommentar warum, Ende des Durchlaufs.

## 2. Task picken

Lese `/root/obsidian-vault/wiki/tasks/README.md`. Finde Tasks mit:
- `agent-ready: true`
- `status: spec-done`
- nicht `blocked: true`

Wenn Queue leer: melde "Keine Tasks in der Queue" und Ende.

## 3. Claimen

Setze `status: in-progress` und `assigned: coder` im Frontmatter des Task-Files. Speichere.

## 4. Delegieren (statt selbst bauen)

Rufe den Wrapper auf:
```bash
/root/.hermes/scripts/finn_build.sh /root/obsidian-vault/wiki/tasks/<task>.md
```

Der Wrapper-Prompt enthält bereits: Task-Datei als Vertrag, ACs/NGs binder,
Verifikations-Pflicht, Scope-Ledger, `status: needs-review`-Setzung.

**Optional ergänzen** (für komplexe Tasks oder wenn du Kontext beisteuern
willst): füge im Wrapper einen zusätzlichen Kontext-Parameter hinzu ODER
schreibe den Kontext voran in die Task-Datei. Am saubersten: die nötigen
Hintergrund-Infos in die Task-Datei ("Relevante Dateien" + Kontext) — der
coder-Bot liest sie dort.

## 5. Verifizieren (Orchestrator-seitig)

Nach dem Wrapper-Lauf:
- Prüfe exit-Code des Wrappers
- Prüfe dass `status: needs-review` im Task-File steht
- Lies die `## Build-Zusammenfassung`-Sektion — hat der Bot für jede AC einen
  Nachweis und Verifikations-Ergebnisse?

Wenn das Fehlt oder der Bot "nicht erfüllt" meldete, ohne eine
Product-Entscheidung zu brauchen → Wrapper erneut (max 3 Iterationen) oder
Review anfragen. Wenn eine AC ein NG bräuchte → Schritt 8.

## 6. Melden

Der coder-Bot hat `status: needs-review` und `agent-ready: false` gesetzt.
Du berichtest Martin kompakt:
- Was der coder gebaut hat (aus der Build-Zusammenfassung)
- Ob für jede AC ein Nachweis existiert
- "Kann reviewed werden: [Task-Link]"

**Nie** selbst mergen oder als "done" markieren. Review ist ein separater
Schritt (finn-review → reviewer-Bot).

## 7. Review-Feedback über Reviewer

Wenn ein Review erneut `review-changes-requested` liefert, ist das der Trigger
für Schritt 1 im nächsten Durchlauf.

## 8. Blocked

Setze `status: blocked` und `blocked_reason: <konkrete Frage>`. Stelle eine
spezifische Frage die Martin asynchron beantworten kann. Nie "ist unklar" —
nenne die exakte Entscheidung, Optionen, und welches AC betroffen ist. Ende des Durchlaufs.
