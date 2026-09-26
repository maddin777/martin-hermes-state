#!/usr/bin/env python3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import json

today = datetime.now(timezone.utc)
cutoff = today - timedelta(days=2)
cutoff_str = cutoff.strftime("%Y-%m-%d")

feeds = {
    "top": "/tmp/google_news_top.xml",
    "finance": "/tmp/google_news_finance.xml",
    "tech": "/tmp/google_news_tech.xml",
    "nord": "/tmp/google_news_nord.xml"
}

all_items = {}
categories = {
    "politics": [],
    "finance": [],
    "tech": [],
    "nord": [],
    "other": []
}

for name, path in feeds.items():
    items_out = []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        items = root.findall('.//item')
        for item in items:
            title = item.find('title')
            pubdate = item.find('pubDate')
            source = item.find('source')
            link = item.find('link')
            desc = item.find('description')
            
            if title is None or title.text is None:
                continue
            
            # Parse pubDate
            dt = None
            if pubdate is not None and pubdate.text:
                try:
                    dt = datetime.strptime(pubdate.text.strip(), "%a, %d %b %Y %H:%M:%S %Z")
                    dt = dt.replace(tzinfo=timezone.utc)
                except:
                    try:
                        dt = datetime.strptime(pubdate.text.strip(), "%a, %d %b %Y %H:%M:%S %z")
                    except:
                        pass
            
            if dt is not None and dt < cutoff:
                continue
            
            src = source.text if source is not None and source.text else ""
            lnk = link.text if link is not None and link.text else ""
            dsc = desc.text if desc is not None and desc.text else ""
            
            date_str = dt.strftime("%d.%m.") if dt else "heute"
            
            items_out.append({
                "title": title.text.strip(),
                "source": src.strip(),
                "link": lnk.strip(),
                "desc": dsc.strip()[:300],
                "date": date_str,
                "dt": dt.isoformat() if dt else None
            })
    except Exception as e:
        print(f"Fehler bei {name}: {e}")
    
    all_items[name] = items_out
    print(f"\n=== {name.upper()} ===")
    print(f"{len(items_out)} aktuelle Artikel (ab {cutoff_str})")
    for it in items_out:
        print(f"  [{it['date']}] {it['title']} ({it['source']})")

# Also parse weather
print("\n\n=== WEATHER RATZEBURG ===")
with open("/tmp/weather_ratzeburg.json") as f:
    w = json.load(f)
    d = w.get('daily', {})
    if d:
        for i in range(min(3, len(d.get('temperature_2m_max', [])))):
            print(f"  Tag {i}: Max {d['temperature_2m_max'][i]}°C, Min {d['temperature_2m_min'][i]}°C, Regen {d['precipitation_probability_max'][i]}%, Code {d['weathercode'][i]}")

print("\n=== WEATHER SCHWERIN ===")
with open("/tmp/weather_schwerin.json") as f:
    w = json.load(f)
    d = w.get('daily', {})
    if d:
        for i in range(min(3, len(d.get('temperature_2m_max', [])))):
            print(f"  Tag {i}: Max {d['temperature_2m_max'][i]}°C, Min {d['temperature_2m_min'][i]}°C, Regen {d['precipitation_probability_max'][i]}%, Code {d['weathercode'][i]}")