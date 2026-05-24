"""
Watchlist Manager
- Liest analysierte Signale aus trading_signals.json
- Pflegt Watchlist über 30 Tage
- Berechnet Conviction Score
- Aktualisiert technische Scores
"""
import sqlite3
import json
import os
import math
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta

DB_PATH      = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
SIGNALS_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading_signals.json"
WATCHLIST_DAYS = 30
MIN_MENTIONS   = 2
MIN_CONVICTION = 0.60

def calculate_conviction(bullish, bearish, neutral, mention_count, unique_channels):
    """
    Conviction Score 0-1:
    - Sentiment-Ratio (bullish vs gesamt)
    - Logarithmische Mentions-Gewichtung
    - Bonus für mehrere verschiedene Kanäle
    """
    if mention_count == 0:
        return 0.0
    sentiment_score = bullish / mention_count
    mention_weight  = math.log(mention_count + 1) / math.log(11)  # normalisiert auf 10 max
    channel_bonus   = min(unique_channels / 3, 1.0) * 0.2  # max 20% Bonus
    conviction = (sentiment_score * 0.6 + mention_weight * 0.4) * (1 + channel_bonus)
    return min(round(conviction, 3), 1.0)

def get_technical_score(ticker):
    """Schnelle technische Bewertung für Watchlist."""
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

        if ema20.iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]:
            score += 2
        elif ema20.iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]:
            score -= 2

        rsi_val = rsi.iloc[-1]
        if 45 < rsi_val < 65:
            score += 1
        elif rsi_val > 75:
            score -= 1
        elif rsi_val < 30:
            score += 1

        hist_col = [c for c in macd.columns if "MACDh" in c][0]
        if macd[hist_col].iloc[-1] > macd[hist_col].iloc[-2]:
            score += 1

        if close.iloc[-1] > ema50.iloc[-1]:
            score += 1

        # Weekly
        df_w = yf.download(ticker, period="1y", interval="1wk",
                          progress=False, auto_adjust=True)
        df_w = df_w.dropna()
        if not df_w.empty and len(df_w) > 20:
            close_w = df_w["Close"].iloc[:, 0]
            ema20_w = ta.ema(close_w, length=20)
            if close_w.iloc[-1] > ema20_w.iloc[-1]:
                score += 2
            else:
                score -= 2

        max_score = 7
        confidence = round((score + max_score) / (2 * max_score), 2)
        direction  = "LONG" if score > 0 else "SHORT" if score < 0 else "NEUTRAL"
        return confidence, direction

    except Exception as e:
        return None, None

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
        "volkswagen": "VOW3.DE", "basf": "BAS.DE",
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
    }
    key = name.lower().strip()
    if key in KNOWN:
        return KNOWN[key]
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
    # Bekannte Sektoren direkt
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

    # yfinance Lookup für unbekannte Ticker
    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector")
        if sector:
            return sector
    except:
        pass
    return "Other"


def main():
    print("📋 Watchlist Manager gestartet", flush=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # 1. Alte Einträge bereinigen (> 30 Tage ohne Mention)
    cutoff = (datetime.now() - timedelta(days=WATCHLIST_DAYS)).strftime("%Y-%m-%d")
    dropped = con.execute("""
        UPDATE watchlist SET status='dropped'
        WHERE last_seen < ? AND status='watching'
    """, (cutoff,)).rowcount
    con.commit()
    if dropped:
        print(f"  🗑 {dropped} Einträge als 'dropped' markiert", flush=True)

    # 2. Neue Mentions aus trading_signals.json einlesen
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

        # Datum formatieren
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

            # Mention speichern (IGNORE bei Duplikaten)
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

    # 3. Watchlist aggregieren
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
        conviction = calculate_conviction(
            m["bullish"], m["bearish"], m["neutral"],
            m["mention_count"], m["unique_channels"]
        )
        channels_list = m["channels"].split(",") if m["channels"] else []

        # Ticker auflösen falls noch nicht bekannt
        existing = con.execute(
            "SELECT ticker FROM watchlist WHERE name=? AND status='watching'", (name,)
        ).fetchone()

        ticker = existing["ticker"] if existing and existing["ticker"] else resolve_ticker(name)
        sector = get_sector(ticker) if ticker else "Other"

        # Watchlist updaten oder neu eintragen
        con.execute("""
            INSERT INTO watchlist (name, ticker, first_seen, last_seen,
                mention_count, bullish_count, bearish_count, neutral_count,
                conviction_score, channels, status, sector)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO NOTHING
        """, (name, ticker, m["first_seen"], m["last_seen"],
              m["mention_count"], m["bullish"], m["bearish"], m["neutral"],
              conviction, json.dumps(channels_list), "watching", sector))

        # Existierenden Eintrag updaten
        con.execute("""
            UPDATE watchlist SET
                ticker=?, last_seen=?, mention_count=?,
                bullish_count=?, bearish_count=?, neutral_count=?,
                conviction_score=?, channels=?, status='watching',
                sector=?
            WHERE name=? AND status IN ('watching', 'dropped')
        """, (ticker, m["last_seen"], m["mention_count"],
              m["bullish"], m["bearish"], m["neutral"],
              conviction, json.dumps(channels_list), sector, name))

    con.commit()

    # 4. Technische Scores für Top-Kandidaten aktualisieren
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

    # 5. Top Kandidaten ausgeben
    top = con.execute("""
        SELECT * FROM watchlist
        WHERE status='watching'
        ORDER BY conviction_score DESC
        LIMIT 10
    """).fetchall()

    print(f"\n📋 TOP WATCHLIST:")
    print(f"{'Name':25} {'Ticker':10} {'Mentions':8} {'Bull/Bear':10} {'Conv':6} {'Tech':6} {'Richtung'}")
    print("-" * 80)
    for w in top:
        channels = json.loads(w["channels"]) if w["channels"] else []
        print(f"  {w['name']:25} {(w['ticker'] or '?'):10} "
              f"{(w['sector'] or 'Other'):12} "
              f"{w['mention_count']:4}x  "
              f"{w['bullish_count']}↑/{w['bearish_count']}↓  "
              f"Conv:{w['conviction_score']:.2f}  "
              f"Tech:{w['tech_score'] or '–'}  "
              f"{w['tech_direction'] or '–'}")

    con.close()
    print(f"\n✅ Watchlist Manager abgeschlossen", flush=True)

if __name__ == "__main__":
    main()
