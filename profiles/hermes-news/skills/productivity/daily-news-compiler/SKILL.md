---
name: daily-news-compiler
description: Automatisierte tägliche Zusammenstellung von Nachrichten (Politik, Wirtschaft, Events) für Europa mit Fokus auf die letzten 12 Stunden. Nutzt öffentlich verfügbare Google‑News‑RSS‑Feeds, filtert nach Zeit, de‑dupliziert und wählt nach Quellen‑Vielfalt aus. Generiert Markdown für Obsidian mit [[Politics]], [[Economy]], [[Events]].
version: 1.0
author: Hermes Agent
---

# Ziel
Erstelle eine Markdown‑Datei `Daily‑News-YYYY-MM-DD.md` im Obsidian‑Vault, die bis zu 20 relevante Nachrichten (max. 10 Politics, 10 Economy) der letzten 12 Stunden enthält, mit ausgewogener Quellen‑Vielfalt und separatem Events‑Abschnitt.

## Vorgehensweise
1. **Zeitliche Schwelle**
   - `cutoff = datetime.utcnow() - timedelta(hours=12)`
2. **Quellen‑Definition**
   - Baue für jede Kategorie (Politics, Economy) eine Liste von Tupeln `(source_name, google_news_rss_url)`.
   - Nutze `site:`‑Operatoren für Reuters, AP, DW, Tagesschau, FAZ, Handelsblatt, Spiegel, NYT, Guardian, Al Jazeera, CNN, BBC.
   - Beschränke das Datum im RSS‑Query auf den vorherigen Tag (z. B. `after:2026-05-08 before:2026-05-09`).
3. **Abruf**
   - Für jede URL `urllib.request.urlopen(url, timeout=12)`
   - Parse XML mit `xml.etree.ElementTree`.
4. **Item‑Extraktion**
   - Titel, Link, Beschreibung, `pubDate` aus `<item>`.
   - Ignoriere Einträge ohne `pubDate` oder ältere als `cutoff`.
   - Bereinige Beschreibung (HTML‑Tags entfernen, HTML‑Entitäten ent‑escapen).
   - Kürze auf 1‑2 Sätze.
5. **Deduplication**
   - Nutze den Link als eindeutigen Schlüssel.
6. **Sortierung**
   - Nach `pubDate` absteigend.
7. **Auswahl‑Logik**
   - Bis zu 20 Items gesamt.
   - Pro Quelle max. 5 Items, BBC max. 2 insgesamt.
   - Mindestens 3 verschiedene Quellen pro Kategorie.
   - Falls weniger als 5 Items einer Kategorie, ergänze aus Rest‑Pool unter Einhaltung der Quell‑Limits.
8. **Event‑Erkennung**
   - Prüfe Titel und Zusammenfassung auf Schlüsselwörter: `summit|conference|meeting|forum|gipfel|kongress|tagung|symposium|veranstaltung` (case‑insensitive).
   - Sammle mindestens 5 Event‑Items, wenn möglich.
9. **Markdown‑Erzeugung**
   - Header `# Tagesnachrichten YYYY-MM-DD`
   - Sektionen `[[Politics]]`, `[[Economy]]`, `[[Events]]`.
   - Für jedes Item:
     - `- **Titel** (Quelle: Source – [Link](URL))`
     - `  - Kurz‑Zusammenfassung`
     - `  - YYYY-MM-DD HH:MM UTC`
10. **Datei‑Schreiben**
    - Pfad `~/obsidian-vault/Daily-News-YYYY-MM-DD.md`
    - UTF‑8, überschreiben.

## Fallenstellen / Pitfalls
- **RSS‑Blockierung**: Direktes Abrufen von Reuters‑RSS kann Captcha zurückgeben. Lösung: Google‑News‑RSS mit `site:`‑Filter.
- **Zeitzonen**: `pubDate` ist meist GMT/UTC – stets als UTC behandeln.
- **Leere Feeds**: Einige Quellen liefern keine Einträge im 12‑Stunden‑Fenster; ignorieren, nicht abbrechen.
- **XML‑Namespace‑Probleme**: Manche Feeds nutzen Namespaces; das `findall('.//item')`-Muster ist robust.
- **Doppelte Einträge**: Gleiches Thema kann über verschiedene Quellen erscheinen – Link‑Deduplication verhindert Wiederholungen.
- **Rate‑Limits**: Google‑News‑RSS ist kostenlos, aber zu viele gleichzeitige Anfragen können kurzzeitig blockieren. Bei Fehlern einen kurzen Sleep (z. B. 1 s) zwischen Anfragen einbauen.

## Test / Verification
- Führe das Skript lokal aus und prüfe, dass die resultierende Markdown‑Datei nicht leer ist und mindestens 3 Quellen pro Kategorie enthält.
- Verifiziere, dass keine BBC‑Einträge über 2 hinauskommen.
- Prüfe, ob Event‑Einträge tatsächlich das Schlüsselwort enthalten.

## Weiterentwicklung
- Optional: Erweiterung um **Lokale Veranstaltungen** (z. B. `site:veranstaltungen.de`).
- Optional: Hinzufügen einer **Kategorisierung** nach Land/Region mithilfe von `title`‑Analyse.
- Optional: Caching‑Mechanismus, um bereits verarbeitete Links zu speichern und unnötige Wiederholungen zu vermeiden.
