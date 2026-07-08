# Datenquellen-Whitelist (Modus B: Self-Fetch)

DeepSeek darf im Self-Fetch-Modus **nur** aus dieser Liste wählen. Jeder Eintrag
nennt Einheit, Plausigrenze (`expected_max`) und den Fetcher, der die CSV baut.
Neue Quellen hier ergänzen UND einen Fetcher in `scripts/fetchers/` anlegen.

> **Wichtig — Einheiten/Währung:** Nicht-Euro-Länder melden teils in Landeswährung
> (HUF, PLN, CZK, DKK, SEK, RON). Der Fetcher MUSS auf eine gemeinsame Einheit
> umrechnen, sonst entstehen Ausreißer wie "Ungarn 491 €/l". `expected_max`
> fängt solche Fehler als Warnung ab.

---

## 1. EU Weekly Oil Bulletin — Kraftstoffpreise EU

- **Inhalt:** wöchentliche Benzin-/Dieselpreise aller EU-Länder, mit/ohne Steuern
- **Einheit nach Fetch:** €/Liter (Landeswährung ÷ gemeldeter Kurs)
- **expected_max:** 3.0
- **Zeitraum:** 2005–heute (Mirror bis 06/2024, offizielle History aktueller)
- **Quelle:** https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en
  · Mirror: github.com/the-Hull/weekly_oil_bulletin
- **Fetcher:** `fetch_oil_bulletin.py`
  - args: `[chart_type, produkt, countries_csv, produces_pfad]`
  - produkt: `benzin` | `diesel`
  - Beispiel: `["line_race","benzin","Deutschland,Frankreich,Italien","/tmp/ob.csv"]`
  - Wide-Output: Zeile = Land, Spalten = Wochen

## 2. Brent Rohöl (wöchentlich)

- **Einheit:** USD/Barrel (Fetcher kann optional in €/l umrechnen)
- **expected_max:** 200 (USD/bbl) bzw. 1.5 (€/l)
- **Quelle:** github.com/datasets/oil-prices
- **Fetcher:** `fetch_brent.py` · args: `[unit, produces]` · unit: `usd_bbl`|`eur_l`

## 3. Zusammensetzung Benzinpreis DE (abgeleitet)

- **Inhalt:** Produkt/Marge, Energiesteuer, CO₂-Preis (BEHG), MwSt — in ct/l
- **Einheit:** Cent/Liter
- **expected_max:** 300
- **Herleitung:** siehe README des fuel-Projekts (BEHG-Stufen, Tankrabatt-Fenster)
- **Fetcher:** `fetch_de_composition.py` · args: `[produces]`
- **Chart-Empfehlung:** `stacked_area` (drei Komponenten sind fast flach → kein race)

## 4. Destatis GENESIS-Online (Platzhalter)

- **Inhalt:** amtliche DE-Statistik (Preise, Löhne, Energie …)
- **Einheit:** je Tabelle unterschiedlich → im Fetcher fixieren
- **Fetcher:** noch anzulegen (`fetch_destatis.py`, GENESIS-API-Key nötig)
- **Status:** TODO — bis dahin `need_input` zurückgeben

---

## Fetcher-Vertrag

Jeder Fetcher in `scripts/fetchers/`:
1. nimmt Argumente wie oben,
2. lädt/berechnet die Daten,
3. rechnet auf die dokumentierte Einheit um,
4. schreibt Wide-CSV (oder Long mit klaren Spalten) an `produces`,
5. exit 0 bei Erfolg.

Standard-Meilensteindatei: der Skill nutzt `references/meilensteine_vorlage.csv`
falls die Config keine eigene angibt.