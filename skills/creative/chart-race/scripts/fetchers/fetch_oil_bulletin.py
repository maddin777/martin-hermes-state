#!/usr/bin/env python3
"""
Fetcher: EU Weekly Oil Bulletin -> Wide-CSV (Land x Woche), Preis in €/Liter.

Vertrag (siehe references/data_sources.md):
    python fetch_oil_bulletin.py <chart_type> <produkt> <countries_csv> <produces>

    produkt        : benzin | diesel
    countries_csv  : "Deutschland,Frankreich,Italien"  (deutsche Namen)
    produces       : Zielpfad der CSV

Rechnet Landeswährung ÷ gemeldeter EUR-Kurs auf €/l um -> keine HUF/PLN-Ausreißer.
Nutzt den GitHub-Mirror (bis ~06/2024). Für aktuellere Daten die offizielle
History-xlsx laden (Logik analog zu update_daten.py des fuel-Projekts).
"""
import subprocess
import sys
import pandas as pd

MIRROR = ("https://raw.githubusercontent.com/the-Hull/"
          "weekly_oil_bulletin/master/data/db/wob_full.csv")
PRODUCT_MAP = {"benzin": "Euro-super 95", "diesel": "Automotive gas oil"}
DE_NAMES = {"Germany": "Deutschland", "France": "Frankreich", "Italy": "Italien",
            "Spain": "Spanien", "Netherlands": "Niederlande", "Belgium": "Belgien",
            "Austria": "Österreich", "Luxembourg": "Luxemburg", "Poland": "Polen",
            "Czechia": "Tschechien", "Denmark": "Dänemark", "Sweden": "Schweden",
            "Hungary": "Ungarn"}
EN_NAMES = {v: k for k, v in DE_NAMES.items()}


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)
    _chart, produkt, countries_csv, produces = sys.argv[1:]
    product = PRODUCT_MAP.get(produkt.lower())
    if not product:
        print(f"Unbekanntes Produkt '{produkt}' (benzin|diesel)", file=sys.stderr)
        sys.exit(1)
    wanted_de = [c.strip() for c in countries_csv.split(",") if c.strip()]
    wanted_en = [EN_NAMES.get(c, c) for c in wanted_de]

    # Download in tmp
    tmp = "/tmp/wob_full.csv"
    subprocess.run(["curl", "-sL", "-o", tmp, MIRROR], check=True)
    df = pd.read_csv(tmp, sep=";", parse_dates=["Prices in force on"])
    df = df.rename(columns={"Prices in force on": "date", "Country Name": "country",
                            "Product Name": "product",
                            "Weekly price with taxes": "brutto",
                            "Euro exchange rate": "rate"})
    df["country"] = df["country"].replace({"Czech Republic": "Czechia"})
    df = df[(df["product"] == product) & (df["country"].isin(wanted_en))].copy()
    df["eur_l"] = df["brutto"] / df["rate"] / 1000  # -> €/l, währungsbereinigt

    wide = df.pivot_table(index="country", columns="date", values="eur_l")
    wide.index = [DE_NAMES.get(c, c) for c in wide.index]
    wide = wide.round(3)
    wide.columns = [d.strftime("%Y-%m-%d") for d in wide.columns]
    wide.to_csv(produces, index_label="Land")
    print(f"geschrieben: {produces}  ({len(wide)} Länder, {wide.shape[1]} Wochen)")


if __name__ == "__main__":
    main()