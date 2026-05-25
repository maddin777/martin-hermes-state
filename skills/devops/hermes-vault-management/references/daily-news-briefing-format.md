# Kanonisches Format: Daily News Briefing (hermes-news Cron, 06:00)

Stand: 24.05.2026 — Nach Feedback von Martin: Prompt war zu streng filternd.
Lokale Ereignisse und internationale Konflikte werden jetzt explizit **nicht** gefiltert.
Wassertemperaturen als saisonale Ergänzung (Mai–September) hinzugefügt.

## Prompt-Struktur (aktuell in jobs.json)

**Zeitraum:** Letzte 24h (seit gestern 06:00)
**Umfang:** 3–5 Nachrichten, inklusive lokaler Ereignisse und int. Konflikte
**Kein "Ruhiger Morgen/entfällt"** — bei ruhigen Tagen: Kurze Zusammenfassung mit dem, was trotzdem passiert ist.

### Themen
- Allgemeine News, Politik, Wirtschaft, Technologie, **lokale Ereignisse**, **internationale Konflikte**
- Regionale Schwerpunkte: Deutschland (besonders MV + SH), Skandinavien (SE, NO, DK, FI), Polen
- **Lokale Ereignisse und int. Konflikte explizit erwünscht — nicht herausfiltern**
- Ignoriert: Sport, Klatsch, Promi, Unterhaltung, Verbrechen ohne Relevanz

### Saisonale Ergänzung (Mai–September)
**Wassertemperaturen-Abschnitt** am Ende des Briefings:
- **Schweriner See**: aktuelle Wassertemperatur
- **Ostsee bei Lübeck**: aktuelle Wassertemperatur
- **Warnemünde**: nur separat, wenn >5°C Unterschied zu Lübeck
- Quellen: DWD, wetter.com, seatemperature.org

### Quellen
- Primär: Web-Scraping (Tagesschau, FAZ, NZZ, Welt, Handelsblatt, Reuters, Bloomberg, Spiegel, lokale MV/SH-Zeitungen, Gazeta Wyborcza, Dziennik, SVT, NRK, Yle)
- Ergänzend: X-Suche via x_search (aktuellste Entwicklungen)
- Cross-Check: min 2-3 Quellen pro Meldung

### Output-Format
- Max **5** Nachrichten pro Tag (vorher 3)
- Pro Nachricht max ~3500 Zeichen
- Struktur:
  1. Überschrift (klar, knapp)
  2. Neutrales Summary (3-6 Sätze)
  3. Wichtigste Fakten / Zahlen
  4. Quellen mit Links
- Trennlinie: ———
- Gruppierung möglich: "Politik & EU", "Wirtschaft & Technik", "Regional Nordost & Skandinavien", "Internationales"
- Bei ruhigen Tagen: Kurze Zusammenfassung, **kein "entfällt" oder "Ruhiger Morgen"**

### Stil
- Nüchtern, sachlich, professionell
- Keine Emojis, keine Wertungen, keine Spekulationen
- Wie ein guter Nachrichtenticker

## Technische Konfiguration

```json
{
  "model": "grok-4.20-0309-non-reasoning",
  "provider": "xai-oauth",
  "schedule": "0 6 * * *",
  "deliver": "telegram"
}
```

## Goal-Struktur — Negativbeispiel

Der Ansatz mit `/goal` und `/subgoal` im Prompt wurde getestet und vom User verworfen.
Der User schrieb einen eigenständigen, vollständigen Prompt und legte Wert darauf, dass
dieser 1:1 übernommen wird. Keine agent-seitige Aufteilung in Subgoals.

## Lernpunkte für vault-insights-generierte Vorschläge

- Wenn der vault-insights Cron einen Vorschlag zum News-Briefing macht, immer das
  kanonische Format oben referenzieren.
- Kein Vorschlag für Goal-Struktur im News-Kontext — das wurde getestet und abgelehnt.
- Provider für den News-Cron ist xAI OAuth, NICHT OpenRouter (seit 21.05.2026).
- Das non-reasoning Modell ist bewusst gewählt (schneller, direkter Output).
- Wassertemperaturen sind NEU seit 24.05.2026 — bei Vorschlägen beachten.