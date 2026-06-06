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
- **Maximale Anzahl**: Maximal 5 unique Top-Themen der letzten 24 Stunden (seit gestern 6:00 Uhr), aggregiert aus seriösen Quellen (Tagesschau, Spiegel, FAZ, Welt, ZEIT, Handelsblatt, Reuters, ARD, NDR etc.). Bei ruhiger Lage weniger Themen oder eine kurze ehrliche Einleitungssatz (kein "Ruhiger Morgen").
- **Strenge Auswahlregeln**: Identifiziere zuerst die dominierenden Meldungen über alle großen Quellen hinweg und aggregiere zu maximal 5 einzigartigen, relevanten Themen. Priorisiere Politik, Wirtschaft, Technologie, internationale Konflikte, EU, Energie, Infrastruktur. Immer regionale Relevanz für Mecklenburg-Vorpommern, Schleswig-Holstein, Hamburg, Skandinavien und Polen prüfen und einbeziehen, wenn relevant. Ignoriere vollständig: Sport, Promis, Kriminalität ohne große Relevanz, Unterhaltung.
- **Format pro Thema**:
  1. Klare, aussagekräftige Überschrift (max. 8–10 Wörter)
  2. Neutrales, faktenreiches Summary (4–6 Sätze)
  3. Wichtige Fakten & Zahlen (Bullet Points)
  4. Quellen (mit Links) am Ende jeder Meldung
- **Gesamtaufbau** (strikt einhalten): 
  - Titel: Morgen-Briefing – [Wochentag], [DD.MM.YYYY]
  - Sinnvolle Gruppierung: Politik & Internationales / Wirtschaft & Technologie / Regional Nordost & Skandinavien
  - Trennlinie: ———
  - Bei ruhiger Lage: Kurzer ehrlicher Einleitungssatz (1 Satz), welche Themen die Berichterstattung dominierten.
  - Neue Abschnitte: Wetter heute (Ratzeburg & Schwerin) mit konkreten Werten; Wassertemperaturen Ostsee & Schweriner See (nie „keine Messung verfügbar“ – aktiv suchen auf wetter.com, wetteronline.de, DWD, wassertemperatur.org, seatemperature.org, NDR etc.).
- **Stil**: Nüchtern, sachlich, professionell, wie ein guter Nachrichtenticker. Maximaler Informationsgehalt, knappe Form. Keine Emojis, keine Wertungen, keine Spekulationen, keine vagen Formulierungen (z. B. vermeide „plant Strategien“, „bereitet vor“ – nur konkrete Entscheidungen oder Maßnahmen). Finale Cron-Antwort ausschließlich das Briefing (oder exakt "[SILENT]"). Komplett auf Deutsch.
- **Recherche**: Nutze intensive Web-Suche und Scraping (browser_navigate + browser_snapshot zuerst auf tagesschau.de, spiegel.de, faz.net, ndr.de, welt.de, handelsblatt.com). Cross-Check jede Meldung mit mindestens 2–3 seriösen Quellen. Bei Regionalthemen gezielt suchen („Mecklenburg-Vorpommern Politik heute“, Ostsee-Zeitung, NDR MV Aktuell). Vor Schreiben einer Meldung oder Aussage „wenig Neues“ Tools intensiv nutzen.
- **Quellen & Cross-Check**: Primär seriöse Seiten via Browser-Tools/Scraping (Tagesschau, FAZ, Welt, Handelsblatt, Spiegel, Reuters, ARD/NDR). Immer mindestens 2–3 Quellen cross-checken. Nutze `browser_navigate` + `browser_snapshot` + `terminal` (curl mit realistischem User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"). Bei Browser-Fehlern (403, Consent-Banner, leere Snapshots) sofort auf curl oder alternative seriöse URLs ausweichen.

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
- **Browser-Blockaden** – Viele News-Seiten zeigen Consent-Banner oder Anti-Bot-Maßnahmen → Snapshot nach Navigation auswerten, ggf. mehrfach navigieren oder auf alternative seriöse Quellen ausweichen. Bei Bedarf `browser_click` auf Consent-Buttons. Bei leeren oder extrem langen/trunkierten Snapshots (oft >2000 Zeilen mit Navigation/Consent, wie in den Sessions 26.05., 27.05., 29.05. und 31.05.2026 beobachtet) **sofort** auf `curl -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36" <URL> | grep -oE '<h[1-4][^>]*>.*?</h[1-4]>'` (oder erweiterte Varianten mit pup/xmllint) umschalten. Dies hat sich als der zuverlässigste und schnellste primäre Ansatz für Cron-Jobs erwiesen. Browser-Tools nur gezielt für tiefergehende Artikel-Details nachnutzen. Neue Referenz: `references/2026-05-31-cron-outcome.md`.
- **Zeitliches Fenster** – Briefing immer Nachrichten der letzten ~24 Stunden (seit gestern 6:00 Uhr MEZ) berücksichtigen. Aktuelles Datum via `date` prüfen.
- **Regionale & Thematische Filterung** – Nur wirklich relevante und neue Entwicklungen mit klarem Bezug zu DE-Nordost, Skandinavien, Polen auswählen. Internationale Konflikte und lokale Ereignisse explizit einbeziehen (nicht herausfiltern). Ignoriere Sport, Klatsch, Promi-News, Unterhaltung, Verbrechen ohne übergeordnete Relevanz sowie reine Alltagsmeldungen. Bei geringer Nachrichtenlage explizit eine kurze, sachliche „Ruhiger Morgen“-Zusammenfassung mit Begründung („keine qualifizierten Meldungen in den priorisierten Regionen/Themen nach Cross-Check mehrerer Quellen“), expliziter Auflistung der geprüften Quellen und Wassertemperatur-Abschnitt anhängen. Diese Variante wurde in der Cron-Ausführung vom 24.05., 25.05., 26.05. und 27.05.2026 erfolgreich eingesetzt. Die Formulierung muss nüchtern bleiben. Keine Meta-Kommentare, Tool-Erwähnungen oder Erklärungen in der finalen Ausgabe.
- **Cross-Checking** – Mindestens 2–3 unabhängige Quellen für jede Meldung bestätigen, bevor sie ins Briefing aufgenommen wird. Bei ruhigen Tagen explizit die durchgeführten Quellen (Tagesschau, Spiegel, FAZ, Handelsblatt, Reuters, lokale norddeutsche und skandinavische Medien) nennen.
- **Paralleles Laden** – `delegate_task` mit mehreren parallelen Browser-Aufrufen für Tagesschau, FAZ, Handelsblatt, Spiegel etc. reduziert Laufzeit. Nach Browser-Interaktionen Snapshot mit `full=false` für kompakte Übersicht nutzen. Bei Browser-Fehlern (Consent-Banner, 403, leere Snapshots) auf alternative URLs oder curl mit starkem User-Agent ausweichen.
- **Output-Disziplin** – Für Cron-Jobs (6:00 Uhr) exakt das geforderte Telegram-Format liefern. Die finale Antwort besteht **ausschließlich** aus dem Briefing-Text (oder [SILENT] bei nichts Neuem). Keine Tool-Zusammenfassungen, keine Meta-Kommentare, keine englischen Reste, keine Erklärungen zur Methodik. Bei sehr ruhiger Lage eine kurze, sachliche „Ruhiger Morgen“-Zusammenfassung mit kurzer Begründung („keine qualifizierten Meldungen in den priorisierten Regionen/Themen nach Cross-Check mehrerer Quellen“) und Wassertemperatur-Abschnitt.

## Beispielaufruf
```bash
python daily_news.py   # erzeugt die Datei für den aktuellen Tag
```

## Ausgabe
Erstellt die Datei `~/obsidian-vault/Daily-News-2026-05-08.md` mit den beiden Listen, einem Event‑Abschnitt und korrekter Quellen‑Diversity.

## Referenzen
Siehe `references/`-Verzeichnis:
- `2026-05-24-cron-outcome.md`
- `2026-05-25-cron-outcome.md`
- `2026-05-26-cron-outcome.md`
- `2026-05-27-cron-outcome.md`
- `2026-05-29-cron-outcome.md` (Bestätigung von curl + grep als primärem robustem Fallback bei langen Browser-Snapshots; erfolgreiche Anwendung des „Ruhiger Morgen“-Formats mit Quellenauflistung und „keine aktuellen Messwerte verfügbar“ bei Wassertemperaturen; strikte Output-Disziplin ohne Tool-Spuren)
- `2026-05-27-cron-outcome.md`
- `2026-05-29-cron-outcome.md` (Bestätigung von curl + grep als primärem robustem Fallback bei langen Browser-Snapshots; erfolgreiche Anwendung des „Ruhiger Morgen“-Formats mit Quellenauflistung und „keine aktuellen Messwerte verfügbar“ bei Wassertemperaturen; strikte Output-Disziplin ohne Tool-Spuren)
