---
name: find-and-fix-all
description: Bei jedem Bugfix das zugrundeliegende Muster identifizieren, projektweit scannen, Befund zeigen, Bestätigung einholen, dann alle Stellen fixen.
---

# Find & Fix All — Bugfix-Protokoll

## Wann
Immer wenn ein Bug/Error/Fix ansteht — insbesondere bei:
- Tracebacks mit Config-Pfaden, Konstanten, Environment-Variablen
- Import-Fehlern, Pfad-Fehlern, Namenskonventionen
- Duplicated-Code-Bugs (Copy-Paste-Fehler)
- Refactoring wo Dinge umbenannt/verschoben wurden

## Protokoll (zwingend)

### Schritt 1: Muster extrahieren
Nachdem der konkrete Fehler identifiziert ist, frage:
- *Ist das ein Einzelfehler oder ein Muster?*
- *Wurde das gleiche woanders copy-pasted?*
- *Liegt ein systemic Problem vor (Namenskonvention, falsche Imports, doppelte Präfixe)?*

### Schritt 2: Projektweiten Scan
Scanne das gesamte relevante Projektverzeichnis mit `search_files` oder `grep`:
- Suche nach dem identischen Pattern (z.B. `STRATEGY_STRATEGY_`, `BACKTEST_BACKTEST_`)
- Suche nach verwandten Mustern (gleiche Fehlerklasse, andere Dateien)
- Dokumentiere Fundstellen: Datei:Zeile + Kontext

### Schritt 3: Befund präsentieren
Dem User zeigen:
- Wie viele weitere Stellen gefunden
- Wo genau (Datei:Zeile)
- Optional: ob es safe ist alle auf einmal zu fixen

### Schritt 4: Bestätigung einholen
Fragen: "Soll ich alle X Stellen fixen?"
Nicht einfach durchballern — der User will Kontrolle.

### Schritt 5: Alle fixen
Nach OK:
- Alle Fundstellen mit `patch` fixen
- Pro Stelle einzeln patchen (nachvollziehbar)
- Abschlussmeldung mit Diff-Übersicht

### Schritt 6: (optional) Skill anlegen
Wenn das Pattern besonders knifflig oder wiederkehrend ist:
- "Soll ich das als Skill speichern?"