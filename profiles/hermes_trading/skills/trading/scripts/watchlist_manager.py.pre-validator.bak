"""
Watchlist Manager
- Liest analysierte Signale aus trading_signals.json
- Pflegt Watchlist über 14 Tage (reduziert von 30)
- Berechnet Conviction Score (bullish + bearish)
- Watchlist-Hygiene: Ticker-Drop, Tech-Score-Drop
"""
import sqlite3
import json
import os
import re
import math
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta

DB_PATH      = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
SIGNALS_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading_signals.json"
WATCHLIST_DAYS = 14  # REDUZIERT von 30 auf 14 Tage
MIN_MENTIONS   = 2
MIN_CONVICTION = 0.55  # leicht gesenkt für mehr SHORT-Signale

def get_channel_weights(con):
    """
    Lädt aktive Quellen-Gewichte aus source_registry.
    Fallback: Gewicht 1.0 für unbekannte Kanäle.
    Stellt sicher dass Lifecycle-Anpassungen direkt auf Conviction wirken.
    """
    try:
        rows = con.execute("""
            SELECT display_name, weight
            FROM source_registry
            WHERE status IN ('active', 'probation') AND enabled = 1
        """).fetchall()
        return {r["display_name"]: r["weight"] for r in rows}
    except Exception:
        return {}

def _weighted_sentiment(mentions_list, channel_weights, sentiment):
    """
    Berechnet Anteil eines Sentiments gewichtet nach Channel-Gewichten.
    Wird aktuell nicht direkt aufgerufen, dient als Helfer für zukünftige Nutzung.
    """
    if not channel_weights or not mentions_list:
        return None
    total_weight = sum(channel_weights.get(ch.strip(), 1.0) for ch in mentions_list)
    return total_weight

def calculate_conviction(bullish, bearish, neutral, mention_count, unique_channels,
                         channels_list=None, channel_weights=None):
    """
    Conviction Score 0-1 für bullish-Signale.
    Berücksichtigt source_registry Gewichte wenn vorhanden.
    """
    if mention_count == 0:
        return 0.0
    # Gewichtete Sentiment-Ratio falls Gewichte verfügbar
    if channel_weights and channels_list and mention_count > 0:
        # Gewichte pro Channel abrufen
        weights = {}
        for ch in channels_list:
            weights[ch.strip()] = channel_weights.get(ch.strip(), 1.0)
        w_total = sum(weights.values()) or 1.0
        # Annahme: bullish Mentions verteilen sich proportional auf Channels
        # Gewichtung: Jede bullishe Mention zählt mit dem Channel-Gewicht
        bullish_weighted = bullish * (w_total / len(weights))  # ø-Gewicht pro Mention
        sentiment_score = bullish_weighted / (mention_count * w_total / len(weights)) \
                          if len(weights) > 0 else bullish / mention_count
        # Vereinfacht: Anteil bullish * durchschnittliches Channel-Gewicht
        avg_weight = w_total / len(weights)
        sentiment_score = (bullish / mention_count) * avg_weight
    else:
        sentiment_score = bullish / mention_count
    mention_weight  = math.log(mention_count + 1) / math.log(11)
    channel_bonus   = min(unique_channels / 3, 1.0) * 0.2
    conviction = (sentiment_score * 0.6 + mention_weight * 0.4) * (1 + channel_bonus)
    return min(round(conviction, 3), 1.0)

def calculate_conviction_bear(bullish, bearish, neutral, mention_count, unique_channels,
                               channels_list=None, channel_weights=None):
    """
    Conviction Score 0-1 für bearish/SHORT-Signale.
    Berücksichtigt source_registry Gewichte wenn vorhanden.
    """
    if mention_count == 0:
        return 0.0
    if channel_weights and channels_list and mention_count > 0:
        weights = {}
        for ch in channels_list:
            weights[ch.strip()] = channel_weights.get(ch.strip(), 1.0)
        w_total = sum(weights.values()) or 1.0
        # Vereinfacht: Anteil bearish * durchschnittliches Channel-Gewicht
        avg_weight = w_total / len(weights)
        bear_ratio = (bearish / mention_count) * avg_weight
    else:
        bear_ratio = bearish / mention_count
    mention_weight = math.log(mention_count + 1) / math.log(11)
    channel_bonus = min(unique_channels / 3, 1.0) * 0.2
    conviction = (bear_ratio * 0.6 + mention_weight * 0.4) * (1 + channel_bonus)
    return min(round(conviction, 3), 1.0)

def get_technical_score(ticker):
    """
    Schnelle technische Bewertung für Watchlist.
    Neuer Score: -10 bis +10 → 0.0-1.0 mit ADX.
    """
    try:
        df = yf.download(ticker, period="2y", interval="1d",
                        progress=False, auto_adjust=True)
        df = df.dropna()
        if df.empty or len(df) < 50:
            return None, None

        close  = df["Close"].iloc[:, 0]
        high   = df["High"].iloc[:, 0]
        low    = df["Low"].iloc[:, 0]

        ema20  = ta.ema(close, length=20)
        ema50  = ta.ema(close, length=50)
        ema200 = ta.ema(close, length=200)
        rsi    = ta.rsi(close, length=14)
        macd   = ta.macd(close)

        score = 0
        if ema200 is None or ema200.iloc[-1] is None:
            return None, None

        # 1. EMA Stack — Gewicht: 1
        if ema20.iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]:
            score += 1
        elif ema20.iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]:
            score -= 1

        # 2. RSI — differenzierter
        rsi_val = rsi.iloc[-1]
        if 50 < rsi_val < 60:
            score += 2
        elif 40 < rsi_val < 70:
            score += 1
        elif rsi_val > 75:
            score -= 2
        elif rsi_val < 25:
            score -= 2

        # 3. MACD Histogram
        hist_col = [c for c in macd.columns if "MACDh" in c][0]
        if macd[hist_col].iloc[-1] > 0 and macd[hist_col].iloc[-1] > macd[hist_col].iloc[-2]:
            score += 2
        elif macd[hist_col].iloc[-1] > macd[hist_col].iloc[-2]:
            score += 1
        elif macd[hist_col].iloc[-1] < 0 and macd[hist_col].iloc[-1] < macd[hist_col].iloc[-2]:
            score -= 2

        # 4. Preis vs. EMA50
        dist_ema50 = (close.iloc[-1] - ema50.iloc[-1]) / ema50.iloc[-1]
        if dist_ema50 > 0.05:
            score += 1
        elif dist_ema50 > 0:
            score += 0.5
        elif dist_ema50 < -0.05:
            score -= 1
        else:
            score -= 0.5

        # 5. Volumen-Trend
        vol = df["Volume"].iloc[:, 0]
        vol_avg20 = vol.rolling(20).mean().iloc[-1]
        vol_avg5  = vol.rolling(5).mean().iloc[-1]
        if vol_avg5 > vol_avg20 * 1.5:
            score += 1.5
        elif vol_avg5 > vol_avg20 * 1.2:
            score += 1

        # 6. Weekly Trend — Gewicht: 1
        df_w = yf.download(ticker, period="1y", interval="1wk",
                          progress=False, auto_adjust=True)
        df_w = df_w.dropna()
        if not df_w.empty and len(df_w) > 20:
            close_w = df_w["Close"].iloc[:, 0]
            ema20_w = ta.ema(close_w, length=20)
            if close_w.iloc[-1] > ema20_w.iloc[-1]:
                score += 1
            else:
                score -= 1

        # 7. ADX
        try:
            adx_df = ta.adx(high, low, close, length=14)
            adx_val = adx_df["ADX_14"].iloc[-1]
            if adx_val > 25:
                score += 1
            elif adx_val < 15:
                score -= 0.5
        except:
            pass

        max_score = 10
        confidence = round((score + max_score) / (2 * max_score), 3)
        confidence = max(0.0, min(1.0, confidence))
        direction  = "LONG" if score >= 2 else "SHORT" if score <= -2 else "NEUTRAL"
        return confidence, direction

    except Exception as e:
        return None, None

# ── Normalisierung (Alias-Tabelle + Legal-Suffix-Regex) ──────────────────────
NORMALIZE_ALIASES = {
    # LLM-Tippfehler → Canonical
    "palantier": "Palantir", "palanteer": "Palantir",
    "reinmetall": "Rheinmetall", "reimmetall": "Rheinmetall",
    "corweef": "CoreWeave", "core weave": "CoreWeave",
    "nebiuz": "Nebius",
    "enhropic": "Anthropic", "entropic": "Anthropic", "anropic": "Anthropic",
    "tüssenkrup": "ThyssenKrupp", "tüssengrup": "ThyssenKrupp",
    "morgen stanley": "Morgan Stanley",
    "rocketlab": "Rocket Lab",
    "soundhoundai": "SoundHound AI", "soundhound": "SoundHound AI",
    "solar edge": "SolarEdge",
    "johnson und johnson": "Johnson & Johnson",
    "albe male": "Alphabet",  # LLM-Halluzination
    "poo gold": "Poo Gold",  # Nischen-Aktie
    # Bekannte Name-Varianten → Canonical
    "meta platforms": "Meta", "meta platforms inc.": "Meta",
    "nvidia corporation": "NVIDIA", "nvidia corp.": "NVIDIA",
    "alphabet inc.": "Alphabet", "alphabet inc. (google)": "Alphabet",
    "micron technology": "Micron",
    "advanced micro devices": "Advanced Micro Devices",
    "intel corporation": "Intel",
    "cerebras systems": "Cerebras", "cerebras systems inc.": "Cerebras",
    "take two interactive": "Take-Two Interactive",
    "take two interactive software": "Take-Two Interactive",
    "take-two interactive software": "Take-Two Interactive",
    "d-wave systems": "D-Wave Quantum", "d-wave systems inc.": "D-Wave Quantum",
    "d-wave quantum inc.": "D-Wave Quantum",
    "d w v quantum": "D-Wave Quantum",
    "jp morgan": "JPMorgan", "jp morgan chase": "JPMorgan",
    "jpmorgan chase": "JPMorgan",
    "goldman sachs group": "Goldman Sachs",
    "berkshire hathaway inc.": "Berkshire Hathaway",
    "costco wholesale": "Costco", "costco wholesale corporation": "Costco",
    "amazon.com": "Amazon", "amazon.com inc.": "Amazon",
    "apple inc.": "Apple",
    "microsoft corporation": "Microsoft",
    "meta platforms inc.": "Meta",
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
    "mara holdings": "MARA",
    "marathon digital holdings": "MARA", "marathon digital holdings inc.": "MARA",
    "rheinmetall ag": "Rheinmetall",
    "infineon technologies": "Infineon", "infineon technologies ag": "Infineon",
    "siemens ag": "Siemens", "siemens aktiengesellschaft": "Siemens",
    "basf se": "BASF",
    "bayer ag": "Bayer",
    "mercedes-benz group": "Mercedes-Benz",
    "adidas ag": "Adidas",
    "zaland se": "Zalando", "zalandos e": "Zalando",
    "commerzbank ag": "Commerzbank",
    "deutsche bank ag": "Deutsche Bank",
    "delivery hero se": "Delivery Hero",
    "dws group gmbh & co. kgaa": "DWS",
    "henkel ag & co. kgaa": "Henkel",
    "cts eventim ag & co. kgaa": "CTS Eventim",
    "stroer se & co. kgaa": "Ströer",
    "kws saat se & co. kgaa": "KWS SAAT",
    "ottobock se & co. kgaa": "Ottobock",
    "münchener rück": "Münchner Rück", "munich re": "Münchner Rück",
    "hannover rück": "Hannover Rück",
    "united health": "UnitedHealth",
    "mercado libre": "MercadoLibre",
    "alibaba group": "Alibaba",
    "uber technologies": "Uber",
    "cisco systems": "Cisco",
    "mastercard inc.": "Mastercard",
    "visa inc.": "Visa",
    "the trade desk": "Trade Desk",
    "booking holdings": "Booking Holdings",
    "by company": "BYD",
    "taiwan semiconductor": "TSMC",
    "taiwan semiconductor manufacturing company": "TSMC",
    "taiwan semiconductor manufacturing company limited": "TSMC",
    "semiconductor manufacturing international corporation": "SMIC",
    "johnson & johnson (jnj)": "Johnson & Johnson",
    "linde plc": "Linde",
    "arm holdings plc": "ARM",
    "standard chartered plc": "Standard Chartered",
    "nextracker inc.": "Nextracker",
    "palantir technologies": "Palantir",
    "microstrategy incorporated": "MicroStrategy",
    "intuitive surgical": "Intuitive Surgical",
    "marvell technology": "Marvell",
    "marvell technology, inc.": "Marvell",
    "on holding": "On",
    "viking holdings ltd": "Viking Holdings",
    "schneider electric se": "Schneider Electric",
    "upstart holdings, inc. (upst)": "Upstart",
    # Spezialfälle zusätzlich
    "lvmh moët hennessy louis vuitton": "LVMH",
    "lvmh moet hennessy louis vuitton": "LVMH",
    "alphabet inc. (google)": "Alphabet",  # doppelt gemoppelt
    "john deere": "Deere & Company",
    "scalable capital": "Scalable Capital",  # nicht börsennotiert, aber keep
    "delta airlines": "Delta Air Lines",
    "itaú": "Itaú Unibanco",
    "merck kgaa": "Merck",
    "jabil inc.": "Jabil",
    "united rentals": "United Rentals",
    "royal caribbean cruises ltd.": "Royal Caribbean",
    "mastercard inc.": "Mastercard",
    # Case-Varianten (LLM liefert gemischt)
    "nvidia": "NVIDIA",
    "amd": "AMD",
    "ibm": "IBM",
    "cisco": "Cisco",
    "intc": "Intel",
    "msft": "Microsoft",
    "googl": "Alphabet",
    "meta": "Meta",  # falls mal "Meta" groß in der DB
}

LEGAL_SUFFIX_RE = re.compile(
    r"(?:\s*[,/]\s*)?"
    r"(?:"
    r"AG(?:\s+&?\s*Co\.?\s*(?:KGaA|KG|OHG))?"
    r"|SE|GmbH(?:\s*&\s*Co\.?\s*(?:KG|KGaA|OHG))?"
    r"|PLC|plc|Inc\.|Inc|Corporation|Corp\.?|Corp"
    r"|Ltd\.?|Limited|LLC|LLP|LP|NV|N\.V\.|SA|S\.A\.|AB|OY"
    r"|S\.p\.A\.|Sp\.? z\.?o\.?o\.?|JSC|PJSC|OJSC"
    r"|Holdings?|Group|Co\.|Company"
    r"|Class\s+[ABCDE]|Common\s+Stock"
    r")(?:\.|\s)*$",
    re.IGNORECASE
)

BRACKET_NOTE_RE = re.compile(
    r"\s*\((?:nicht\s+börsennotiert|Marke\s+von[^)]*|privat[^)]*|Teil\s+von[^)]*)\)\s*$",
    re.IGNORECASE
)


def normalize_company_name(name):
    """Normalisiert Unternehmensnamen zum Abgleich von Duplikaten.

    1. Strip Klammer-Notizen: '(nicht börsennotiert)', '(Marke von ...)'
    2. Strip Legal-Suffixe: 'AG', 'Inc.', 'Corporation', 'Ltd', 'PLC', 'SE', 'GmbH & Co. KGaA' usw.
    3. Strip 'The '-Präfix (optional)
    4. Alias-Resolution via NORMALIZE_ALIASES
    5. Trim whitespace
    """
    n = name.strip()
    # Klammer-Notizen entfernen
    n = BRACKET_NOTE_RE.sub("", n)
    # 'bei Do?' u.ä. aus Klammern im Namen
    n = re.sub(r"\s*\([^)]*[?][^)]*\)\s*$", " ", n)
    # Legal-Suffixe entfernen (iterativ für verschachtelte: "DWS Group GmbH & Co. KGaA")
    prev = None
    while prev != n:
        prev = n
        n = LEGAL_SUFFIX_RE.sub("", n).strip()
    # 'The '-Präfix entfernen
    n = re.sub(r"^The\s+", "", n)
    # Whitespace normalisieren
    n = re.sub(r"\s+", " ", n).strip()
    # Alias-Resolution (lowercase-Key)
    lower = n.lower()
    if lower in NORMALIZE_ALIASES:
        return NORMALIZE_ALIASES[lower]
    return n


def resolve_ticker(name):
    """Einfache Ticker-Auflösung via yfinance Search."""
    KNOWN = {
        "sap": "SAP.DE", "servicenow": "NOW", "service now": "NOW",
        "microsoft": "MSFT", "apple": "AAPL", "nvidia": "NVDA",
        "tesla": "TSLA", "amazon": "AMZN", "meta": "META",
        "alphabet": "GOOGL", "google": "GOOGL", "intel": "INTC",
        "nike": "NKE", "adobe": "ADBE", "broadcom": "AVGO",
        "palantir": "PLTR", "salesforce": "CRM", "amd": "AMD",
        "halliburton": "HAL", "siemens energy": "ENR.DE",
        "sgl carbon": "SGL.DE", "commerzbank": "CBK.DE",
        "allianz": "ALV.DE", "siemens": "SIE.DE",
        "deutsche bank": "DBK.DE", "bmw": "BMW.DE",
        "volkswagen": "VOW3.DE", "bas": "BAS.DE",
        "bayer": "BAYN.DE", "adidas": "ADS.DE",
        "infineon": "IFX.DE", "mtu aero engines": "MTX.DE",
        "deutsche telekom": "DTE.DE", "rwe": "RWE.DE",
        "eli lilly": "LLY", "unitedhealth": "UNH",
        "johnson & johnson": "JNJ", "msci": "MSCI",
        "crowdstrike": "CRWD", "palo alto": "PANW",
        "fastly": "FSLY", "applovin": "APP",
        "bloom energy": "BE", "ionq": "IONQ",
        "synopsys": "SNPS", "autodesk": "ADSK",
        "texas instruments": "TXN", "ibm": "IBM",
        "sandisk": "SNDK", "qualcomm": "QCOM",
        "take-two interactive": "TTWO", "d-wave quantum": "QBTS",
        "lvmh": "MC.PA", "linde": "LIN",
    }
    key = name.lower().strip()
    if key in KNOWN:
        return KNOWN[key]
    # Auch nach Normalisierung prüfen
    norm = normalize_company_name(name).lower().strip()
    if norm != key and norm in KNOWN:
        return KNOWN[norm]
    try:
        results = yf.Search(name, max_results=3)
        quotes  = results.quotes
        if quotes:
            for q in quotes:
                if q.get("exchange") in ("GER","XETRA","FRA","STU","MUN"):
                    return q.get("symbol")
            return quotes[0].get("symbol")
    except:
        pass
    return None

def get_sector(ticker):
    """Holt Sektor via yfinance, cached in DB."""
    KNOWN_SECTORS = {
        "Tech":      ["AAPL","MSFT","GOOGL","NVDA","META","NOW","SAP.DE",
                      "INTC","AMD","AVGO","ADBE","PLTR","CRM","PANW",
                      "CRWD","SNPS","ADSK","FSLY","APP","IBM","IONQ"],
        "Finance":   ["MSCI","CBK.DE","DBK.DE","ALV.DE","UCG.MI",
                      "BAC","JPM","GS","MS"],
        "Energy":    ["ENR.DE","RWE.DE","EOAN.DE","HAL","BE","SLB"],
        "Consumer":  ["NKE","ADS.DE"],
        "Health":    ["LLY","JNJ","UNH","GILD","MRNA"],
        "Materials": ["SGL.DE","BAS.DE","BAYN.DE"],
        "Industrial":["SIE.DE","MTX.DE","DTG.DE"],
        "Auto":      ["BMW.DE","VOW3.DE","MBG.DE","TSLA"],
    }
    for sector, tickers in KNOWN_SECTORS.items():
        if ticker in tickers:
            return sector
    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector")
        if sector:
            return sector
    except:
        pass
    return "Other"


def normalize_mentions(con):
    """Dedupliziert watchlist_mentions.name via normalize_company_name().

    Findet Duplikate wie 'Meta'/'Meta Platforms'/'Meta Platforms Inc.',
    merged sie auf den kürzesten/gebräuchlichsten Namen durch UPDATE.
    """
    import re as _re  # shadow import für re innerhalb der Funktion

    rows = con.execute(
        "SELECT DISTINCT name FROM watchlist_mentions ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    print(f"  🔍 Normalisiere {len(names)} unique Namen...", flush=True)

    # Gruppiere nach normalisiertem Namen
    groups = {}  # normalized -> [original_names]
    for n in names:
        norm = normalize_company_name(n)
        groups.setdefault(norm, []).append(n)

    # Merge: canonical = kürzester Name pro Gruppe
    merged = 0
    for norm, originals in groups.items():
        if len(originals) <= 1:
            continue
        # Canonical: bevorzuge Namen der dem norm-Wortlaut exakt entspricht,
        # sonst kürzesten. Vermeide Legal-Suffixe (Inc., Corp., AG, SE etc.)
        canon_candidates = [n for n in originals if n.lower() == norm.lower()]
        if canon_candidates:
            canonical = canon_candidates[0]
        else:
            canonical = min(originals, key=len)

        # Duplikat-Reihenfolge: zuerst alle alte Namen löschen die mit
        # canonical im selben video_id konfliktieren, DANN updaten
        for orig in originals:
            if orig == canonical:
                continue
            # Schritt 1: Konflikte vor dem UPDATE bereinigen
            con.execute(
                "DELETE FROM watchlist_mentions WHERE name=? AND "
                "EXISTS (SELECT 1 FROM watchlist_mentions AS w2 "
                "WHERE w2.name=? AND w2.video_id=watchlist_mentions.video_id)",
                (orig, canonical)
            )
            # Schritt 2: Bulk-UPDATE der restlichen
            updated = con.execute(
                "UPDATE watchlist_mentions SET name=? WHERE name=?",
                (canonical, orig)
            ).rowcount
            merged += updated

        print(f"  🔗 {len(originals)} → '{canonical}'  "
              f"(zusammengeführt: {', '.join(originals)})", flush=True)

    con.commit()
    if merged:
        print(f"  ✓ {merged} Mentions auf kanonische Namen aktualisiert", flush=True)
    else:
        print(f"  ✓ Keine Duplikate gefunden", flush=True)
    return merged


def main():
    print("📋 Watchlist Manager gestartet", flush=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Migration: conviction_score_bear Spalte hinzufügen
    cols = [row[1] for row in con.execute("PRAGMA table_info(watchlist)")]
    if "conviction_score_bear" not in cols:
        con.execute("ALTER TABLE watchlist ADD COLUMN conviction_score_bear REAL DEFAULT 0")

    # Quellen-Gewichte aus source_registry laden (Lifecycle-Integration)
    channel_weights = get_channel_weights(con)
    if channel_weights:
        print(f"  ⚖️  {len(channel_weights)} Quellen-Gewichte aus source_registry geladen", flush=True)
    else:
        print("  ⚖️  source_registry leer – Standardgewichte (1.0) verwendet", flush=True)

    # 1. Alte Einträge bereinigen (> 14 Tage ohne Mention)
    cutoff = (datetime.now() - timedelta(days=WATCHLIST_DAYS)).strftime("%Y-%m-%d")
    dropped = con.execute("""
        UPDATE watchlist SET status='dropped'
        WHERE last_seen < ? AND status='watching'
    """, (cutoff,)).rowcount
    con.commit()
    if dropped:
        print(f"  🗑 {dropped} Einträge als 'dropped' markiert (>14 Tage)", flush=True)

    # 2. Einträge ohne Ticker nach 7 Tagen droppen
    cutoff_7d = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    dropped_no_ticker = con.execute("""
        UPDATE watchlist SET status='dropped'
        WHERE ticker IS NULL
        AND first_seen < ?
        AND status='watching'
    """, (cutoff_7d,)).rowcount
    con.commit()
    if dropped_no_ticker:
        print(f"  🗑 {dropped_no_ticker} Einträge ohne Ticker nach 7 Tagen gedropt", flush=True)

    # 3. Einträge mit tech_score < 0.3 nach 3 Tagen ohne neue Mention droppen
    cutoff_3d = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    dropped_low_tech = con.execute("""
        UPDATE watchlist SET status='dropped'
        WHERE tech_score < 0.30
        AND last_seen < ?
        AND status='watching'
    """, (cutoff_3d,)).rowcount
    con.commit()
    if dropped_low_tech:
        print(f"  🗑 {dropped_low_tech} Einträge mit Tech-Score < 0.3 gedropt", flush=True)

    # 4. Neue Mentions aus trading_signals.json einlesen
    if not os.path.exists(SIGNALS_PATH):
        print("  ⚠ Keine signals.json gefunden", flush=True)
        con.close()
        return

    with open(SIGNALS_PATH, encoding="utf-8") as f:
        signals = json.load(f)

    new_mentions = 0
    for signal in signals:
        source  = signal.get("source", {})
        channel = source.get("channel", "")
        video_id= source.get("video_id", "")
        title   = source.get("title", "")
        date    = source.get("date", datetime.now().strftime("%Y%m%d"))

        try:
            mention_date = datetime.strptime(str(date), "%Y%m%d").strftime("%Y-%m-%d")
        except:
            mention_date = datetime.now().strftime("%Y-%m-%d")

        for company in signal.get("companies", []):
            name      = company.get("name", "").strip()
            sentiment = company.get("sentiment", "neutral")
            reason    = company.get("reason", "")

            if not name or len(name) < 2:
                continue

            try:
                con.execute("""
                    INSERT OR IGNORE INTO watchlist_mentions
                    (name, channel, video_id, video_title, sentiment, reason, mention_date)
                    VALUES (?,?,?,?,?,?,?)
                """, (name, channel, video_id, title, sentiment, reason, mention_date))
                if con.execute("SELECT changes()").fetchone()[0] > 0:
                    new_mentions += 1
            except Exception as e:
                pass

    con.commit()
    print(f"  ✓ {new_mentions} neue Mentions gespeichert", flush=True)

    # 4b. Mention-Deduplizierung (vor Aggregation)
    normalize_mentions(con)

    # 5. Watchlist aggregieren
    mentions = con.execute("""
        SELECT name,
               COUNT(*) as mention_count,
               SUM(CASE WHEN sentiment='bullish' THEN 1 ELSE 0 END) as bullish,
               SUM(CASE WHEN sentiment='bearish' THEN 1 ELSE 0 END) as bearish,
               SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END) as neutral,
               COUNT(DISTINCT channel) as unique_channels,
               GROUP_CONCAT(DISTINCT channel) as channels,
               MIN(mention_date) as first_seen,
               MAX(mention_date) as last_seen
        FROM watchlist_mentions
        WHERE mention_date >= ?
        GROUP BY name
        ORDER BY mention_count DESC
    """, (cutoff,)).fetchall()

    print(f"  → {len(mentions)} Unternehmen in Watchlist", flush=True)

    for m in mentions:
        name       = m["name"]
        channels_list = m["channels"].split(",") if m["channels"] else []
        conviction = calculate_conviction(
            m["bullish"], m["bearish"], m["neutral"],
            m["mention_count"], m["unique_channels"],
            channels_list=channels_list, channel_weights=channel_weights
        )
        conviction_bear = calculate_conviction_bear(
            m["bullish"], m["bearish"], m["neutral"],
            m["mention_count"], m["unique_channels"],
            channels_list=channels_list, channel_weights=channel_weights
        )

        existing = con.execute(
            "SELECT ticker FROM watchlist WHERE name=? AND status='watching'", (name,)
        ).fetchone()

        ticker = existing["ticker"] if existing and existing["ticker"] else resolve_ticker(name)
        sector = get_sector(ticker) if ticker else "Other"

        con.execute("""
            INSERT INTO watchlist (name, ticker, first_seen, last_seen,
                mention_count, bullish_count, bearish_count, neutral_count,
                conviction_score, conviction_score_bear, channels, status, sector)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO NOTHING
        """, (name, ticker, m["first_seen"], m["last_seen"],
              m["mention_count"], m["bullish"], m["bearish"], m["neutral"],
              conviction, conviction_bear, json.dumps(channels_list), "watching", sector))

        con.execute("""
            UPDATE watchlist SET
                ticker=?, last_seen=?, mention_count=?,
                bullish_count=?, bearish_count=?, neutral_count=?,
                conviction_score=?, conviction_score_bear=?,
                channels=?, status='watching', sector=?
            WHERE name=? AND status IN ('watching', 'dropped')
        """, (ticker, m["last_seen"], m["mention_count"],
              m["bullish"], m["bearish"], m["neutral"],
              conviction, conviction_bear,
              json.dumps(channels_list), sector, name))

    con.commit()

    # 6. Technische Scores für Top-Kandidaten aktualisieren
    top_candidates = con.execute("""
        SELECT * FROM watchlist
        WHERE status='watching'
        AND conviction_score >= ?
        AND mention_count >= ?
        AND ticker IS NOT NULL
        ORDER BY conviction_score DESC
        LIMIT 20
    """, (MIN_CONVICTION * 0.5, 1)).fetchall()

    print(f"\n  Technische Analyse für {len(top_candidates)} Kandidaten...", flush=True)
    for c in top_candidates:
        tech_score, direction = get_technical_score(c["ticker"])
        if tech_score:
            con.execute("""
                UPDATE watchlist SET tech_score=?, tech_direction=?
                WHERE name=?
            """, (tech_score, direction, c["name"]))
            print(f"  {c['name']:25} {c['ticker']:10} "
                  f"Conv:{c['conviction_score']:.2f} "
                  f"Tech:{tech_score} {direction}", flush=True)

    con.commit()

    # 7. Top Kandidaten ausgeben
    top = con.execute("""
        SELECT * FROM watchlist
        WHERE status='watching'
        ORDER BY conviction_score DESC
        LIMIT 10
    """).fetchall()

    print("\n📋 TOP WATCHLIST:")
    print(f"{'Name':25} {'Ticker':10} {'Mentions':8} {'Bull/Bear':10} {'Conv':6} {'Bear':6} {'Tech':6} {'Richtung'}")
    print("-" * 90)
    for w in top:
        channels = json.loads(w["channels"]) if w["channels"] else []
        print(f"  {w['name']:25} {(w['ticker'] or '?'):10} "
              f"{(w['sector'] or 'Other'):12} "
              f"{w['mention_count']:4}x  "
              f"{w['bullish_count']}↑/{w['bearish_count']}↓  "
              f"Conv:{w['conviction_score']:.2f}  "
              f"Bear:{w['conviction_score_bear']:.2f}  "
              f"Tech:{w['tech_score'] or '–'}  "
              f"{w['tech_direction'] or '-'}")

    # 8. '?' Flagging: Unresolved Ticker reportieren
    unresolved = con.execute("""
        SELECT name, mention_count, conviction_score
        FROM watchlist
        WHERE status='watching' AND ticker IS NULL
        ORDER BY mention_count DESC
    """).fetchall()

    if unresolved:
        print(f"\n❓ UNRESOLVED TICKER ({len(unresolved)} Eintrage ohne Ticker):")
        print(f"  {'Name':30} {'Mentions':8} {'Conv':6}")
        print("  " + "-" * 48)
        for u in unresolved[:15]:  # Top 15
            print(f"  {u['name']:30} {u['mention_count']:4}x  "
                  f"Conv:{u['conviction_score']:.2f}")
        if len(unresolved) > 15:
            print(f"  ... und {len(unresolved) - 15} weitere (insg. {len(unresolved)})")
        print()

    con.close()
    print("\n✅ Watchlist Manager abgeschlossen", flush=True)

if __name__ == "__main__":
    main()
