"""
Script 3: Technical Validator
- Löst Unternehmensnamen → Ticker auf (yfinance)
- Prüft DE und US Börsen
- Berechnet Confluence Score (EMA, RSI, MACD, Volumen)
- Filtert ungültige Unternehmen raus
- Schreibt validierte Signale in trading_signals_validated.json
"""
import json
import os
import yfinance as yf
import pandas_ta as ta
import pandas as pd

SIGNALS_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading_signals.json"
OUTPUT_PATH  = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading_signals_validated.json"

# Bekannte Mappings für häufige deutsche Unternehmen
KNOWN_TICKERS = {
    "allianz": "ALV.DE", "sap": "SAP.DE", "siemens": "SIE.DE",
    "siemens energy": "ENR.DE", "deutsche bank": "DBK.DE",
    "commerzbank": "CBK.DE", "volkswagen": "VOW3.DE", "vw": "VOW3.DE",
    "bmw": "BMW.DE", "mercedes": "MBG.DE", "mercedes-benz": "MBG.DE",
    "basf": "BAS.DE", "bayer": "BAYN.DE", "adidas": "ADS.DE",
    "daimler truck": "DTG.DE", "mtu aero engines": "MTX.DE",
    "mtu": "MTX.DE", "infineon": "IFX.DE", "heidelberg": "HEIG.DE",
    "deutsche telekom": "DTE.DE", "telekom": "DTE.DE",
    "e.on": "EOAN.DE", "eon": "EOAN.DE", "rwe": "RWE.DE",
    "hannover re": "HNR1.DE", "munich re": "MUV2.DE",
    "münchener rück": "MUV2.DE", "fresenius": "FRE.DE",
    "continental": "CON.DE", "henkel": "HEN3.DE",
    "sartorius": "SRT3.DE", "zalando": "ZAL.DE", "delivery hero": "DHER.DE",
    "hellofresh": "HFG.DE", "teamviewer": "TMV.DE",
    "scout24": "G24.DE", "compugroup": "COP.DE",
    "unicredit": "UCG.MI", "deutsche pfandbriefbank": "PBB.DE",
    "redcare pharmacy": "RDC.DE", "doc morris": "0QT.L",
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
    "pernod ricard": "RI.PA", "figma": None,  # nicht börsennotiert
    "openai": None, "anthropic": None,  # nicht börsennotiert
}

def resolve_ticker(company_name):
    """Löst Unternehmensnamen zu Ticker auf."""
    key = company_name.lower().strip()

    # 1. Bekannte Mappings
    if key in KNOWN_TICKERS:
        return KNOWN_TICKERS[key]

    # 2. yfinance Search
    try:
        results = yf.Search(company_name, max_results=3)
        quotes = results.quotes
        if quotes:
            # Bevorzuge deutsche Börse wenn möglich
            for q in quotes:
                if q.get("exchange") in ("GER", "XETRA", "FRA", "STU", "MUN"):
                    return q.get("symbol")
            # Sonst erstes Ergebnis
            return quotes[0].get("symbol")
    except Exception:
        pass

    return None

def get_technical_score(ticker):
    """Berechnet Confluence Score für einen Ticker."""
    try:
        df = yf.download(ticker, period="2y", interval="1d",
                         progress=False, auto_adjust=True)
        df = df.dropna()
        if df.empty or len(df) < 50:
            return None

        close = df["Close"].iloc[:, 0]
        high  = df["High"].iloc[:, 0]
        low   = df["Low"].iloc[:, 0]
        vol   = df["Volume"].iloc[:, 0]

        score   = 0
        max_score = 8
        reasons = []

        # 1. EMA Stack (20 > 50 > 200)
        ema20  = ta.ema(close, length=20)
        ema50  = ta.ema(close, length=50)
        ema200 = ta.ema(close, length=200)
        if ema20.iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]:
            score += 2
            reasons.append("EMA Stack bullish ✓")
        elif ema20.iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]:
            score -= 2
            reasons.append("EMA Stack bearish ✗")

        # 2. RSI
        rsi = ta.rsi(close, length=14)
        rsi_val = rsi.iloc[-1]
        if 45 < rsi_val < 65:
            score += 1
            reasons.append(f"RSI gesund ({rsi_val:.0f}) ✓")
        elif rsi_val > 75:
            score -= 1
            reasons.append(f"RSI überkauft ({rsi_val:.0f}) ✗")
        elif rsi_val < 30:
            score += 1
            reasons.append(f"RSI überverkauft ({rsi_val:.0f}) – Reversal möglich")

        # 3. MACD Histogram steigt
        macd = ta.macd(close)
        hist_col = [c for c in macd.columns if "MACDh" in c][0]
        if macd[hist_col].iloc[-1] > macd[hist_col].iloc[-2]:
            score += 1
            reasons.append("MACD Momentum steigt ✓")

        # 4. Preis über/unter EMA50
        last_close = close.iloc[-1]
        if last_close > ema50.iloc[-1]:
            score += 1
            reasons.append("Preis über EMA50 ✓")
        else:
            score -= 1
            reasons.append("Preis unter EMA50 ✗")

        # 5. Volumen-Trend (letzte 5 Tage vs. 20-Tage-Schnitt)
        vol_avg20 = vol.rolling(20).mean().iloc[-1]
        vol_avg5  = vol.rolling(5).mean().iloc[-1]
        if vol_avg5 > vol_avg20 * 1.2:
            score += 1
            reasons.append("Volumen erhöht ✓")

        # 6. Weekly Trend (höhere Timeframe Bestätigung)
        df_w = yf.download(ticker, period="1y", interval="1wk",
                           progress=False, auto_adjust=True)
        df_w = df_w.dropna()
        if not df_w.empty and len(df_w) > 20:
            close_w = df_w["Close"].iloc[:, 0]
            ema20_w = ta.ema(close_w, length=20)
            if close_w.iloc[-1] > ema20_w.iloc[-1]:
                score += 2
                reasons.append("Weekly Trend bullish ✓")
            else:
                score -= 2
                reasons.append("Weekly Trend bearish ✗")

        confidence = round((score + max_score) / (2 * max_score), 2)

        return {
            "ticker":        ticker,
            "last_price":    round(float(last_close), 2),
            "score":         score,
            "max_score":     max_score,
            "confidence":    confidence,
            "direction":     "LONG" if score > 0 else "SHORT" if score < 0 else "NEUTRAL",
            "reasons":       reasons,
            "ema20":         round(float(ema20.iloc[-1]), 2),
            "ema50":         round(float(ema50.iloc[-1]), 2),
            "rsi":           round(float(rsi_val), 1),
        }

    except Exception as e:
        print(f"     ✗ Technische Analyse Fehler: {e}", flush=True)
        return None


def main():
    with open(SIGNALS_PATH, encoding="utf-8") as f:
        signals = json.load(f)

    validated = []
    all_candidates = []

    # Alle Unternehmen aus allen Videos sammeln
    for signal in signals:
        for company in signal.get("companies", []):
            all_candidates.append({
                "company":        company,
                "source":         signal["source"],
                "market_outlook": signal.get("market_outlook"),
            })

    print(f"Kandidaten gesamt: {len(all_candidates)}", flush=True)

    # Deduplizieren nach Firmenname
    seen = {}
    for c in all_candidates:
        key = c["company"]["name"].lower().strip()
        if key not in seen:
            seen[key] = c

    print(f"Unique Unternehmen: {len(seen)}", flush=True)

    results = []
    for key, candidate in seen.items():
        company = candidate["company"]
        name    = company["name"]
        print(f"\n[{name}]", flush=True)

        # Ticker auflösen
        ticker = resolve_ticker(name)
        if not ticker:
            print(f"  ✗ Kein Ticker gefunden – überspringe", flush=True)
            continue

        print(f"  → Ticker: {ticker}", flush=True)

        # Technische Analyse
        tech = get_technical_score(ticker)
        if not tech:
            print(f"  ✗ Keine Kursdaten – überspringe", flush=True)
            continue

        print(f"  → Score: {tech['score']}/{tech['max_score']} "
              f"| Confidence: {tech['confidence']} "
              f"| {tech['direction']}", flush=True)

        results.append({
            "name":           name,
            "ticker":         ticker,
            "sentiment":      company.get("sentiment"),
            "strength":       company.get("strength"),
            "action_hint":    company.get("action_hint"),
            "reason":         company.get("reason"),
            "mentioned_price":company.get("mentioned_price"),
            "price_target":   company.get("price_target"),
            "technical":      tech,
            "source":         candidate["source"],
        })

    # Sortieren nach Confidence
    results.sort(key=lambda x: x["technical"]["confidence"], reverse=True)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Fertig. {len(results)} validierte Signale → {OUTPUT_PATH}", flush=True)
    print(f"\nTop 5 nach Confidence:", flush=True)
    for r in results[:5]:
        t = r["technical"]
        print(f"  {r['name']:25} {r['ticker']:10} "
              f"Score:{t['score']:+d} Conf:{t['confidence']} {t['direction']}",
              flush=True)


if __name__ == "__main__":
    main()
