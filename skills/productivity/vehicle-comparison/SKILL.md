---
name: vehicle-comparison
description: >
  Vergleiche Gebrauchtwagen für Martin nach festen Kriterien:
  Budget max 7k, Platz hinten > Kofferraum, Bodenfreiheit, Benziner,
  Handschalter, kein VAG. Liefert Tabellen mit Vorteil-Spalte
  und effektiven Gesamtkosten.
---

# Vehicle Comparison

## Wann laden
- Martin vergleicht zwei oder mehr Gebrauchtwagen
- Martin fragt nach technischen Details eines konkreten Modells (Bodenfreiheit, bekannte Probleme, Rost)
- Martin schickt ein konkretes Angebot und will eine Bewertung

## Martins fixe Kriterien (aus Memory)
- Budget: **max 7.000€** (Ausnahmen nur auf seinen Wunsch)
- Priorität: **Platz hinten** > Kofferraum
- **Bodenfreiheit / Höherlegung** wichtig (höhere Sitzposition)
- **Kein Allrad** nötig (Frontantrieb reicht)
- **Handschalter** (kein DSG/Automatik)
- **Benziner** (kein Diesel — Umweltzonen, Steuer, DPF-Ärger)
- **Kein VAG** (VW/Audi/Skoda/Seat) — zu viele bekannt Probleme (Steuerketten, DSG, brechende Federn, Abgasskandal)
- Wohnort: Schwerin (19055) — Umkreis relevant für Besichtigung

## Vergleichsformat
Immer **tabellarisch** mit:
1. Technische Daten nebeneinander
2. **Vorteil-Spalte** (wer gewinnt in diesem Punkt)
3. **Kosten-Wahrheit**: Kaufpreis + fällige Wartung + Steuer-Differenz über 3 Jahre
4. Bekannte Probleme pro Modell separat auflisten
5. Klares Fazit mit Empfehlung

## Bekannte Problem-Checks (Recherche-Pflicht)

### Kia Soul (Gen 2, 2014-2016)
- **Hinterachs-Rost** — Verbundlenkerachse rostet von innen. Prüfung: Hammer-Test (dumpfer Sound = Rost). Fix: Achse tauschen ~2.000€.
- 1.6 GDI Motor: Steuerkette hält gut, kein bekanntes Massenproblem
- DSG? Nein — nur Schalter und Automatik (6-Gang Wandler, kein DSG)

### Dacia Dokker Stepway (2012-2021)
- **Bodenfreiheit ~190mm** (Stepway, Serie +30mm) — höher als Yeti!
- **Schiebetüren** beidseitig — praktisch in der Stadt
- **Platz hinten: Riesig** (Hochdach, fast stehend möglich)
- **1.6 SCe 100 PS** — Saugrohreinspritzung, kein Turbo, kein Direkteinspritzung.
  Steuerkette hinten hält. **Ultra-robuster Urmotor** (Renault K7M, seit den 90ern).
  Einziger Nachteil: 8L Verbrauch.
- **1.5 dCi 90 PS** — Renault K9K, solide, aber Diesel (AGR/DPF bei Kurzstrecke).
- **3 NCAP-Sterne** (2013) — das ist der Haken. Kein ESP in frühen Modellen.
- **Verarbeitung:** Hartplastik pur, laut bei Autobahnfahrt, Sitze wie Brett auf
  Langstrecke. Kein Komfort.
- **Preis:** 4.000-7.000€ (für 2015er mit ~100tkm)
- **Fazit:** Budget-Wunder. Höchste Bodenfreiheit aller verglichenen Modelle.
  Aber 3 NCAP macht Sorgen.

### Skoda Yeti (2009-2017) — weitere Details
- **1.2 TSI (105 PS) bis 2012**: Steuerkette reißt → Motorschaden. **NICHT EMPFEHLEN.**
- **1.8 TSI (160 PS)**: Steuerkette + Kolbenringe → Ölverbrauch, Motorschaden. **NICHT EMPFEHLEN.**
- **1.4 TSI EA211 (122 PS) ab 2013**: Zahnriemen statt Steuerkette — das ist der
  **sichere** Yeti-Motor. ABER: Zahnriemen-Wechsel alle 180tkm/6J (~1.000€). Bei
  11 Jahren + 154tkm stand der Wechsel an.
- **2.0 TDI**: Solide, aber Diesel (höhere Steuer, DPF, Abgasskandal)
- **Brechende Federn**: VAG-Klassiker, besonders hinten. Prüfen!
- **DSG DQ200 (7-Gang Trocken)**: Mechatronik-Defekte ~1.500-2.500€.
  Handschalter bevorzugen.
- **Rost**: Türkanten, Heckklappe, Schweller
- **VarioFlex-Sitze hinten**: einzeln verschiebbar + herausnehmbar. Bester
  Platz hinten im Vergleich.
- **Bodenfreiheit ~180mm** (Serie) — gut, aber Dokker Stepway ist höher.
- Konkretes Angebot analysiert: Yeti Adventure 8.200€, 154tkm, 2015, 2. Hand.
  Effektive Kosten: 9.380€ (Kaufpreis + fälliger Zahnriemen).
- **Gegenüber Soul:** 44.000km mehr gelaufen, Euro 5 statt 6, Zahnriemen fällig,
  aber mehr Bodenfreiheit und VarioFlex.

### Renault Kangoo Trekka 4x4
- **19-23 Jahre alt** → Rost überall: Schweller, Radläufe, Schiebetüren
- Allrad-Komponenten (ATC-Kupplung) — Ersatzteile knapp
- 1.9 dCi solide, 1.6 16V säuft (9L)
- Euro 3/4 — Umweltzonen-Problem

### VW Touran (1T3, 2010-2015)
- **Bodenfreiheit ~140mm** — niedriger als Soul (150mm) und Yeti (180mm)
- 2.0 TDI vom Abgasskandal betroffen
- AGR/DPF-Probleme bei Kurzstrecke
- Platz hinten: sehr gut (3 Einzelsitze, optional 7)

### Suzuki Ignis
- **Gen 1 (2003-2008)**: 17-22 Jahre alt, kaum noch relevant. Rost an Heckklappe + Schweller. Kein ESP in Basis.
- **Gen 3 (2016-2020)**: Die moderne Version. Für 7k nur mit hoher Laufleistung. 1.2 Dualjet 90 PS + Mildhybrid. Allrad optional (Allgrip). Verbrauch 4,5L!

## Recherche-Tooling
- Wikipedia API (curl): `https://en.wikipedia.org/w/api.php?action=query&titles=<Model>&prop=extracts&format=json&explaintext=1`
- Deutsche Wikipedia für detailreichere Infos: `https://de.wikipedia.org/w/api.php?action=query&titles=<Model>&prop=extracts&format=json&explaintext=1`
- Bei Firecrawl-Ausfall: Browser oder curl mit User-Agent als Fallback
- Preise: Kein direktes Scraping von mobile.de/autoscout24 möglich (blocked) — auf Wissen oder konkrete Angebote des Users angewiesen

## Ausgabe-Regel
Nach dem Vergleich immer fragen: "Soll ich nach konkreten Angeboten suchen / nachverhandeln / Alternative vorschlagen?" — Martin entscheidet, nicht du.