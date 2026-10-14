#!/usr/bin/env python3
"""Pre-Run-Datenbeschaffung für den daily-news-briefing Cron.

Gibt strukturierte Rohdaten auf stdout aus. Der Cron-Agent formatiert nur noch,
er führt keine Befehle aus. Nur Stdlib. Quellen: Google News RSS, Open-Meteo, wassertemperatur.org.
Anpassen: FEEDS, WETTER_ORTE, WASSER_ORTE.
"""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HDR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

FEEDS = {
    "TOP-NACHRICHTEN": "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de",
    "POLITIK & INTERNATIONAL": "https://news.google.com/rss/search?q=Politik+USA+Ukraine+EU+China+Wahl&hl=de&gl=DE&ceid=DE:de",
    "FINANZEN & WIRTSCHAFT": "https://news.google.com/rss/search?q=DAX+B%C3%B6rse+Gold+%C3%96lpreis&hl=de&gl=DE&ceid=DE:de",
    "IT & KI": "https://news.google.com/rss/search?q=KI+Artificial+Intelligence+Tech&hl=de&gl=DE&ceid=DE:de",
    "DEUTSCHLAND & NORDEUROPA": "https://news.google.com/rss/search?q=Schleswig-Holstein+Mecklenburg-Vorpommern+Deutschland&hl=de&gl=DE&ceid=DE:de",
}
WETTER_ORTE = [("Ratzeburg", 53.70, 10.75), ("Schwerin", 53.63, 11.41)]
WASSER_ORTE = [("Ostsee Lübeck/Trave", "ostsee/luebeck"), ("Ostsee Wismar", "ostsee/wismar"),
               ("Ostsee Rostock", "ostsee/rostock"), ("Schweriner See", "schweriner-see")]
WMAP = {0: "klar", 1: "leicht bewölkt", 2: "teils bewölkt", 3: "bewölkt", 45: "Nebel", 48: "Nebel",
        51: "Sprühregen", 53: "Sprühregen", 61: "Regen", 63: "Regen", 65: "starker Regen", 80: "Schauer", 95: "Gewitter"}


def fetch(url, timeout=25):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=timeout).read()


def parse_rss(raw):
    out = []
    for it in ET.fromstring(raw).findall(".//item"):
        t = it.find("title"); s = it.find("source"); d = it.find("pubDate")
        try:
            # pubDate endet auf GMT; strptime mit %Z liefert naive Zeit.
            ts = datetime.strptime(d.text, "%a, %d %b %Y %H:%M:%S %Z")
        except Exception:
            ts = None
        out.append((t.text if t is not None else "", s.text if s is not None else "", ts))
    return out


def main():
    now = datetime.now(timezone.utc)
    # naive UTC-Cutoff, passend zu den geparsten naiven pubDate-Werten
    cutoff = (now - timedelta(days=2)).replace(tzinfo=None)
    print("DATENSTAND (Pre-Run-Script):", now.strftime("%Y-%m-%d %H:%M UTC"))

    for label, url in FEEDS.items():
        print(f"\n### {label} (nur letzte 2 Tage)")
        try:
            fresh = [i for i in parse_rss(fetch(url)) if i[2] and i[2] >= cutoff]
            if not fresh:
                print("- (keine Artikel der letzten 2 Tage in diesem Feed)")
            for t, src, ts in fresh:
                print(f"- [{ts:%Y-%m-%d %H:%M}] {t} ({src})")
        except Exception as e:
            print(f"- (FEHLER beim Abruf: {e})")

    print("\n### WETTER (Open-Meteo)")
    for name, lat, lon in WETTER_ORTE:
        try:
            d = json.loads(fetch(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto"))
            x = d["daily"]
            print(f"- {name}: {x['temperature_2m_min'][0]}..{x['temperature_2m_max'][0]} °C, "
                  f"{WMAP.get(x['weathercode'][0], '?')}, Regen {x['precipitation_probability_max'][0]}% heute | "
                  f"morgen bis {x['temperature_2m_max'][1]} °C, Regen {x['precipitation_probability_max'][1]}%")
        except Exception as e:
            print(f"- {name}: (FEHLER {e})")

    print("\n### WASSERTEMPERATUR (wassertemperatur.org)")
    for name, slug in WASSER_ORTE:
        try:
            raw = fetch(f"https://www.wassertemperatur.org/{slug}/").decode("utf-8", "replace")
            m = re.search(r"(\d{1,2}[.,]?\d*)\s*°C", raw)
            print(f"- {name}: {m.group(1).replace('.', ',')} °C" if m else f"- {name}: (kein Wert)")
        except Exception as e:
            print(f"- {name}: (FEHLER {e})")

    print("\nHINWEIS: Nur diese Rohdaten verwenden. Keine weiteren Befehle ausführen.")


if __name__ == "__main__":
    main()
