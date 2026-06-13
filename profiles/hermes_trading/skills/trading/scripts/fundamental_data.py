"""
Fundamental Data Collector
- FRED Makrodaten (Yield Curve, Fed Rate, CPI, VIX)
- SEC EDGAR Form 4 (Insider Trades)
- Put/Call Ratio via yfinance
"""
import sqlite3
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import requests
import yfinance as yf
from datetime import datetime, timedelta
from config import DB_PATH, MACRO_SIGNAL_PATH, STRATEGY_CONFIG_PATH, db_connect
from utils import retry, get_logger
log = get_logger("fundamental_data")

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

def load_config():
    with open(STRATEGY_CONFIG_PATH) as f:
        return json.load(f)

def fetch_fred_data(con, indicators):
    """Holt Makrodaten von FRED API."""
    print("\n📊 FRED Makrodaten...", flush=True)
    for ind in indicators:
        if not ind.get("enabled"):
            continue
        try:
            if FRED_API_KEY:
                url = f"https://api.stlouisfed.org/fred/series/observations?series_id={ind['id']}&api_key={FRED_API_KEY}&file_type=json&limit=1&sort_order=desc"
                r = requests.get(url, timeout=10)
                data = r.json()
                obs = data["observations"][-1]
                value = float(obs["value"]) if obs["value"] != "." else None
                date  = obs["date"]
            else:
                # Kostenloser Fallback via FRED ohne Key (limitiert)
                url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={ind['id']}"
                r = requests.get(url, timeout=10)
                lines = r.text.strip().split("\n")
                last = lines[-1].split(",")
                date  = last[0]
                value = float(last[1]) if last[1] not in ["", "."] else None

            if value is None:
                continue

            # Signal berechnen
            signal = "neutral"
            if ind["id"] == "T10Y2Y":
                signal = "bearish" if value < 0 else "bullish"
            elif ind["id"] == "VIXCLS":
                signal = "bearish" if value > 25 else "bullish" if value < 15 else "neutral"

            con.execute("""
                INSERT INTO macro_data (indicator, value, date, fetched_at, signal, description)
                VALUES (?,?,?,?,?,?)
            """, (ind["id"], value, date, datetime.now().isoformat(),
                  signal, ind["name"]))
            print(f"  ✓ {ind['name']:30} {value:8.3f} [{signal}]", flush=True)

        except Exception as e:
            print(f"  ✗ {ind['id']}: {e}", flush=True)

    con.commit()

def fetch_insider_trades(con, tickers):
    """Holt Insider-Trades von SEC EDGAR für Watchlist-Ticker."""
    print("\n🏛 SEC EDGAR Insider Trades...", flush=True)
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    for ticker in tickers[:20]:  # Max 20 Ticker
        try:
            # Ticker → CIK lookup
            search_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={cutoff}&forms=4"
            headers = {"User-Agent": "TradingSkill admin@example.com"}
            r = requests.get(search_url, headers=headers, timeout=10)

            if r.status_code != 200:
                continue

            data = r.json()
            hits = data.get("hits", {}).get("hits", [])

            for hit in hits[:3]:  # Max 3 pro Ticker
                src = hit.get("_source", {})
                period = src.get("period_of_report", "")
                entity = src.get("entity_name", "")
                display_names = src.get("display_names", [])
                insider = display_names[0] if display_names else "Unknown"

                # Vereinfachtes Signal basierend auf Form 4
                signal = "neutral"
                con.execute("""
                    INSERT OR IGNORE INTO insider_trades
                    (ticker, company, insider_name, trade_date, fetched_at, signal)
                    VALUES (?,?,?,?,?,?)
                """, (ticker, entity, insider, period,
                      datetime.now().isoformat(), signal))

            if hits:
                print(f"  ✓ {ticker:10} {len(hits)} Insider-Trades gefunden", flush=True)

        except Exception as e:
            print(f"  ✗ {ticker}: {e}", flush=True)

    con.commit()

def fetch_pcr(con, tickers):
    """Berechnet Put/Call Ratio via yfinance."""
    print("\n📈 Put/Call Ratio...", flush=True)

    for ticker in tickers[:15]:  # Max 15 Ticker
        try:
            t = yf.Ticker(ticker)
            expirations = t.options
            if not expirations:
                continue

            # Nächsten Verfallstermin nehmen
            chain = t.option_chain(expirations[0])
            puts  = chain.puts["openInterest"].sum()
            calls = chain.calls["openInterest"].sum()

            if calls == 0:
                continue

            pcr = round(puts / calls, 3)
            signal = "bearish" if pcr > 1.2 else "bullish" if pcr < 0.7 else "neutral"

            con.execute("""
                INSERT INTO options_data (ticker, pcr, signal, fetched_at)
                VALUES (?,?,?,?)
            """, (ticker, pcr, signal, datetime.now().isoformat()))

            print(f"  ✓ {ticker:10} PCR={pcr:.3f} [{signal}]", flush=True)

        except Exception as e:
            pass  # Viele Ticker haben keine Options

    con.commit()

def get_macro_summary(con):
    """Gibt aktuellen Makro-Status zurück."""
    rows = con.execute("""
        SELECT indicator, value, signal, description, date
        FROM macro_data
        WHERE fetched_at = (
            SELECT MAX(fetched_at) FROM macro_data m2
            WHERE m2.indicator = macro_data.indicator
        )
        ORDER BY indicator
    """).fetchall()

    bearish_count = sum(1 for r in rows if r[2] == "bearish")
    bullish_count = sum(1 for r in rows if r[2] == "bullish")

    print("\n📊 MAKRO-ZUSAMMENFASSUNG:", flush=True)
    print(f"  Bullish: {bullish_count} | Bearish: {bearish_count}", flush=True)
    for r in rows:
        print(f"  {r[3]:35} {r[1]:8.3f} [{r[2]}] ({r[4]})", flush=True)

    # Gesamtsignal
    if bearish_count >= 2:
        return "bearish"
    elif bullish_count >= 3:
        return "bullish"
    return "neutral"

def detect_market_regime(con):
    """
    Erweitertes Regime-Modell mit zwei Dimensionen:
      1. Trend-Regime (bull/bear/sideways): Markov Chain auf SPY + DAX 20d-Returns
      2. Makro-Overlay: VIX-Level, Credit Spreads (HYG/LQD), Dollar-Index (DXY)

    Separate US- und EU-Regimes werden berechnet.
    Das kombinierte Regime gewichtet US 60% / EU 40%.
    """
    print("\n📈 Markt-Regime Erkennung (erweitert)...", flush=True)
    try:
        import yfinance as yf
        import numpy as np
        from datetime import datetime, timedelta

        # ── Marktdaten laden ────────────────────────────────────────────────
        tickers = {
            "SPY":    yf.download("SPY",    period="2y", interval="1d", progress=False, auto_adjust=True)["Close"].iloc[:, 0],
            "DAX":    yf.download("^GDAXI", period="2y", interval="1d", progress=False, auto_adjust=True)["Close"].iloc[:, 0],
            "VIX":    yf.download("^VIX",   period="2y", interval="1d", progress=False, auto_adjust=True)["Close"].iloc[:, 0],
            "HYG":    yf.download("HYG",    period="2y", interval="1d", progress=False, auto_adjust=True)["Close"].iloc[:, 0],  # High-Yield Credit
            "DXY":    yf.download("DX-Y.NYB", period="2y", interval="1d", progress=False, auto_adjust=True)["Close"].iloc[:, 0],  # Dollar-Index
        }

        spy = tickers["SPY"]
        dax = tickers["DAX"]
        vix = tickers["VIX"]
        hyg = tickers["HYG"]
        dxy = tickers["DXY"]

        # ── 20-Tage Returns (US + EU getrennt) ──────────────────────────────
        spy_ret = spy.pct_change(20).dropna()
        dax_ret = dax.pct_change(20).dropna()

        # ── US Regime (60% Gewicht) ──────────────────────────────────────────
        vol_spy = spy_ret.std()
        def classify_us(ret):
            if vol_spy == 0: return "sideways"
            z = ret / vol_spy
            return "bull" if z > 0.5 else "bear" if z < -0.5 else "sideways"

        # ── EU Regime (40% Gewicht) ──────────────────────────────────────────
        vol_dax = dax_ret.std()
        def classify_eu(ret):
            if vol_dax == 0: return "sideways"
            z = ret / vol_dax
            return "bull" if z > 0.5 else "bear" if z < -0.5 else "sideways"

        # ── Makro-Overlay-Score (−2 bis +2) ──────────────────────────────────
        def macro_overlay_score():
            """
            Addiert Punkte basierend auf:
              VIX < 18  → +1 (risikofreudig)  | VIX > 28 → −1 (risikoscheu)
              HYG 20d   → +1 wenn steigend     | fallend  → −1 (Credit Spreads)
              DXY 20d   → −0.5 wenn steigend   | fallend  → +0.5 (schwacher Dollar = Risk-On)
            """
            score = 0.0
            # VIX
            try:
                vix_now = float(vix.iloc[-1])
                if vix_now < 18:   score += 1.0
                elif vix_now > 28: score -= 1.0
                print(f"  VIX: {vix_now:.1f} → overlay {'+1' if vix_now < 18 else ('-1' if vix_now > 28 else '0')}", flush=True)
            except Exception: pass
            # Credit Spreads (HYG)
            try:
                hyg_ret = float(hyg.pct_change(20).dropna().iloc[-1])
                if hyg_ret > 0.01:   score += 1.0   # HYG steigt = Spreads eng = Risk-On
                elif hyg_ret < -0.01: score -= 1.0
                print(f"  HYG 20d: {hyg_ret:+.1%} → overlay {'+1' if hyg_ret > 0.01 else ('-1' if hyg_ret < -0.01 else '0')}", flush=True)
            except Exception: pass
            # Dollar-Index
            try:
                dxy_ret = float(dxy.pct_change(20).dropna().iloc[-1])
                if dxy_ret > 0.02:    score -= 0.5   # starker Dollar = Risk-Off
                elif dxy_ret < -0.02: score += 0.5
                print(f"  DXY 20d: {dxy_ret:+.1%} → overlay {'-0.5' if dxy_ret > 0.02 else ('+0.5' if dxy_ret < -0.02 else '0')}", flush=True)
            except Exception: pass
            return round(score, 2)

        overlay = macro_overlay_score()

        # ── Gemeinsamer Index + kombinierter Return ───────────────────────────
        common = spy_ret.index.intersection(dax_ret.index)
        spy_ret = spy_ret[common]
        dax_ret = dax_ret[common]
        combined = (spy_ret * 0.6 + dax_ret * 0.4)   # US 60% / EU 40%

        vol_20d = combined.std()
        def classify(ret):
            if vol_20d == 0: return "sideways"
            z_score = ret / vol_20d
            return "bull" if z_score > 0.5 else "bear" if z_score < -0.5 else "sideways"

        regimes = combined.apply(classify)

        # ── Makro-Overlay auf aktuelles Regime anwenden ───────────────────────
        # Overlay ≥ +1.5 → bull-Bias, ≤ −1.5 → bear-Bias
        base_regime = regimes.iloc[-1]
        if overlay >= 1.5 and base_regime == "sideways":
            current_regime = "bull"
            print(f"  Overlay +{overlay}: sideways → bull (makro-adjustiert)", flush=True)
        elif overlay <= -1.5 and base_regime in ("sideways", "bull"):
            current_regime = "bear"
            print(f"  Overlay {overlay}: {base_regime} → bear (makro-adjustiert)", flush=True)
        else:
            current_regime = base_regime

        # Rolling 252d Transition Matrix
        window = min(252, len(regimes))
        recent = regimes.iloc[-window:]

        transitions = {"bull": {"bull":0,"bear":0,"sideways":0},
                      "bear": {"bull":0,"bear":0,"sideways":0},
                      "sideways":{"bull":0,"bear":0,"sideways":0}}

        for i in range(len(recent)-1):
            from_state = recent.iloc[i]
            to_state   = recent.iloc[i+1]
            transitions[from_state][to_state] += 1

        # Normalisieren → Wahrscheinlichkeiten
        probs = {}
        for state, counts in transitions.items():
            total = sum(counts.values()) or 1
            probs[state] = {k: round(v/total, 3) for k, v in counts.items()}

        # Aktuelles Regime
        current_regime = regimes.iloc[-1]
        current_spy    = round(float(spy_ret.iloc[-1]), 4)
        current_dax    = round(float(dax_ret.iloc[-1]), 4)

        # n-Step Wahrscheinlichkeiten (1 Woche = 5 Tage)
        curr_probs = probs.get(current_regime, {"bull":0.33,"bear":0.33,"sideways":0.34})

        print(f"  Aktuelles Regime: {current_regime.upper()}", flush=True)
        print(f"  SPY 20d Return:   {current_spy:.1%}", flush=True)
        print(f"  DAX 20d Return:   {current_dax:.1%}", flush=True)
        print(f"  Nächste Woche:    Bull={curr_probs.get('bull',0):.0%} "
              f"Bear={curr_probs.get('bear',0):.0%} "
              f"Sideways={curr_probs.get('sideways',0):.0%}", flush=True)

        # In DB speichern
        today = datetime.now().strftime("%Y-%m-%d")
        # Migration: neue Spalten falls noch nicht vorhanden
        existing_cols = [r[1] for r in con.execute("PRAGMA table_info(regime_history)").fetchall()]
        for col_def in [
            ("regime_us",     "TEXT"),
            ("regime_eu",     "TEXT"),
            ("macro_overlay", "REAL"),
            ("vix",           "REAL"),
        ]:
            if col_def[0] not in existing_cols:
                con.execute(f"ALTER TABLE regime_history ADD COLUMN {col_def[0]} {col_def[1]}")

        con.execute("""
            INSERT OR REPLACE INTO regime_history
            (date, regime, spy_return, dax_return,
             bull_prob, bear_prob, sideways_prob,
             regime_us, regime_eu, macro_overlay, vix,
             created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (today, current_regime, current_spy, current_dax,
              curr_probs.get("bull", 0), curr_probs.get("bear", 0),
              curr_probs.get("sideways", 0),
              classify_us(float(spy_ret.iloc[-1])),
              classify_eu(float(dax_ret.iloc[-1])),
              overlay,
              round(float(vix.iloc[-1]), 1) if len(vix) > 0 else None,
              datetime.now().isoformat()))
        con.commit()

        # In macro_signal.json schreiben
        import json as _json
        macro_file = MACRO_SIGNAL_PATH
        try:
            with open(macro_file) as f:
                macro = _json.load(f)
        except Exception:
            macro = {}

        macro["regime"]        = current_regime
        macro["regime_probs"]  = curr_probs
        macro["spy_return"]    = current_spy
        macro["dax_return"]    = current_dax
        macro["regime_us"]     = classify_us(float(spy_ret.iloc[-1]))
        macro["regime_eu"]     = classify_eu(float(dax_ret.iloc[-1]))
        macro["macro_overlay"] = overlay
        macro["vix"]           = round(float(vix.iloc[-1]), 1) if len(vix) > 0 else None
        macro["regime_updated"] = datetime.now().isoformat()

        with open(macro_file, "w") as f:
            _json.dump(macro, f, indent=2)

        return current_regime, curr_probs

    except Exception as e:
        print(f"  ✗ Regime-Detection fehlgeschlagen: {e}", flush=True)
        return "sideways", {"bull": 0.33, "bear": 0.33, "sideways": 0.34}


def update_benchmark(con):
    """
    Phase 5: Benchmark-Tracking — SPY und DAX täglich festhalten.
    Berechnet Alpha des Portfolios gegenüber Buy-and-Hold SPY und DAX.
    """
    print("\n📊 Benchmark-Tracking aktualisieren...", flush=True)
    try:
        import yfinance as yf
        today = datetime.now().strftime("%Y-%m-%d")

        # Schema sicherstellen
        con.executescript("""
            CREATE TABLE IF NOT EXISTS benchmark (
                date TEXT PRIMARY KEY,
                spy_close REAL,
                dax_close REAL,
                portfolio_value REAL,
                spy_return_ytd REAL,
                dax_return_ytd REAL,
                portfolio_return_ytd REAL,
                alpha_spy REAL,
                alpha_dax REAL
            );
        """)

        def get_close(df, idx=-1):
            """
            Extrahiert Close-Preis robust aus yfinance DataFrame.
            Neuere yfinance-Versionen liefern Multi-Level-Columns
            (z.B. ("Close","SPY")) statt einfach "Close".
            """
            if df.empty:
                return None
            col = df["Close"]
            # Multi-Level: col ist ein DataFrame → erste Spalte nehmen
            if hasattr(col, "iloc") and hasattr(col.iloc[0], "__len__"):
                val = col.iloc[idx]
                if hasattr(val, "iloc"):
                    val = val.iloc[0]
            else:
                val = col.iloc[idx]
            return float(val)

        spy_data = yf.download("SPY",    period="5d", interval="1d",
                               progress=False, auto_adjust=True)
        dax_data = yf.download("^GDAXI", period="5d", interval="1d",
                               progress=False, auto_adjust=True)

        if spy_data.empty or dax_data.empty:
            print("  ⚠ Keine Benchmark-Daten verfügbar")
            return

        spy_close = get_close(spy_data)
        dax_close = get_close(dax_data)

        if spy_close is None or dax_close is None:
            print("  ⚠ Close-Preis konnte nicht extrahiert werden")
            return

        portfolio = con.execute("SELECT total_value FROM portfolio WHERE id=1").fetchone()
        portfolio_value = float(portfolio[0]) if portfolio else 10000.0

        # Jahresanfangs-Werte für YTD-Return
        jan1 = f"{datetime.now().year}-01-01"
        spy_jan = yf.download("SPY",    start=jan1, end=f"{datetime.now().year}-01-31",
                              interval="1d", progress=False, auto_adjust=True)
        dax_jan = yf.download("^GDAXI", start=jan1, end=f"{datetime.now().year}-01-31",
                              interval="1d", progress=False, auto_adjust=True)

        spy_start = get_close(spy_jan, idx=0) or spy_close
        dax_start = get_close(dax_jan, idx=0) or dax_close

        # Portfolio-Startkapital aus config
        import json as _j
        cfg_path = STRATEGY_CONFIG_PATH
        starting_capital = 10000.0
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                starting_capital = _j.load(f).get("starting_capital", 10000.0)

        spy_return_ytd  = round((spy_close / spy_start - 1) * 100, 2)
        dax_return_ytd  = round((dax_close / dax_start - 1) * 100, 2)
        port_return_ytd = round((portfolio_value / starting_capital - 1) * 100, 2)
        alpha_spy = round(port_return_ytd - spy_return_ytd, 2)
        alpha_dax = round(port_return_ytd - dax_return_ytd, 2)

        con.execute("""
            INSERT OR REPLACE INTO benchmark
            (date, spy_close, dax_close, portfolio_value,
             spy_return_ytd, dax_return_ytd, portfolio_return_ytd, alpha_spy, alpha_dax)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (today, spy_close, dax_close, portfolio_value,
              spy_return_ytd, dax_return_ytd, port_return_ytd,
              alpha_spy, alpha_dax))
        con.commit()

        alpha_spy_icon  = "✅" if alpha_spy >= 0 else "❌"
        alpha_dax_icon  = "✅" if alpha_dax >= 0 else "❌"
        print(f"  Portfolio YTD: {port_return_ytd:+.1f}%", flush=True)
        print(f"  SPY YTD:       {spy_return_ytd:+.1f}% | Alpha: {alpha_spy:+.1f}% {alpha_spy_icon}", flush=True)
        print(f"  DAX YTD:       {dax_return_ytd:+.1f}% | Alpha: {alpha_dax:+.1f}% {alpha_dax_icon}", flush=True)

    except Exception as e:
        print(f"  ⚠ Benchmark-Tracking Fehler: {e}", flush=True)


def main():
    print("📡 Fundamental Data Collector gestartet", flush=True)
    con = db_connect()
    try:
        config = load_config()

        # 1. FRED Makrodaten
        fetch_fred_data(con, config["fred_indicators"])

        # 2. Watchlist-Ticker für Insider + PCR
        watchlist_tickers = [
            r[0] for r in con.execute("""
                SELECT DISTINCT ticker FROM watchlist
                WHERE status='watching'
                AND ticker IS NOT NULL
                AND conviction_score >= 0.5
                ORDER BY conviction_score DESC
                LIMIT 30
            """).fetchall()
        ]
        print(f"\n  Watchlist-Ticker für Analyse: {len(watchlist_tickers)}", flush=True)

        # 3. SEC Insider Trades
        fetch_insider_trades(con, watchlist_tickers)

        # 4. Put/Call Ratio
        fetch_pcr(con, watchlist_tickers)

        # 5. Makro-Zusammenfassung
        macro_signal = get_macro_summary(con)
        print(f"\n  🌍 Gesamt-Makrosignal: {macro_signal.upper()}", flush=True)

        # 6. Regime-Detection
        regime, regime_probs = detect_market_regime(con)

        # 7. Benchmark-Tracking (Phase 5)
        update_benchmark(con)

        # Makrosignal speichern für signal_manager
        import json as _json
        macro_file = MACRO_SIGNAL_PATH
        with open(macro_file) as f:
            macro_data = _json.load(f) if os.path.exists(macro_file) else {}
        macro_data.update({
            "signal":  macro_signal,
            "regime":  regime,
            "updated": datetime.now().isoformat()
        })
        with open(macro_file, "w") as f:
            _json.dump(macro_data, f, indent=2)

        print("\n✅ Fundamental Data Collector abgeschlossen", flush=True)
    finally:
        con.close()

if __name__ == "__main__":
    main()
