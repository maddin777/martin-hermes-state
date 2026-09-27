#!/usr/bin/env python3
"""Pre-run data gatherer for daily-news-briefing cron job.
Fetches fresh news, weather and water temperatures OUTSIDE the agent loop and
prints structured markdown that gets injected into the cron agent's prompt.
The agent only formats/Categorizes — it must NOT run terminal commands.
"""
import urllib.request, json, re, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HDR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=HDR)
    return urllib.request.urlopen(req, timeout=timeout).read()

def parse_rss(raw, n=14):
    root = ET.fromstring(raw)
    out = []
    for it in root.findall('.//item')[:n]:
        t = it.find('title'); s = it.find('source'); d = it.find('pubDate')
        src = s.text if s is not None else ''
        ts = None
        try:
            ts = datetime.strptime(d.text, '%a, %d %b %Y %H:%M:%S %Z')
        except Exception:
            pass
        out.append((t.text if t is not None else '', src, ts))
    return out

def fmt_date(ts):
    if not ts: return '?'
    return ts.strftime('%Y-%m-%d %H:%M')

def main():
    now = datetime.now(timezone.utc)
    print("DATENSTAND (abgerufen vom Pre-Run-Script):", now.strftime('%Y-%m-%d %H:%M UTC'))
    print("=" * 60)

    today = now.strftime('%Y-%m-%d')
    cutoff = (now - timedelta(days=2)).replace(tzinfo=None)  # naive, passend zu geparsten mit %Z

    feeds = {
        "TOP-NACHRICHTEN (alle Themen)": "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de",
        "POLITIK & INTERNATIONAL": "https://news.google.com/rss/search?q=Politik+USA+Ukraine+EU+China+Wahl&hl=de&gl=DE&ceid=DE:de",
        "FINANZEN & WIRTSCHAFT": "https://news.google.com/rss/search?q=DAX+B%C3%B6rse+Gold+Bitcoin+%C3%96lpreis&hl=de&gl=DE&ceid=DE:de",
        "IT & KI": "https://news.google.com/rss/search?q=KI+Artificial+Intelligence+Tech&hl=de&gl=DE&ceid=DE:de",
        "DEUTSCHLAND & NORDEUROPA": "https://news.google.com/rss/search?q=Schleswig-Holstein+Mecklenburg-Vorpommern+Deutschland+Wahl&hl=de&gl=DE&ceid=DE:de",
    }
    for label, url in feeds.items():
        print(f"\n### {label} (aktuellste, 2-Tage-Filter)")
        try:
            items = parse_rss(fetch(url))
            fresh = [i for i in items if i[2] and i[2] >= cutoff]
            # Nur frische Artikel zeigen — niemals veraltete als Fallback (Preis-/Fakten-Regel).
            if not fresh:
                print("- (keine Artikel der letzten 2 Tage in diesem Feed)")
            else:
                for t, src, ts in fresh:
                    print(f"- [{fmt_date(ts)}] {t} ({src})")
        except Exception as e:
            print(f"- (FEHLER beim Abruf: {e})")

    # Weather
    print("\n### WETTER (Open-Meteo, heute + morgen)")
    for name, lat, lon in [("Ratzeburg", 53.70, 10.75), ("Schwerin", 53.63, 11.41)]:
        try:
            d = json.loads(fetch(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=auto"))
            d2 = d['daily']
            wc = d2['weathercode'][0]
            wmap = {0:"klar",1:"leicht bewölkt",2:"teils bewölkt",3:"bewölkt",45:"Nebel",48:"Nebel",
                    51:"Sprühregen",53:"Sprühregen",61:"Regen",63:"Regen",65:"starker Regen",80:"Schauer",95:"Gewitter"}
            print(f"- {name}: {d2['temperature_2m_min'][0]}..{d2['temperature_2m_max'][0]}°C, "
                  f"{wmap.get(wc,'?')}, Regen {d2['precipitation_probability_max'][0]}% "
                  f"(heute) | morgen bis {d2['temperature_2m_max'][1]}°C, Regen {d2['precipitation_probability_max'][1]}%")
        except Exception as e:
            print(f"- {name}: (FEHLER {e})")

    # Water temperatures
    print("\n### WASSERTEMPERATUR (wassertemperatur.org)")
    for name, slug in [("Ostsee Luebeck/Trave", "ostsee/luebeck"), ("Ostsee Wismar", "ostsee/wismar"),
                       ("Ostsee Rostock", "ostsee/rostock"), ("Schweriner See", "schweriner-see")]:
        try:
            raw = fetch(f"https://www.wassertemperatur.org/{slug}/").decode('utf-8', 'replace')
            m = re.search(r'(\d{1,2}[.,]?\d*)\s*°C', raw)
            print(f"- {name}: {m.group(1).replace('.',',')} °C" if m else f"- {name}: (kein Wert)")
        except Exception as e:
            print(f"- {name}: (FEHLER {e})")

    print("\nHINWEIS: Dies sind die Rohdaten. Erstelle daraus das Briefing in 5 Sektionen "
          "(Politik, Finanzen, IT/KI, Deutschland/Nordeuropa, Wetter/Wasser), max 5 Items, "
          "alle Quellen angeben, nur Daten von 2 Tagen. Führe KEINE weiteren Terminal-Befehle aus — "
          "alle Daten sind hier.")

if __name__ == "__main__":
    main()
