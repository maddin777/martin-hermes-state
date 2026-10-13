# Evergreen DataViz Topics — vorgeprüft, wiederverwendbar

Themen, die die 4 Hooks treffen und regelmässig neue Daten bekommen. Jedes Topic enthält
konkrete Datenquellen und Varianten. Updates-Formel: nimm das beste alte Thema,
aktualisiere die Daten um 1-2 Jahre, ändere die Hook-Richtung.

## 1. Baupreise vs. Löhne

**Hooks:** Überraschung, Identität

**Datenquellen:**
- Destatis Tab. 61262-0001: Baupreisindex für Wohngebäude (1968–heute, Basis 2020=100)
- Destatis Tab. 62111-0001: Bruttolohnindex (1970–heute)
- Destatis Tab. 61111-0001: Verbraucherpreisindex (VPI)

**Kern-Story:**
Baupreisindex 1970: ~25 → 2024: ~120 (Faktor ~4,8). Lohnindex 1970: ~20 → 2024: ~90
(Faktor ~4,5). Seit 2000: Baupreise +80%, Löhne +45% → Schere öffnet sich.

**Varianten:** "1 Haus = 3 Jahresgehälter (1970) → 8 (2024)" · Baupreis vs. Inflation ·
Baupreis vs. Bauzinsen (Niedrigzins-Ära 2010-2021) · Baulandpreise vs. Baukosten.

```bash
curl -sL "https://de.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Baupreisindex" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(list(d['query']['pages'].values())[0].get('extract','')[:500])"
```

## 2. Politikergehälter vs. Normalverdiener

**Hooks:** Vergleich, Identität

**Datenquellen:** Wikipedia Abgeordnetenentschädigung; Destatis Tab. 62111-0001; Destatis
Durchschnittsbrutto (~4.500€/Monat Stand 2024).

**Kern-Story:** 2025 Bundestagsdiät 11.833€/Monat vs. Ø-Brutto ~4.500€ = Faktor 2,6. 1977
Diäten steuerpflichtig, vorher ~3.000€ vs. ~1.200€ DM = Faktor 2,5 — Verhältnis überraschend
stabil, aber seit BVerfG-Urteil 1975 NICHT mehr an Lohnentwicklung gekoppelt; geplante
Angleichung 2008 an Bundesrichterbezüge (8.159€) als "nicht vermittelbar" gestoppt.

**Varianten:** "1 Tag Bundestag = 2,6 Tage Arbeit" · Diätenerhöhung vs. Tariflohn seit 1977 ·
"Bundestagsdiät vs. Mindestlohn-Vollzeit" (11.833€ vs. ~2.100€ = Faktor 5,6) · Landtagsdiäten
(Bayern 10.178€ vs. Hamburg 4.807€).

| Jahr | Diät | Vergleich |
|------|------|-----------|
| 1949 | 600 DM + 450 DM Tagegeld | — |
| 1977 | ~7.500 DM | Steuerpflichtig ab hier |
| 2008 | ~7.000€ | Angleichung an Bundesrichter gescheitert |
| 2010 | ~7.668€ | Geplant, nie umgesetzt |
| 2025 | 11.833€ | Aktuell |

## 3. Mietpreise vs. Kaufpreise

**Hooks:** Identität, Neugier. **Datenquellen:** Destatis Immobilienpreisindex;
Gutachterausschüsse (Bodenrichtwerte); Empirica/Immowelt.
**Story-Idee:** "In München kaufst du 2025 für 1 Jahr Bruttogehalt 2m² — 1970 waren es 12m²."

## 4. Weitere Evergreen-Kandidaten

- Energiekosten DE vs. EU — Eurostat, BNetzA/SMARD
- Rentenlücke — Deutsche Rentenversicherung, Destatis
- Lebensmittelpreise vs. Inflation — Destatis VPI, Warenkorb
- Vermögensverteilung — DIW/SOEP, EZB
- Spritpreis-Entwicklung — Tankerkönig-API, MWST-Anteil über Zeit
- CO2-Preis vs. Effekte — Umweltbundesamt, Destatis
