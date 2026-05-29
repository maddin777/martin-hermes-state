#!/usr/bin/env python3
"""
Watchlist Dedup — dedupliziert die watchlist-Tabelle auf zwei Ebenen:
  1. Ticker-basiert (gleicher Ticker → merge)
  2. Name-basiert (normalisierte Names → merge)

Konsolidiert Conviction, Mentions, Channels und droppt Duplikate.
Kann standalone oder als Cron (z.B. wöchentlich) laufen.
"""
import sqlite3, json, os, sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401

DB_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"

# ── Normalisierung (aus watchlist_manager.py übernommen) ──────────────

NORMALIZE_ALIASES = {
    "nvidia": "NVIDIA",
    "nvidia corporation": "NVIDIA", "nvidia corp.": "NVIDIA",
    "amd": "AMD",
    "advanced micro devices": "AMD",
    "ibm": "IBM",
    "intc": "Intel",
    "msft": "Microsoft",
    "meta platforms": "Meta", "meta platforms inc.": "Meta",
    "meta platforms, inc.": "Meta",
    "alphabet inc.": "Alphabet", "alphabet inc. (google)": "Alphabet",
    "micron technology": "Micron",
    "cerebras systems": "Cerebras", "cerebras systems inc.": "Cerebras",
    "take two interactive": "Take-Two Interactive",
    "take two interactive software": "Take-Two Interactive",
    "take-two interactive software": "Take-Two Interactive",
    "d-wave systems": "D-Wave Quantum", "d-wave systems inc.": "D-Wave Quantum",
    "jp morgan": "JPMorgan", "jp morgan chase": "JPMorgan",
    "jpmorgan chase": "JPMorgan",
    "berkshire hathaway inc.": "Berkshire Hathaway",
    "costco wholesale": "Costco", "costco wholesale corporation": "Costco",
    "amazon.com": "Amazon", "amazon.com inc.": "Amazon",
    "apple inc.": "Apple",
    "microsoft corporation": "Microsoft",
    "salesforce inc.": "Salesforce",
    "netflix inc.": "Netflix",
    "intuit inc.": "Intuit",
    "paypal holdings": "PayPal",
    "snowflake inc.": "Snowflake",
    "walmart inc.": "Walmart",
    "mcdonald's corporation": "McDonald's",
    "pepsico inc.": "PepsiCo",
    "coca-cola co.": "Coca-Cola",
    "palo alto networks": "Palo Alto",
    "sk hynix inc.": "SK Hynix",
    "softbank group": "SoftBank", "softbank group corp.": "SoftBank",
    "mara holdings": "MARA Holdings",
    "marathon digital holdings": "MARA Holdings",
    "marathon digital holdings inc.": "MARA Holdings",
    "rheinmetall ag": "Rheinmetall",
    "infineon technologies": "Infineon",
    "infineon technologies ag": "Infineon",
    "siemens ag": "Siemens",
    "basf se": "BASF",
    "bayer ag": "Bayer",
    "mercedes-benz group": "Mercedes-Benz",
    "adidas ag": "Adidas",
    "commerzbank ag": "Commerzbank",
    "deutsche bank ag": "Deutsche Bank",
    "delivery hero se": "Delivery Hero",
    "dws group gmbh & co. kgaa": "DWS",
    "henkel ag & co. kgaa": "Henkel",
    "münchener rück": "Münchner Rück", "munich re": "Münchner Rück",
    "united health": "UnitedHealth",
    "uber technologies": "Uber",
    "cisco systems": "Cisco",
    "mastercard inc.": "Mastercard",
    "visa inc.": "Visa",
    "booking holdings": "Booking Holdings",
    "taiwan semiconductor": "TSMC",
    "taiwan semiconductor manufacturing company": "TSMC",
    "taiwan semiconductor manufacturing company limited": "TSMC",
    "johnson & johnson (jnj)": "Johnson & Johnson",
    "linde plc": "Linde",
    "arm holdings plc": "ARM",
    "palantir technologies": "Palantir",
    "microstrategy incorporated": "MicroStrategy",
    "intuitive surgical": "Intuitive Surgical",
    "marvell technology": "Marvell",
    "marvell technology, inc.": "Marvell",
    "viking holdings ltd": "Viking Holdings",
    "schneider electric se": "Schneider Electric",
    "lvmh moët hennessy louis vuitton": "LVMH",
    "lvmh moet hennessy louis vuitton": "LVMH",
    "zaland se": "Zalando", "zalandos e": "Zalando",
    "by company": "BYD",
    "cisco": "Cisco",
    "nvidia corp.": "NVIDIA",
    "nubank": "NuBank",
    "n holdings": "Nu Holdings",
    "nu holdings": "Nu Holdings",
    "service now": "ServiceNow",
    "marvel": "Marvell",
    "strategy": "Strategy",
    "reddit, inc.": "Reddit, Inc.",
    "reddit inc.": "Reddit, Inc.",
    "hims & hers health": "Hims & Hers",
    "hilton worldwide holdings inc.": "Hilton Worldwide Holdings",
    "fiserv, inc. (fisv)": "Fiserv, Inc.",
    "fiserv, inc.": "Fiserv, Inc.",
    "deckers brands": "Deckers Outdoor",
    "domino's pizza": "Dominos Pizza",
    "exxon mobil": "Exxon",
    "gemini space station inc.": "Gemini Space",
    "watches of switzerland group plc": "Watches of Switzerland",
    "team, inc.": "Team",
    "sma solar technology ag": "SMA Solar Technology",
    "upstart holdings, inc. (upst)": "Upstart",
    "renk group ag": "Renk Group",
    "e.l.f. beauty": "e.l.f.",
    "wells fargo & company": "Wells Fargo",
    "under armour inc.": "Under Armour",
    "hyundai motor company": "Hyundai Motor",
    "vibra energia s.a.": "Vibra Energia",
    "standard chartered plc": "Standard Chartered",
    "standard chartered pl": "Standard Chartered",
    "samsung electronics": "Samsung",
    "vodafone group plc": "Vodafone",
    "novo nordisk a/s": "Novo Nordisk",
    "siltronic ag": "Siltronic",
    "nxp semiconductor": "NXP Semiconductors",
    "thyssenkrupp ag": "ThyssenKrupp",
    "rwe ag": "RWE",
    "qualcomm incorporated": "Qualcomm",
    "macy's": "Macy",
    "mtu": "MTU Aero Engines",
    "agilysys inc.": "Agilysys",
    "adobe inc.": "Adobe",
    "abn amro bank n.v.": "ABN AMRO Bank",
    "8x8, inc.": "8x8",
    "viking holdings ltd": "Viking Holdings",
    "hochtief ag": "Hochtief",
    "berkshire hathaway inc.": "Berkshire Hathaway",
    "hannover rück": "Hannover Rück",
    "3i group plc": "3i Group",
    "merck kgaa": "Merck",
    "hubspot, inc.": "HubSpot",
    "mercado libre": "MercadoLibre",
    "alibaba group": "Alibaba",
    "american water works": "American Water Works",
    "agnico eagle mines": "Agnico Eagle Mines",
    "allied gold corporation": "Allied Gold",
    "amer sports inc.": "Amer Sports",
    "americas gold and silver corporation": "Americas Gold and Silver",
    "altria group, inc.": "Altria",
    "kingsoft corporation": "Kingsoft",
    "agco corporation": "AGCO",
    "asml holding": "ASML",
    "vinci sa": "Vinci",
    "bae systems plc": "BAE Systems",
    "bechtle ag": "Bechtle",
    "essity ab": "Essity",
    "ge aerospace": "GE Aerospace",
    "gsk plc": "GSK",
    "innoviz technologies": "Innoviz",
    "nibe industrier ab": "Nibe Industrier",
    "telefonica sa": "Telefónica",
    "uniper se": "Uniper",
    "vestas wind systems a/s": "Vestas",
    "volvo ab": "Volvo",
    "weir group plc": "Weir Group",
    "american tower corporation": "American Tower",
    "astrazeneca plc": "AstraZeneca",
    "atlas copco ab": "Atlas Copco",
}


def normalize_company_name(name):
    """Normalisiert einen Namen für Duplikat-Vergleiche."""
    import re
    n = name.strip()
    # Klammer-Notizen entfernen
    n = re.sub(r"\s*\((?:nicht\s+börsennotiert|Marke\s+von[^)]*|privat[^)]*|Teil\s+von[^)]*)\)\s*$", "", n, flags=re.IGNORECASE)
    n = re.sub(r"\s*\([^)]*[?][^)]*\)\s*$", " ", n)
    # Legal-Suffixe entfernen
    legal_re = re.compile(
        r"(?:\s*[,/]\s*)?"
        r"(?:AG(?:\s+&?\s*Co\.?\s*(?:KGaA|KG|OHG))?"
        r"|SE|GmbH(?:\s*&\s*Co\.?\s*(?:KG|KGaA|OHG))?"
        r"|PLC|plc|Inc\.|Inc|Corporation|Corp\.?|Corp"
        r"|Ltd\.?|Limited|LLC|LLP|LP|NV|N\.V\.|SA|S\.A\.|AB|OY"
        r"|S\.p\.A\.|Sp\.? z\.?o\.?o\.?|JSC|PJSC|OJSC"
        r"|Holdings?|Group|Co\.|Company"
        r"|Class\s+[ABCDE]|Common\s+Stock"
        r")(?:\.|\s)*$",
        re.IGNORECASE
    )
    prev = None
    while prev != n:
        prev = n
        n = legal_re.sub("", n).strip()
    n = re.sub(r"^The\s+", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    lower = n.lower()
    if lower in NORMALIZE_ALIASES:
        return NORMALIZE_ALIASES[lower]
    return n


# ── Merge-Logik ───────────────────────────────────────────────────────

MERGE_COLS = ["mention_count", "bullish_count", "bearish_count",
              "neutral_count", "conviction_score", "conviction_score_bear"]


def merge_group(con, rows, key, key_label):
    """Merge eine Gruppe von Duplikaten in einen kanonischen Eintrag.
    rows: Liste von sqlite3.Row-Dicts (alle mit status='watching')
    key: Beschriftung für Logging
    """
    if len(rows) <= 1:
        return 0

    # 1. Kanonischen Namen bestimmen
    names = [r["name"] for r in rows]
    # Bevorzuge kürzesten Namen der NICHT auf legal-Suffix endet
    canon = min(names, key=lambda n: (
        len(n) if not any(n.lower().endswith(s) for s in
                          ["inc", "inc.", "corp", "corp.", "ltd", "ltd.", "ag",
                           "se", "plc", "llc", "gmbh", "nv", "sa", "ab", "oy",
                           "holdings", "group", "plc", "co.", "company"])
        else len(n) + 1000,  # penalize suffixed names
        names.index(n)  # tie-breaker: first appearance
    ))
    # Nochmal check: falls ein Name den normalisierten Namen exakt matcht, den nehmen
    norm = normalize_company_name(canon)
    for n in names:
        if n.lower() == norm.lower():
            canon = n
            break

    # 2. Stats aggregieren
    merged = {}
    for col in MERGE_COLS:
        merged[col] = sum(r[col] or 0 for r in rows)

    # Channels: union aller Channels
    all_channels = set()
    for r in rows:
        chans = json.loads(r["channels"]) if r["channels"] else []
        all_channels.update(chans)
    merged["channels"] = json.dumps(sorted(all_channels))

    # Date range: earliest first_seen, latest last_seen
    merged["first_seen"] = min(r["first_seen"] for r in rows if r["first_seen"])
    merged["last_seen"]  = max(r["last_seen"] for r in rows if r["last_seen"])

    # Ticker: prefer the one that actually resolves (not a weird alternative)
    tickers = [r["ticker"] for r in rows if r["ticker"]]
    merged["ticker"] = tickers[0] if tickers else None

    # Sector: von canonical row übernehmen falls vorhanden, sonst first non-None
    canon_row = next((r for r in rows if r["name"] == canon), rows[0])
    merged["sector"] = canon_row["sector"] or "Other"

    # 3. Canonical Eintrag updaten
    set_parts = []
    params = []
    for col in MERGE_COLS + ["channels", "first_seen", "last_seen", "ticker", "sector"]:
        set_parts.append(f"{col}=?")
        params.append(merged[col])
    set_parts.append("status=?")
    params.append("watching")
    params.append(canon)

    con.execute(f"UPDATE watchlist SET {', '.join(set_parts)} WHERE name=?", params)

    # 4. Duplikate droppen
    dropped = 0
    for r in rows:
        if r["name"] == canon:
            continue
        con.execute(
            "UPDATE watchlist SET status='dropped', notes=? WHERE name=?",
            (f"merged into '{canon}' (watchlist_dedup)", r["name"])
        )
        dropped += 1

    print(f"  🔗 {len(rows)} → '{canon}'  ({key_label}: {key})  "
          f"Conv:{merged['conviction_score']:.2f} Mentions:{merged['mention_count']} "
          f"Dropped:{dropped}", flush=True)
    return dropped


# ── Hauptlogik ────────────────────────────────────────────────────────

def dedup_ticker(con):
    """Phase 1: Gleicher Ticker → merge."""
    rows = con.execute("""
        SELECT * FROM watchlist
        WHERE status='watching' AND ticker IS NOT NULL
        ORDER BY ticker, mention_count DESC
    """).fetchall()
    groups = {}
    for r in rows:
        t = r["ticker"].strip().upper()
        groups.setdefault(t, []).append(r)
    total = 0
    for ticker, group in groups.items():
        total += merge_group(con, group, ticker, "ticker")
    con.commit()
    return total


def dedup_name(con):
    """Phase 2: Normalisierter Name → merge (für Einträge OHNE Ticker)."""
    rows = con.execute("""
        SELECT * FROM watchlist
        WHERE status='watching' AND ticker IS NULL
        ORDER BY mention_count DESC
    """).fetchall()
    groups = {}
    for r in rows:
        norm = normalize_company_name(r["name"]).lower()
        groups.setdefault(norm, []).append(r)
    total = 0
    for norm, group in groups.items():
        if len(group) <= 1:
            continue
        total += merge_group(con, group, norm[:40], "name")
    con.commit()
    return total


def dedup_ticker_variants(con):
    """
    Phase 3: Einträge mit unterschiedlichen Tickern, die aber die gleiche
    Firma repräsentieren (z.B. NVDA + NVD.DE, SAP.DE + SAP).
    Nur konkrete bekannte Varianten mergen.
    """
    # Manuelle Paare von tickern die die gleiche Firma sind
    TICKER_GROUPS = {
        "NVDA": ["NVDA", "NVD.DE", "NVD.F"],
        "META": ["META"],
        "GOOGL": ["GOOGL", "GOOG", "ABEA.F"],
        "AMZN": ["AMZN"],
        "MSFT": ["MSFT"],
        "AAPL": ["AAPL"],
        "SAP.DE": ["SAP.DE", "SAP"],
        "IFX.DE": ["IFX.DE"],
        "MTX.DE": ["MTX.DE"],
        "SIE.DE": ["SIE.DE"],
        "ALV.DE": ["ALV.DE"],
        "CBK.DE": ["CBK.DE"],
        "DBK.DE": ["DBK.DE"],
        "BAYN.DE": ["BAYN.DE"],
        "BAS.DE": ["BAS.DE"],
        "TTWO": ["TTWO"],
        "PLTR": ["PLTR"],
        "AMD": ["AMD"],
        "INTC": ["INTC"],
        "QCOM": ["QCOM"],
        "MSTR": ["MSTR"],
        "CRWD": ["CRWD"],
        "NU": ["NU"],
        "UBER": ["UBER"],
    }
    total = 0
    for canonical_ticker, variants in TICKER_GROUPS.items():
        if len(variants) <= 1:
            continue
        rows = con.execute("""
            SELECT * FROM watchlist
            WHERE status='watching' AND ticker IN ({})
            ORDER BY mention_count DESC
        """.format(",".join("?" for _ in variants)), variants).fetchall()
        if len(rows) <= 1:
            continue
        # Ticker auf canonical setzen vor merge
        for r in rows:
            if r["ticker"] != canonical_ticker:
                con.execute("UPDATE watchlist SET ticker=? WHERE name=?", (canonical_ticker, r["name"]))
        con.commit()
        # Erneutes Laden mit einheitlichem Ticker
        rows = con.execute("""
            SELECT * FROM watchlist
            WHERE status='watching' AND ticker=?
            ORDER BY mention_count DESC
        """, (canonical_ticker,)).fetchall()
        if len(rows) > 1:
            total += merge_group(con, rows, canonical_ticker, "ticker-variant")
    con.commit()
    return total


def main():
    print("🧹 Watchlist Dedup gestartet", flush=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Bestand vorher
    before = con.execute(
        "SELECT COUNT(*) FROM watchlist WHERE status='watching'"
    ).fetchone()[0]

    print(f"  Vorher: {before} watching entries", flush=True)

    total = 0
    total += dedup_ticker_variants(con)  # erst ticker-varianten angleichen
    total += dedup_ticker(con)           # dann ticker-basiert mergen
    total += dedup_name(con)             # dann name-basiert (ohne ticker)

    # Nachher
    after = con.execute(
        "SELECT COUNT(*) FROM watchlist WHERE status='watching'"
    ).fetchone()[0]
    still_watching = after

    print(f"\n  Ergebnis: {before} → {after} watching  (-{before - after})", flush=True)
    print(f"  🗑 {total} Duplikate gedroppt", flush=True)

    # Unresolved ticker report
    unresolved = con.execute("""
        SELECT name, mention_count, conviction_score
        FROM watchlist
        WHERE status='watching' AND ticker IS NULL
        ORDER BY mention_count DESC LIMIT 15
    """).fetchall()
    if unresolved:
        print(f"\n❓ Noch {len(unresolved)} watching ohne Ticker:", flush=True)
        for u in unresolved:
            print(f"   {u['name']:30} {u['mention_count']:4}x  Conv:{u['conviction_score']:.2f}", flush=True)

    # Top 3 merge groups report
    print(f"\n  Noch {still_watching} watching entries in Watchlist", flush=True)
    print("✅ Watchlist Dedup abgeschlossen", flush=True)

    con.close()


if __name__ == "__main__":
    main()