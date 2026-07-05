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

### Phase 2: Context-Check + Hypothese

**Bevor** du einen Fix machst: prüfe ob die Umgebung/Regime/Config deinen Fix überhaupt unterstützt. Martins Standard-Frage: "Sollte nicht auch ein Check erfolgen ob wir in einem Seitwärts/Uptrend/Downtrend sind?" — generalisiert auf ALLE Tasks.

- **Context-Check**: Ist das System in einem Zustand, in dem mein Fix Sinn ergibt? (Regime? Config-Zustand? Abhängigkeiten?)
- **Hypothese** formulieren: "Ich glaube das Problem ist X, weil ich Y gesehen habe. Der Context (Regime/Config/Umgebung) unterstützt diesen Fix weil Z."
- **Bei mehrdeutigen Requests:** Wenn Martins Frage auf mehrere Projekte/Kontexte zutreffen könnte, kurz verifizieren bevor du lossprintest. Ein "Deepdive wozu?" spart 12 Nachrichten und Frustration.
- **"Aus meinen proaktiven Vorschlägen" — Trace-Pattern:** Wenn Martin sagt "Bau X aus deinen proaktiven Vorschlägen" und X ist nirgends zu finden → die Vorschläge kamen aus dem vault-insights Cron (02:45, Abschnitt C). `session_search(query="Proaktive Vorschläge", sort="newest", limit=1)` findet den Report. Der Report listet 3 Vorschläge mit konkreten nächsten Schritten — Punkt 1, 2, 3 entsprechen "Abschnitt C Punkt 1, 2, 3".
- **"Aktualisier die erklaerung.md" — Richtung prüfen:** Wenn die Wiki-Seite neuer ist als die Quelle, ist die Quelle veraltet und muss mit dem Wiki-Stand aktualisiert werden (nicht umgekehrt). Timestamps checken bevor du editierst.

### Phase 2b: Compact-Response-Regel (bei komplexen Ergebnissen)

Wenn das Ergebnis einer Task-Ausführung mehrere Punkte/Erkenntnisse umfasst:

- **Sammle alles in EINER Antwort**, nicht verteilt über mehrere Tool-Calls/Nachrichten.
- Nur aufteilen wenn Telegram-Zeichenlimit (3000) oder Tool-Constraint es erzwingt.
- Martin hat sich explizit über fragmentierte Antworten beschwert ("Warum hast die Erklärung jetzt 12 mal erzeugt?"). Eine lange, vollständige Nachricht ist besser als 12 kurze.

### Phase 3: Fix (ein Schritt pro Runde)

- **EINEN Fix** pro Iteration — nie zwei Änderungen gleichzeitig machen
- Fix protokollieren in der Konversation (muss für Martin nachvollziehbar sein)

### Phase 4: Verification Gate(s) durchlaufen

Jedes Gate nacheinander prüfen:

```
Gate 1: <systemctl status / grep Log / curl Endpunkt>
  → ✅/❌
Gate 2: <SELECT aus DB / Datei existiert / Output sichtbar>
  → ✅/❌  
Gate 3 (echter Done): <Ist das Problem aus Martins Sicht gelöst?>
  → ✅/❌
```

### Phase 5: Entscheiden

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

## Token-Warnung vor grossen Analysen

Vor Tasks die >100k Tokens kosten werden (delegate_task mit viel Kontext, x_search-Calls, umfassende DB-Analysen):

```
⚠️  Warnung: Dieser Task wird schätzungsweise <N>k Tokens kosten.
OpenRouter-Modelle (deepseek-v4-flash) haben grössere Limits als xAI-Modelle.
Weiter? [ja/nein]
```

Faustregel: delegate_task mit Context >2KB oder >5 Tool-Calls → vorher warnen.

## Wichtige Grundsätze

1. **Niemals zwei Änderungen gleichzeitig.** Sonst weißt du nicht was gewirkt hat.
2. **Niemals "wird schon klappen"** — jedes Gate muss aktiv geprüft werden.
3. **Niemals dasselbe nochmal probieren.** Wenn Hypothese nicht hielt, neue aufstellen.
4. **Architektur-Änderungen vorher vorschlagen, nicht einfach implementieren.** Bei Änderungen die mehrere Komponenten betreffen (Config-Format, Datenfluss, neue Module): kurz die Logik skizzieren + Martin entscheiden lassen. Nicht "ich baue das jetzt" bei System-Architektur.
5. **Bevor du was erklärst: mach.** Code-Änderung → ausführen. Gateway-Problem → prüfen. Nicht "ich würde vorschlagen".
6. **Skill patchen nach erfolgreichem Fix.** Wenn das Wissen nicht in einem Skill landet, passiert der Fehler wieder.