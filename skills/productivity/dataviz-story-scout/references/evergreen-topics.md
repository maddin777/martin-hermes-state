# Evergreen Topics — DataViz

Vorgeprüfte Themen, die regelmäßig neu aufgelegt werden können. Jedes Topic enthält die konkreten Datenquellen und Vergleichsmöglichkeiten.

## 1. Baupreise vs. Löhne

**Hooks:** Überraschung, Identität

**Datenquellen:**
- Destatis Tab. 61262-0001: Baupreisindex für Wohngebäude (1968–heute, Basis 2020=100)
- Destatis Tab. 62111-0001: Bruttolohnindex (1970–heute)
- Destatis Tab. 61111-0001: Verbraucherpreisindex (VPI)

**Kern-Story:**
Baupreisindex 1970: ~25 Punkte → 2024: ~120 Punkte (Faktor ~4,8)
Lohnindex 1970: ~20 → 2024: ~90 (Faktor ~4,5)
Seit 2000: Baupreise +80%, Löhne +45% → Schere öffnet sich dramatisch

**Varianten:**
- "1 Haus = 3 Jahresgehälter (1970) → 8 Jahresgehälter (2024)"
- Baupreis vs. Inflation (Bau deutlich schneller)
- Baupreis vs. Bauzinsen (Niedrigzins-Ära 2010-2021)
- Baulandpreise vs. Baukosten (Boden vs. Material)

**Daten extrahieren:**
```bash
# Wikipedia API für Baupreisindex
curl -sL "https://de.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Baupreisindex" | python3 -c "import json,sys; d=json.load(sys.stdin); print(list(d['query']['pages'].values())[0].get('extract','')[:500])"
```

## 2. Politikergehälter vs. Normalverdiener

**Hooks:** Vergleich, Identität

**Datenquellen:**
- Wikipedia: Abgeordnetenentschädigung (aktuelle + historische Werte)
- Destatis Tab. 62111-0001: Bruttolohnindex
- Destatis: Durchschnittsbrutto (monatlich ~4.500€ Stand 2024)

**Kern-Story:**
- 2025: Bundestagsdiät 11.833€/Monat vs. Durchschnittsbrutto ~4.500€ = Faktor 2,6
- 1977: Diäten wurden steuerpflichtig, vorher ~3.000€ vs. ~1.200€ DM = Faktor 2,5
- Verhältnis überraschend stabil, aber: Diäten sind seit BVerfG-Urteil 1975 NICHT mehr automatisch an Lohnentwicklung gekoppelt
- 2008 geplante Angleichung an Bundesrichterbezüge (8.159€) wurde als "nicht vermittelbar" gestoppt

**Varianten:**
- "1 Tag Bundestag = 2,6 Tage Arbeit für Normalverdiener"
- Diätenerhöhung vs. Tariflohn-Entwicklung seit 1977
- "Bundestagsdiät vs. Mindestlohn-Vollzeit" (11.833€ vs. ~2.100€ = Faktor 5,6)
- Landtagsdiäten im Vergleich (Bayern 10.178€ vs. Hamburg 4.807€)

**Bekannte historische Datenpunkte:**
| Jahr | Diät | Vergleich |
|------|------|-----------|
| 1949 | 600 DM + 450 DM Tagegeld | — |
| 1977 | ~7.500 DM | Steuerpflichtig ab hier |
| 2008 | ~7.000€ | Angleichung an Bundesrichter gescheitert |
| 2010 | ~7.668€ | Geplant, nie umgesetzt |
| 2025 | 11.833€ | Aktuell |

## 3. Mietpreise vs. Kaufpreise

**Hooks:** Identität, Neugier

**Datenquellen:**
- Destatis Immobilienpreisindex
- Gutachterausschüsse (Bodenrichtwerte pro Stadt)
- Empirica/Immowelt (private Indizes, aber oft in Presse zitiert)

**Story-Idee:** "In München kaufst du 2025 für 1 Jahr Bruttogehalt 2m² — 1970 waren es 12m²"

## 4. Weitere Evergreen-Kandidaten

- **Energiekosten DE vs. EU** — Eurostat, BNetzA/SMARD
- **Rentenlücke** — Deutsche Rentenversicherung, Destatis
- **Lebensmittelpreise vs. Inflation** — Destatis VPI, Warenkorb-Daten
- **Vermögensverteilung** — DIW/SOEP, EZB
- **Spritpreis-Entwicklung** — Tankerkönig-API, MWST-Anteil über Zeit
- **CO2-Preis vs. Effekte** — Umweltbundesamt, Destatis