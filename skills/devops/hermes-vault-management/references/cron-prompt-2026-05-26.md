# vault-insights-daily Cron Prompt — Stand 26.05.2026

**Cron:** `53f222b00811` | **Schedule:** `45 2 * * *` | **Deliver:** Telegram

```
Du hast Zugriff auf den Obsidian Vault unter /root/obsidian-vault/. Der nächtliche GDrive-Sync war vor ~30 Minuten abgeschlossen (Cron 02:00). 

Deine Aufgaben:

## A — Wiki pflegen (höchste Priorität)
Scanne ob es neue/geänderte Dateien im Vault gibt (seit letztem Sync mit `find /root/obsidian-vault/ -maxdepth 3 -type f -newer /tmp/vault-last-sync -name "*.md" -not -path "*/wiki/*" -not -path "*/.*"` nachdem du /tmp/vault-last-sync per touch aktualisiert hast).

**Proaktive Watchlist-Wartung:** Prüf ob `Trading/Watchlist.md` aktualisiert wurde. Wenn ja:
- Aktualisiere `wiki/entities/Watchlist.md` mit neuen Metriken (Anzahl Einträge, Paper-Positionen, Quellenverteilung, Data Quality Issues)
- Tracke ob die Exit-Management-Quelldatei `Projekte/Hermes_Trading_Skill_Erklaerung.md` neuer ist als `wiki/concepts/Exit Management.md`. Wenn ja, aktualisiere die Exit Management Seite mit dem aktuellen Stand.

**Sonstige neue/geänderte Dateien:** Kaufe neue Konzepte, Entitäten oder Quellen als Wiki-Seiten ein:
- Trading-relevante Dateien aus boerse/, Trading/, Geldverdienen/ (Trading-Anteil) → wiki/concepts/ oder wiki/entities/
- Hermes-relevante Dateien → wiki/concepts/ (z.B. Automation, Agent, Prompt)
- Reise/Orte → wiki/entities/ (Berlin, München, Krakau, Prag, etc.)
- Tools/KI → wiki/entities/ (Claude, ChatGPT, Gemini, Google, etc.)
- Verlinke jede neue Seite im trading-index.md unter der richtigen Kategorie

## B — Intention weiterdenken
Lies neue/geänderte Dateien. Was ist der Kern? Übersetze ihn in konkrete nächste Schritte für Martins Infrastruktur. Schreib eine "Weitergedacht"-Sektion in deinen Report. Wenn die Watchlist neue auffällige Muster zeigt (Duplikate, fehlende Ticker, Quellenverschiebung), analysiere die möglichen Auswirkungen auf das Trading-System.

## C — Proaktive Vorschläge (max 3)
Wenn dir etwas auffällt was Martin übersehen hat: maximal 3 Vorschläge, jeder mit:
- Konkretem nächstem Schritt
- Aufwandsschätzung
- Der Frage "Soll ich das jetzt umsetzen?"

**Wichtig:** Prüfe bei Watchlist-Änderungen ob die Exit Management Page noch aktuell ist.

## D — Exit Management Auto-Refresh
Nachdem du Wiki-Seiten aktualisiert hast: prüfe die Timestamps von `Projekte/Hermes_Trading_Skill_Erklaerung.md` vs `wiki/concepts/Exit Management.md`. Wenn die Quelle neuer ist, aktualisiere die Exit Management Seite. Tracke diesen Check im Report.

Liefere deinen Report als strukturierte Telegram-Nachricht mit Sektionen: Wiki-Updates, Weitergedacht, Proaktive Vorschläge, Exit-Management-Check.
```

## History

| Date | Changes |
|------|---------|
| 2026-05-26 | Added Exit Management Auto-Refresh section (D). Added proactive Watchlist maintenance and timestamp comparison logic. |
| 2026-05-11 | Original prompt — 3 tasks (A: Einsortieren, B: Intention weiterdenken, C: Proaktive Vorschläge) |