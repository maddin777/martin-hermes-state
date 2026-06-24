---
name: task-loop
description: >-
  Meta-Arbeitsweise für komplexe Tasks (>3 Tool-Calls): definiere ein Done-Kriterium,
  iteriere mit einem Fix pro Runde, verifiziere am Output. Nach 3 Iterationen
  ohne Durchbruch -> Eskalation an Martin.
---

# Task-Loop

## Wann aktivieren

**AUTOMATISCH** bei:
- Task mit >3 Tool-Calls (erwarte Komplexität)
- Reparatur/Fehlerbehebung (zweiter Versuch nötig)
- Martin sagt "hat nicht geklappt" / "funktioniert nicht"

**NICHT nötig** bei:
- Einfachen Lese-/Schreib-Tasks (1-2 Calls)
- Klaren "mach X"-Anweisungen ohne Iterationserwartung

## Ablauf

### Phase 1: Task annehmen + Done-Kriterium

Bevor ich irgendeinen Fix mache:

```
──────────────────────────────────────
Task: <Kurzbeschreibung>
Done-Kriterium: <Woran messe ich dass es fertig ist?>
  - Gate 1: <Erster Check, z.B. "Prozess läuft">
  - Gate 2: <Zweiter Check, z.B. "Log zeigt Erfolg">
  - Gate 3 (echter Done-Check): <Output/Ergebnis im Zielsystem>
──────────────────────────────────────
```

Faustregel: **Das Done-Kriterium muss das Problem aus Martins Perspektive lösen**, nicht nur einen Zwischenschritt. Wenn die News nicht im Kanal ankommen, ist "Job scheduled" kein Done. "Nachricht im Chat" ist Done.

### Phase 2: Hypothese + Fix (ein Schritt pro Runde)

- **Hypothese** formulieren: "Ich glaube das Problem ist X, weil ich Y gesehen habe"
- **EINEN Fix** pro Iteration — nie zwei Änderungen gleichzeitig machen
- Fix protokollieren in der Konversation (muss für Martin nachvollziehbar sein)

### Phase 3: Verification Gate(s) durchlaufen

Jedes Gate nacheinander prüfen:

```
Gate 1: <systemctl status / grep Log / curl Endpunkt>
  → ✅/❌
Gate 2: <SELECT aus DB / Datei existiert / Output sichtbar>
  → ✅/❌  
Gate 3 (echter Done): <Ist das Problem aus Martins Sicht gelöst?>
  → ✅/❌
```

### Phase 4: Entscheiden

| Ergebnis | Nächster Schritt |
|----------|------------------|
| **Alle Gates grün** ✅ | Skill patchen (wenn neues Wissen), Memory updaten, fertig |
| **Gate(s) rot** ❌ | Neue Hypothese → zurück zu Phase 2 |
| **3 Iterationen ohne allen Gates grün** | **Eskalation an Martin**: was probiert, welche Gates fehlschlugen, was ich brauche |

## Eskalations-Format

Nach 3 Iterationen kein Durchbruch:

```
═══ ESKALATION ═══
Task: <Name>
Versuche:
  1. <Hypothese> → <Gate-Ergebnis>
  2. <Hypothese> → <Gate-Ergebnis>
  3. <Hypothese> → <Gate-Ergebnis>
  
Offene Fragen / Was ich brauche:
  - <kann ich nicht prüfen weil ich kein API-Key/Channel-Zugriff habe>
  - <Vermutung, die ich nur mit dir verifizieren kann>
═══
```

## Beispiel-Applizierung (Newsbriefing-Post-Mortem)

```
──────────────────────────────────────
Task: Newsbriefing (daily-news-briefing) kommt nicht im News-Kanal an
Done-Kriterium: Nachricht erscheint um 06:00 im @hermster_news_bot Kanal
  Gate 1: Gateway hermes-news läuft (systemctl)
  Gate 2: Cron-Job hat gültiges next_run_at
  Gate 3: Probelauf → Nachricht im Kanal sichtbar
──────────────────────────────────────

Iteration 1:
  Hypothese: Gateway ist tot (seit 20.06. inactive)
  Fix: systemctl start hermes-gateway-hermes-news
  Gate 1: ✅ active (running)
  Gate 2: ✅ next_run_at morgen 06:00
  Gate 3: ❌ nicht getestet (hätte einen manuellen Probelauf triggern müssen)

Iteration 2:
  Neue Hypothese: Gate 3 nicht geprüft → Bot fehlt im Channel
  → Eskalation an Martin: "Bitte @myhermster_bot in den News-Channel einladen"
  
Nach Eskalation: Martin startet Gateway → alle Gates grün ✅
──────────────────────────────────────
```

## Verifikations-Muster nach Task-Typ

| Task-Typ | Verifikation |
|----------|-------------|
| **Delivery-Cron** | Probelauf triggern → Ziel-Channel checken |
| **Pipeline-Reparatur** | Nächsten geplanten Lauf abwarten ODER manuell ausführen + Log prüfen |
| **Code-Änderung** | Syntax-Check + Testlauf + Vergleich alter/neuer Output |
| **DB-Änderung** | SELECT nach Änderung + angrenzende SELECTs ob nichts kaputt |
| **Konfig-Änderung** | Restart + Healthcheck + Funktionsprüfung |
| **Gateway-Problem** | systemctl status + Bot antwortet auf /start + Nachricht senden |

## Wichtige Grundsätze

1. **Niemals zwei Änderungen gleichzeitig.** Sonst weißt du nicht was gewirkt hat.
2. **Niemals "wird schon klappen"** — jedes Gate muss aktiv geprüft werden.
3. **Niemals dasselbe nochmal probieren.** Wenn Hypothese nicht hielt, neue aufstellen.
4. **Bevor du was erklärst: mach.** Code-Änderung → ausführen. Gateway-Problem → prüfen. Nicht "ich würde vorschlagen".
5. **Skill patchen nach erfolgreichem Fix.** Wenn das Wissen nicht in einem Skill landet, passiert der Fehler wieder.