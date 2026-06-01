"""
Script 3: Technical Validator
- Löst Unternehmensnamen → Ticker auf (yfinance)
- Prüft DE und US Börsen
- Berechnet Confluence Score (EMA, RSI, MACD, Volumen, ADX)
- Filtert ungültige Unternehmen raus
- Schreibt validierte Signale in trading_signals_validated.json
"""
import json
import os
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import sqlite3
from pathlib import Path
# get_technical_score() zentral aus utils (DRY – war lokale Kopie)
import sys as _sys
_sys.path.insert(0, '/root/.hermes/profiles/hermes_trading/skills/trading/scripts')
from utils import get_technical_score  # noqa: E402


# Bekannte Mappings für häufige deutsche Unternehmen
KNOWN_TICKERS = {
    "allianz": "ALV.DE", "sap": "SAP.DE", "siemens": "SIE.DE",
    "siemens energy": "ENR.DE", "deutsche bank": "DBK.DE",
    "commerzbank": "CBK.DE", "volkswagen": "VOW3.DE", "vw": "VOW3.DE",
    "bmw": "BMW.DE", "mercedes": "MBG.DE", "mercedes-benz": "MBG.DE",
    "bas": "BAS.DE", "bayer": "BAYN.DE", "adidas": "ADS.DE",
    "daimler truck": "DTG.DE", "mtu aero engines": "MTX.DE",
    "mtu": "MTX.DE", "infineon": "IFX.DE",
    "deutsche telekom": "DTE.DE", "telekom": "DTE.DE",
    "e.on": "EOAN.DE", "eon": "EOAN.DE", "rwe": "RWE.DE",
    "hannover re": "HNR1.DE", "munich re": "MUV2.DE",
    "münchener rück": "MUV2.DE", "fresenius": "FRE.DE",
    "continental": "CON.DE", "henkel": "HEN3.DE",
    "sartorius": "SRT3.DE", "zalando": "ZAL.DE", "delivery hero": "DHER.DE",
    "hellofresh": "HFG.DE", "teamviewer": "TMV.DE",
    "scout24": "G24.DE",
    "unicredit": "UCG.MI", "deutsche pfandbriefbank": "PBB.DE",
    "redcare pharmacy": "RDC.DE",
    "sgl carbon": "SGL.DE",
    # US
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL",
    "alphabet": "GOOGL", "amazon": "AMZN", "meta": "META",
    "nvidia": "NVDA", "tesla": "TSLA", "netflix": "NFLX",
    "adobe": "ADBE", "intel": "INTC", "nike": "NKE",
    "unitedhealth": "UNH", "johnson & johnson": "JNJ",
    "eli lilly": "LLY", "gilead sciences": "GILD",
    "broadcom": "AVGO", "ibm": "IBM", "ionq": "IONQ",
    "halliburton": "HAL", "american airlines": "AAL",
    "united airlines": "UAL", "brown forman": "BF-B",
    "pernod ricard": "RI.PA", "figma": None,
    "openai": None, "anthropic": None,
    # --- FIXES für Fehlauflösungen (verified gegen Yahoo, 2026-05-28) ---
    "hp":              "HPQ",      # HP Inc. (PC/Drucker); NICHT HP=Helmerich&Payne, NICHT HPE=HP Enterprise
    "hp inc":          "HPQ",
    "hp inc.":         "HPQ",
    "hpq":             "HPQ",
    "intuit":          "INTU",     # NICHT ISRG (Intuitive Surgical)
    "salesforce":      "CRM",      # NICHT 3CRE.DE / FOO0.MU (DE-Fonds)
    "salesforce.com":  "CRM",
    "barrick":         "B",        # Barrick Mining, neuer NYSE-Ticker seit Umbenennung
    "barrick gold":    "B",        # alter Firmenname, gleicher Ticker
    "barrick mining":  "B",
    "tsmc":            "TSM",      # NICHT TSMC34.SA (Brasilien-BDR)
    "taiwan semiconductor":            "TSM",
    "taiwan semiconductor manufacturing": "TSM",
    "itaú":            "ITUB",     # mit Akzent
    "itau":            "ITUB",     # ohne Akzent
    "itau unibanco":   "ITUB",
    "itaú unibanco":   "ITUB",
    "at&s":            "ATS.VI",   # österreichische Leiterplatten, NICHT A1Q.F (Insurance)
    "at & s":          "ATS.VI",
    # --- Cross-Exchange Mappings (verified gegen Yahoo, 2026-05-28) ---
    # US-Hauptlisting bevorzugt; verhindert dass yfinance EU-Mirrors waehlt
    "alphabet":            "GOOGL",   # statt ABEA.F (Frankfurt-Mirror)
    "apple":               "AAPL",    # statt APC.DE
    "blackstone":          "BX",      # statt BBN1.F
    "doordash":            "DASH",    # statt DD2.MU
    "hsbc":                "HSBC",    # statt HSBA.L (London) — US-ADR
    "intel":               "INTC",    # statt INL.DE
    "marvell":             "MRVL",    # statt 9MW.MU
    "marvell technology":  "MRVL",
    "microsoft":           "MSFT",    # statt MSF.DE
    "netflix":             "NFLX",    # statt NFC1.MU
    "s&p global":          "SPGI",    # statt MHL.F
    "sp global":           "SPGI",
    "schlumberger":        "SLB",     # statt SCL.MU
    "tesla":               "TSLA",    # statt TL0.F
    "ubs":                 "UBS",     # statt 0UB.F
    # Sonderfaelle (kein US-Listing): Heimatboerse statt obskurer Mirror
    "airbus":              "AIR.PA",  # Paris-Heimat, statt AIR.DE oder anderem
    "sma solar":           "S92.DE",  # XETRA-Heimat, statt 1S.MI oder S92D.XC
    "sma solar technology":"S92.DE",
    # --- Cross-Exchange Mappings Runde 2 (verified, 2026-05-28) ---
    "coreweave":         "CRWV",     # statt I1V.F
    "costco":            "COST",     # statt CTO.DE
    "costco wholesale":  "COST",
    "moody's":           "MCO",      # statt DUT.MU
    "moodys":            "MCO",      # ohne Apostroph
    "xiaomi":            "1810.HK",  # Hong Kong = Heimat, kein US-Listing
    # --- Cross-Exchange Mappings Runde 3 (verified, 2026-05-28) ---
    "micron":                 "MU",     # statt MTE.SG
    "micron technology":      "MU",
    "constellation energy":   "CEG",    # statt E7S.F / E7S.SG (NYSE-Hauptlisting)
    # Heidelberg-Disambiguation (HEI ≠ HDD, zwei verschiedene Firmen)
    "heidelberg materials":  "HEI.DE",
    "heidelbergcement":      "HEI.DE",
    "heidelberger druck":    "HDD.DE",
    "heidelberger druckmaschinen": "HDD.DE",
    # DocMorris Heimatboerse (UK-Listing 0QT.L ist 404)
    "doc morris":            "DOCM.SW",
    "docmorris":             "DOCM.SW",
    # compugroup: 2024 von CVC uebernommen, delisted -> raus
}

# Indizes, Krypto, ETFs, Newsletter-/Depot-Namen — nicht handelbar als Einzelaktie
import re
from config import DB_PATH, SIGNALS_PATH, SIGNALS_VALIDATED_PATH

_NOT_TRADABLE_PATTERNS = [
    # Indizes
    r'\b(DAX|MDAX|SDAX|TecDAX)\b',
    r'\bS&P\s*\d+\b', r'\bSP\s*500\b',
    r'\bDow\s*Jones\b', r'\bDJIA\b',
    r'\bNASDAQ\s*(Composite|100)?\b',
    r'\bRussell\s*\d+\b',
    r'\bMSCI\b',                # MSCI als Index ODER als Firma (mehrdeutig — bewusst filtern)
    r'\bFTSE\b', r'\bSTOXX\b', r'\bEuro\s*Stoxx\b',
    r'\bNikkei\b', r'\bHang\s*Seng\b',
    r'\bCAC\s*40\b', r'\bIBEX\b',
    # Krypto (Coins, nicht Krypto-Aktien)
    r'\b(BTC|ETH|XRP|SOL|ADA|DOGE|USDT|USDC|BNB|MATIC|DOT|AVAX)\b',
    r'\bBitcoin\b(?!\s+(Mining|Group|Holdings))',   # erlaubt 'Bitcoin Mining Corp' etc.
    r'\bEthereum\b(?!\s+(Mining|Classic))',
    r'\bRipple\b', r'\bSolana\b', r'\bCardano\b', r'\bDogecoin\b',
    # ETFs / Fondsstrukturen
    r'\bSPDR\b', r'\biShares\b', r'\bVanguard\s+(ETF|Index|Fund)',
    r'\bETF\s*Trust\b',
    # Newsletter-/Depot-Namen (sieht aus wie kein Unternehmen)
    r'M\u00e4rkte und Trends Depot',
]
_NOT_TRADABLE_RE = re.compile('|'.join(_NOT_TRADABLE_PATTERNS), re.IGNORECASE)

def _load_ticker_cache():
    """
    Laedt company_aliases aus DB in Memory-Dict.
    Bei Fehler (DB unreachable): fallback auf hardcoded KNOWN_TICKERS.
    """
    if not Path(DB_PATH).is_file():
        print(f"[resolve_ticker] WARN: DB nicht gefunden, nutze hardcoded KNOWN_TICKERS", flush=True)
        return dict(KNOWN_TICKERS)

    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT a.alias, a.ticker, c.status
            FROM company_aliases a
            JOIN companies c ON c.ticker = a.ticker
        """)
        rows = cur.fetchall()
        con.close()

        cache = {}
        for alias, ticker, status in rows:
            # private companies -> None (wie im alten KNOWN_TICKERS)
            cache[alias] = None if status == 'private' else ticker
        return cache
    except Exception as e:
        print(f"[resolve_ticker] WARN: DB-Lookup fehlgeschlagen ({e}), Fallback auf KNOWN_TICKERS", flush=True)
        return dict(KNOWN_TICKERS)


# Beim Modul-Import einmal laden
_TICKER_CACHE = _load_ticker_cache()


def is_tradable(name: str) -> bool:
    """Filtert Indizes, Krypto-Coins, ETFs und Newsletter-Namen aus."""
    if not name or not name.strip():
        return False
    return _NOT_TRADABLE_RE.search(name) is None


# Suffix-Stripping fuer KNOWN_TICKERS Lookup
# WICHTIG: nur als Fallback, NACHDEM der volle Name nicht gematcht hat.
# So bleiben Sonderfaelle wie "Siemens Energy" -> ENR.DE intakt
# (statt zu "siemens" gestrippt zu werden und auf SIE.DE zu kollidieren).
_LEGAL_SUFFIXES_RE = re.compile(
    r'[,\s]+(?:'
    # Rechtsformen
    r'inc\.?|incorporated|corp\.?|corporation|'
    r'ag|se|plc|ltd\.?|limited|kgaa|gmbh|'
    r's\.?\s*a\.?|s\.?\s*p\.?\s*a\.?|n\.?\s*v\.?|'
    r'co\.?\s*,?\s*ltd\.?|co\.?\s*kgaa|'
    # Generische Firmen-Suffixe (sicher, weil Schutz durch Volltext-Match steht)
    r'group|holdings?|company|technology|technologies|systems|'
    r'motor company'
    r')\s*$',
    re.IGNORECASE
)

def _strip_suffixes(name: str) -> str:
    """Schneidet iterativ rechtliche/generische Suffixe ab. 'Apple Inc.' -> 'apple'."""
    prev = None
    cur = name.lower().strip()
    while prev != cur:
        prev = cur
        cur = _LEGAL_SUFFIXES_RE.sub('', cur).strip(' ,.')
    return cur


def resolve_ticker(company_name):
    """Löst Unternehmensnamen zu Ticker auf.

    Lookup-Reihenfolge:
    1. Voller Name in KNOWN_TICKERS  (schuetzt 'siemens energy' vor Kollision mit 'siemens')
    2. Suffix-gestrippter Name in KNOWN_TICKERS  (faengt 'Apple Inc.' -> 'apple')
    3. Yahoo-Suche (yf.Search), bevorzugt DE-Boersen
    """
    key = company_name.lower().strip()

    # 1. Voller Name
    if key in _TICKER_CACHE:
        return _TICKER_CACHE[key]

    # 2. Suffix-Stripping Fallback
    stripped = _strip_suffixes(key)
    if stripped and stripped != key and stripped in _TICKER_CACHE:
        return _TICKER_CACHE[stripped]

    # 3. Yahoo-Suche
    try:
        results = yf.Search(company_name, max_results=3)
        quotes = results.quotes
        if quotes:
            for q in quotes:
                if q.get("exchange") in ("GER", "XETRA", "FRA", "STU", "MUN"):
                    return q.get("symbol")
            return quotes[0].get("symbol")
    except Exception:
        pass
    return None

# get_technical_score() wurde nach utils.py ausgelagert (DRY).
# Import steht oben: from utils import get_technical_score

def main():
    with open(SIGNALS_PATH, encoding="utf-8") as f:
        signals = json.load(f)

    # === PHASE 1: Sammeln aller Kandidaten ===
    all_candidates = []
    for signal in signals:
        for company in signal.get("companies", []):
            all_candidates.append({
                "company":        company,
                "source":         signal["source"],
                "market_outlook": signal.get("market_outlook"),
            })
    print(f"Kandidaten gesamt: {len(all_candidates)}", flush=True)

    # === PHASE 2: Filter (Indizes/Krypto/ETFs) + Vor-Dedup nach Name ===
    by_name = {}     # normalized_name -> list of candidates
    filtered_count = 0
    for c in all_candidates:
        name = c["company"]["name"]
        if not is_tradable(name):
            filtered_count += 1
            continue
        key = name.lower().strip()
        by_name.setdefault(key, []).append(c)

    if filtered_count:
        print(f"Gefiltert (Indizes/Krypto/ETFs): {filtered_count}", flush=True)
    print(f"Unique Namen: {len(by_name)}", flush=True)

    # === PHASE 3: Ticker-Auflösung pro unique Name ===
    print(f"\n--- Ticker-Auflösung ---", flush=True)
    by_ticker = {}   # ticker -> list of candidates (alle Namensvarianten zusammen)
    unresolved = 0
    for nkey, candidates in by_name.items():
        # nimm den längsten Namen aus der Gruppe als Display-Repräsentant
        rep_name = max((c["company"]["name"] for c in candidates), key=len)
        ticker = resolve_ticker(rep_name)
        if not ticker:
            unresolved += 1
            continue
        by_ticker.setdefault(ticker, []).extend(candidates)

    print(f"Unique Ticker: {len(by_ticker)} | Nicht aufgelöst: {unresolved}", flush=True)

    # === PHASE 4: Technical-Score pro Ticker (1x statt N-mal) ===
    print(f"\n--- Technical Analysis ---", flush=True)
    results = []
    for ticker, candidates in by_ticker.items():
        # Längster/vollständigster Name als Anzeige
        rep_name = max((c["company"]["name"] for c in candidates), key=len)
        mentions = len(candidates)

        if mentions > 1:
            print(f"\n[{rep_name}] (× {mentions} Mentions)", flush=True)
        else:
            print(f"\n[{rep_name}]", flush=True)
        print(f"  → Ticker: {ticker}", flush=True)

        tech = get_technical_score(ticker)
        if not tech:
            print("  ✗ Keine Kursdaten – überspringe", flush=True)
            continue

        print(f"  → Score: {tech['score']}/{tech['max_score']} "
              f"| Confidence: {tech['confidence']} "
              f"| {tech['direction']}", flush=True)

        # === PHASE 5: Aggregation der Metadaten über alle Mentions ===
        # Sources sammeln (unique nach video_id, Reihenfolge stabil)
        sources_seen, sources_list = set(), []
        for c in candidates:
            s = c.get("source")
            if not s:
                continue
            # Eindeutiger Schluessel: video_id wenn dict, sonst Fallback auf String-Repr
            sid = s.get("video_id") if isinstance(s, dict) else str(s)
            if sid and sid not in sources_seen:
                sources_seen.add(sid)
                sources_list.append(s)

        # Eintrag mit höchster strength als Repräsentant für Sentiment-Metadaten
        def _strength_val(c):
            v = c["company"].get("strength")
            try: return float(v) if v is not None else -1
            except (TypeError, ValueError): return -1
        top = max(candidates, key=_strength_val)
        top_comp = top["company"]

        # Alle Reasons sammeln (unique)
        reasons_seen, reasons_list = set(), []
        for c in candidates:
            r = c["company"].get("reason")
            if r and r not in reasons_seen:
                reasons_seen.add(r)
                reasons_list.append(r)

        # Ersten nicht-null Preis/Target nehmen
        def _first_nonnull(field):
            for c in candidates:
                v = c["company"].get(field)
                if v is not None:
                    return v
            return None

        results.append({
            "name":            rep_name,
            "ticker":          ticker,
            "mentions":        mentions,
            "sentiment":       top_comp.get("sentiment"),
            "strength":        top_comp.get("strength"),
            "action_hint":     top_comp.get("action_hint"),
            "reason":          reasons_list[0] if reasons_list else None,
            "all_reasons":     reasons_list,
            "mentioned_price": _first_nonnull("mentioned_price"),
            "price_target":    _first_nonnull("price_target"),
            "technical":       tech,
            "sources":         sources_list,
            "source":          sources_list[0] if sources_list else None,  # Backward-compat
        })

    # === Sortierung & Output ===
    results.sort(key=lambda x: (x["technical"]["confidence"], x["mentions"]), reverse=True)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Fertig. {len(results)} validierte Signale → {OUTPUT_PATH}", flush=True)
    print("\nTop 10 nach Confidence × Mentions:", flush=True)
    for r in results[:10]:
        t = r["technical"]
        m = r["mentions"]
        print(f"  {r['name'][:30]:30} {r['ticker']:10} "
              f"Score:{t['score']:+.1f} Conf:{t['confidence']} "
              f"×{m} {t['direction']}",
              flush=True)

if __name__ == "__main__":
    main()
