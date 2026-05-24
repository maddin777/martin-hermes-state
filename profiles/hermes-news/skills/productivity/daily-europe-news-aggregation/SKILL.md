---
name: daily-europe-news-aggregation
category: productivity
description: |
  Aggregiert die wichtigsten politischen und wirtschaftlichen Nachrichten aus Europa der letzten 12 Stunden aus mehreren Quellen, erzeugt eine formatierte Markdown‑Datei im Obsidian‑Vault und listet relevante heutige EU‑Events.
---

## Anforderungen
- Python 3.8+
- `requests`, `feedparser`, `python-dateutil`
- Schreibrechte für `~/obsidian-vault/`
- Internetzugang

## Ablauf (erweitert)

### Benutzerpräferenz: Telegram-Morgen-Briefing (streng priorisiert)
- **Maximale Anzahl**: 3 Nachrichten pro Briefing (bei sehr wenigen relevanten Meldungen 1–2 oder eine kurze „Ruhiger Morgen“-Zusammenfassung).
- **Format pro Nachricht**:
  1. Überschrift (klar und knapp)
  2. Neutrales Summary (3–6 Sätze)
  3. Wichtigste Fakten / Zahlen (Bullet-Liste)
  4. Quellen mit Links am Ende
- **Gesamtlänge**: Jede Nachricht max. ~3500 Zeichen. Gesamt-Briefing nüchtern, sachlich, professionell.
- **Stil**: Keine Emojis, keine Wertungen, keine Spekulationen. Wie ein guter Nachrichtenticker.
- **Thematische Priorisierung**: Starke regionale Fokussierung auf Deutschland (besonders Mecklenburg-Vorpommern und Schleswig-Holstein), Skandinavien (Schweden, Norwegen, Dänemark, Finnland), Polen sowie Entwicklungen mit direkter Relevanz für diese Regionen. Themen: Allgemeine News, Politik, Wirtschaft, Technologie. Ignoriere komplett: Sport, Klatsch, Promi-News, Unterhaltung, Verbrechen ohne übergeordnete Relevanz.
- **Quellen & Cross-Check**: Primär seriöse Seiten via Browser-Tools/Scraping (Tagesschau, FAZ, NZZ, Die Welt, Handelsblatt, Reuters, Bloomberg, Spiegel, lokale MV/SH-Zeitungen, Gazeta Wyborcza, SVT, NRK, Yle etc.). Ergänze mit X-Suche für allerfrischeste Entwicklungen. Immer mindestens 2–3 Quellen cross-checken. Nutze `browser_navigate` + `browser_snapshot` + `terminal` (curl mit realistischem User-Agent) für zuverlässige Abfragen.
- **Ausgabe**: Komplett auf Deutsch. Trennlinie `———` zwischen Nachrichten. Gruppierung möglich (z. B. „Politik & EU“, „Wirtschaft & Technik“, „Regional Nordost & Skandinavien“). Für Cron-Jobs direkt als finale Antwort liefern – keine zusätzlichen Erklärungen.

## Ablauf (erweitert)
1. **Quellen festlegen** – 3‑5 RSS‑Feeds pro Kategorie (z. B. BBC Europe, FAZ Politik, NYT Business, Al Jazeera, DW). Maximal 2 BBC‑Einträge pro Liste.
2. **Parallel‑Fetching** – Verwende `concurrent.futures.ThreadPoolExecutor` oder Hermes‑`delegate_task`‑Subagents, um alle Feeds gleichzeitig abzurufen und Netzwerk‑Latenz zu minimieren.
3. **HTTP‑Requests** mit einem realistischen `User-Agent` ausführen, um 403/401 zu vermeiden. Implementiere einen Retry‑Mechanismus (max 3 Versuche, exponentielles Back‑off).
4. **RSS‑Feeds parsen** (mit `feedparser`). Für Al Jazeera CDATA‑Titel mit `html.unescape` extrahieren, bei Bedarf mit Regex bereinigen.
5. **Artikel filtern** nach Publikationszeit (`published_parsed`) – nur Einträge der letzten 12 Stunden. Nutze `dateutil.parser` für unterschiedliche Zeitformate und Zeitzonen‑Handling.
6. **Quellen‑Diversity prüfen** – nicht mehr als 5 verschiedene Quellen pro Kategorie, maximal 2 BBC‑Einträge. Falls weniger Quellen verfügbar, greife auf **Google‑News‑Suche** (Bing‑API) als Fallback zurück.
7. **Fehlerhafte Feeds** – Bei einem Feed‑Fehler (z. B. Guardian 404) protokolliere das Problem, überspringe den Feed und nutze den Fallback‑Mechanismus; das Skript bricht nicht ab.
8. **Einträge formatieren** – `- [Titel](URL) (Quelle)`. Titel übersetzen (falls nötig) mit einfacher `str.translate`‑Mapping für gängige Wörter, oder über ein lokales Wörterbuch.
9. **Heutige EU‑Events** – Ziehe Ereignisse aus einer öffentlichen EU‑Kalender‑API (z. B. `https://data.europa.eu/euodp/en/data/dataset/eu-events`) oder nutze eine statische Tabelle, die regelmäßig aktualisiert wird.
10. **Markdown zusammenbauen** – Header `# Daily News YYYY‑MM‑DD`, Wikilinks `[[Politics]] [[Economy]]`, Abschnitte `## Politik` & `## Wirtschaft` und danach eine Event‑Tabelle.
11. **Datei schreiben** – Pfad `~/obsidian-vault/Daily‑News-YYYY‑MM‑DD.md`; Verzeichnis bei Bedarf anlegen.
12. **Verifikation** – Datei existiert, nicht leer, mindestens 5 Artikel pro Abschnitt; bei Unterschreitung sende Warnung im Log.

## Fallstricke & Lösungen
- **Feed-/RSS-Ausfälle** – Viele Endpunkte (Tagesschau API, Reuters etc.) liefern 403/404 oder HTML statt RSS → primär Browser-Tools (`browser_navigate` + `browser_snapshot`) oder `curl` mit starkem User-Agent (`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`) nutzen. Fallback auf direkte Seiten-Navigation (tagesschau.de, faz.net, handelsblatt.com, spiegel.de, n-tv.de, welt.de).
- **Browser-Blockaden** – Viele News-Seiten zeigen Consent-Banner oder Anti-Bot-Maßnahmen → Snapshot nach Navigation auswerten, ggf. mehrfach navigieren oder auf alternative seriöse Quellen ausweichen. Bei Bedarf `browser_click` auf Consent-Buttons.
- **Zeitliches Fenster** – Briefing immer Nachrichten der letzten ~24 Stunden (seit gestern 6:00 Uhr MEZ) berücksichtigen. Aktuelles Datum via `date` prüfen.
- **Regionale & Thematische Filterung** – Nur wirklich relevante und neue Entwicklungen mit klarem Bezug zu DE-Nordost, Skandinavien, Polen auswählen. Ignoriere Sport, Klatsch, Verbrechen ohne übergeordnete Relevanz sowie lokale Alltagsmeldungen. Bei geringer Nachrichtenlage explizit eine kurze „Ruhiger Morgen“-Zusammenfassung mit Begründung (Quellen-Check-Ergebnis) liefern. Diese Variante wurde in der Cron-Ausführung vom 24.05.2026 erfolgreich eingesetzt, als keine qualifizierten Meldungen vorlagen.
- **Cross-Checking** – Mindestens 2–3 unabhängige Quellen für jede Meldung bestätigen, bevor sie ins Briefing aufgenommen wird.
- **Paralleles Laden** – `delegate_task` mit mehreren parallelen Browser-Aufrufen für Tagesschau, FAZ, Handelsblatt, Spiegel etc. reduziert Laufzeit. Nach Browser-Interaktionen Snapshot mit `full=false` für kompakte Übersicht nutzen.
- **Output-Disziplin** – Für Cron-Jobs (6:00 Uhr) exakt das geforderte Telegram-Format liefern. Die finale Antwort besteht **ausschließlich** aus dem Briefing-Text (oder [SILENT] bei nichts Neuem). Keine Tool-Zusammenfassungen, keine Meta-Kommentare, keine englischen Reste, keine Erklärungen zur Methodik. Bei sehr ruhiger Lage eine kurze, sachliche „Ruhiger Morgen“-Zusammenfassung mit kurzer Begründung („keine qualifizierten Meldungen in den priorisierten Regionen/Themen nach Cross-Check mehrerer Quellen“).

## Beispielaufruf
```bash
python daily_news.py   # erzeugt die Datei für den aktuellen Tag
```

## Ausgabe
Erstellt die Datei `~/obsidian-vault/Daily-News-2026-05-08.md` mit den beiden Listen, einem Event‑Abschnitt und korrekter Quellen‑Diversity.
