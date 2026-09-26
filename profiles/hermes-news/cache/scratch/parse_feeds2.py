#!/usr/bin/env python3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

today = datetime.now(timezone.utc)
cutoff = today - timedelta(days=2)

def parse_feed(path, label):
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
            
            if title is None or title.text is None:
                continue
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
            date_str = dt.strftime("%d.%m.") if dt else "heute"
            items_out.append({"title": title.text.strip(), "source": src.strip(), "link": lnk.strip(), "date": date_str})
    except Exception as e:
        print(f"Fehler {label}: {e}")
    print(f"\n=== {label} ===")
    for it in items_out:
        print(f"  [{it['date']}] {it['title']} ({it['source']})")
    return items_out

tech = parse_feed("/tmp/google_news_tech2.xml", "TECH2")
fin = parse_feed("/tmp/google_news_finance2.xml", "FINANCE2")