---
name: dataviz-story-scout
description: >-
  Wöchentliche Data-Story-Ideen-Generierung für faceless Social-Content (DE/EU-Markt).
  Betreibt den dataviz-ideen-weekly Cron (Samstag 12:00), scannt aktuelle Datenquellen
  nach emotionalen, teilbaren Geschichten und formatiert sie als Chart-Vorschläge.
  Kein Bauen der Visualisierung — nur Ideen-Lieferung.
---

# DataViz Story Scout

## Überblick

Wöchentlicher Cron-Job (`dataviz-ideen-weekly`, ID `f9f061808aaf`, Samstag 12:00) der 10
Datenvisualisierungs-Ideen mit konkreten, frei zugänglichen Quellen liefert. Ziel:
faceless Social-Account mit deutschen Datengeschichten (Instagram/LinkedIn/X).

Das Goal-File liegt unter `~/hermes/goals/dataviz_ideen.txt` und enthält den vollständigen
Scout-Prompt inkl. Quellen, Scoring und Output-Format.

## Setup

### Cron-Job (existiert bereits)

```
Job-ID:  f9f061808aaf
Name:    dataviz-ideen-weekly
Schedule: 0 12 * * 6 (Samstag 12:00)
Model:   deepseek/deepseek-v4-flash (OpenRouter)
Deliver: telegram
Goal:    ~/hermes/goals/dataviz_ideen.txt
```

### Goal-File Struktur

Das Goal-File (`~/hermes/goals/dataviz_ideen.txt`) enthält:

1. **Rolle**: Data-Story-Scout für faceless Content
2. **Schritt 1 — Aktuellen Bezug sammeln**: News/Quellen DE/EU letzte 7-14 Tage
3. **Schritt 2 — Ideen formen**: News-Hook + Evergreen Mix, 4 Hooks
4. **Schritt 3 — Datenquellen-Gate**: Nur frei zugängliche, konkrete Quellen
5. **Scoring**: Hook-Stärke × Datenverfügbarkeit, Aktualität als Tiebreaker
6. **Dedup**: Gegen 8-Wochen-Store
7. **Output**: 10 Ideen mit Titel, Story, Viz-Idee, Quelle, Caption-Hook

### Dedup-Store

Die Ideen der letzten 8 Wochen liegen unter `~/hermes/reports/`.
Format: `dataviz_ideen_YYYY-WW.md` (ISO-Kalenderwoche).

## Die 4 Hooks (aus dem Instagram-Trendreport Juni 2026)

Jede Idee MUSS einen dieser 4 Hooks treffen:

| Hook | Frage | Beispiel |
|------|-------|---------|
| **Identität** | "Bin ich normal?" | Gehalt nach Beruf, Ausgaben nach Alter |
| **Vergleich** | "Wo stehe ich?" | Stadt-Vergleich Lebenshaltung, DE vs. EU |
| **Neugier** | "Echt jetzt?" | Überraschende Zusammenhänge |
| **Überraschung** | "Wtf?" | Unerwartete Entwicklungen, krasse Unterschiede |

## Ideal-Beispiel (aus X-Trend Juni 2026)

Der Post "Seit 2020: Energie +50%, Lebensmittel +30-40%, Verbraucherpreise +25%"
hat 150+ Likes + hitzige Diskussion ausgelöst. Warum:
- 3 einfache Zahlen, kein Chart nötig
- Langer Zeitraum (2020→heute), klarer Trend
- Jeder spürt es im Alltag — Zahlen bestätigen Bauchgefühl
- Thread-Replies liefern sofort neue Story-Ideen

**Die Formel:** "Seit [Zeitraum] ist [Alltagsgut] um [überraschende Zahl] gestiegen/gefallen."

## Quellen-Priorität

| Quelle | Typ | Zugang |
|--------|-----|--------|
| Destatis GENESIS-Online | Offizielle Statistik | Frei, Tabellennummer bekannt |
| Eurostat | EU-Vergleich | Frei, Dataset-Code |
| Bundeshaushalt.de | Staatsausgaben | Frei |
| DIW (SOEP) | Einkommen/Kaufkraft | Frei |
| BNetzA/SMARD | Energie/Strom | Frei, API |
| Tankerkönig-API | Spritpreise | Frei |
| FRED (St. Louis Fed) | Makro/Rohstoffe | Frei |
| Bundesagentur für Arbeit | Arbeitsmarkt | Frei |
| Numbeo | Lebenshaltungskosten | Frei |
| Tagesschau/Handelsblatt/ZEIT | News-Hooks | Frei (RSS/Web) |

## Visualisierungs-Formate (optional, kein Zwang)

Out-of-the-box Ideen erwünscht:
- Bar Chart Race (klassisch, gut für Rankings über Zeit)
- Animierte Karte (regionaler Vergleich)
- Scrollytelling (längere Story)
- Vergleichs-Animation (vorher/nachher)
- Zeitraffer (Entwicklung über Jahre)
- Ranking-Animation (wer steigt/fällt)
- Single-Stat Slide (1 überraschende Zahl, 1 Bild)

## Bekannte Pitfalls

- **Firecrawl-Credits leer**: web_search/web_extract oft nicht verfügbar. Ausweichen auf:
  curl + old.reddit.com für Reddit-Quellen, direkte API-Calls (FRED, Tankerkönig), Exa Search via `mcporter`
- **Keine erfundenen Daten**: Jede Idee braucht eine reale, frei zugängliche Quelle. Lieber 7 solide Ideen als 10 mit toten Quellen.
- **Dedup vergessen**: Immer gegen den 8-Wochen-Store checken. Gleiches Thema nur mit neuem Winkel wiederholen.
- **Zu generisch**: "Chart über Inflation" → scheitert am Hook-Gate. Immer: "Seit 2020 sind Lebensmittel 35% teurer, aber die Löhne nur 12% gestiegen."

## Verifikation

```bash
# Cron-Job Status
hermes cron list | grep dataviz

# Letzten Report lesen
ls -lt ~/hermes/reports/dataviz_ideen_*.md | head -3

# Goal-File prüfen
cat ~/hermes/goals/dataviz_ideen.txt
```

## Wartung

- Goal-File bei neuen Erkenntnissen patchen (neue Quellen, neue Hook-Erkenntnisse)
- Dedup-Store nach 8 Wochen automatisch überrollt
- Cron läuft Samstag 12:00 — wenn er ausfällt: manuell triggern via `hermes cron run f9f061808aaf`