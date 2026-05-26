"""
Factor Ranker — Multi-Faktor-Ranking ueber das Anlage-Universum (~800 Ticker).
Faktoren: Momentum, Quality, Value, Revision, Low Vol.
"""
import json
import os
import sqlite3
import numpy as np
from datetime import date

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)

THEMATIC_DIR = os.path.dirname(__file__)
UNIVERSE_PATH = os.path.join(THEMATIC_DIR, "config", "universe.json")
CONFIG_PATH = os.path.join(THEMATIC_DIR, "config", "thematic_config.json")


def _load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _fetch_price_data(ticker: str):
    """Holt 1 Jahr Kursdaten fuer den Ticker."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        close = df["Close"].iloc[:, 0]
        high = df["High"].iloc[:, 0]
        low = df["Low"].iloc[:, 0]
        volume = df["Volume"].iloc[:, 0]
        return {"close": close, "high": high, "low": low, "volume": volume}
    except Exception:
        return None


def _compute_momentum_score(close, idx: int = -1) -> float:
    """6M-Return minus 1M-Return, Perzentil."""
    if len(close) < 126:
        return 0.5
    ret_6m = (close.iloc[idx] / close.iloc[max(0, idx - 126)] - 1) if idx >= 0 else 0
    ret_1m = (close.iloc[idx] / close.iloc[max(0, idx - 21)] - 1) if idx >= 0 else 0
    return ret_6m - ret_1m


def _compute_quality_score(ticker: str) -> float:
    """ROIC + (1 - Debt/Equity) aus Finnhub."""
    from thematic.lib import finnhub_client
    metrics = finnhub_client.get_basic_financials(ticker)
    metric = metrics.get("metric", {}) if metrics else {}
    roic = metric.get("roicTTM") or 0
    debt_eq = metric.get("totalDebt/totalEquityQuarterly") or 1
    if debt_eq is None or debt_eq <= 0:
        debt_eq = 1
    quality = float(roic) + (1.0 - min(float(debt_eq), 1.0))
    return max(0, quality)


def _compute_value_score(ticker: str) -> float:
    """FCF Yield."""
    from thematic.lib import finnhub_client
    metrics = finnhub_client.get_basic_financials(ticker)
    metric = metrics.get("metric", {}) if metrics else {}
    fcf = metric.get("freeCashFlowTTM")
    mc = metric.get("marketCapitalization")
    if fcf and mc and mc > 0:
        return float(fcf) / (float(mc) * 1_000_000)
    return 0


def _compute_revision_score(ticker: str) -> float:
    """Analysten-Revision via Finnhub Recommendations."""
    from thematic.lib import finnhub_client
    recs = finnhub_client.get_recommendation_trends(ticker)
    if not recs or len(recs) < 2:
        return 0
    # Vereinfacht: Trend der Buy vs Sell ueber 2 Monate
    current = recs[0]
    prev = recs[1] if len(recs) > 1 else current
    cur_buy = (current.get("strongBuy", 0) or 0) + (current.get("buy", 0) or 0)
    prev_buy = (prev.get("strongBuy", 0) or 0) + (prev.get("buy", 0) or 0)
    return (cur_buy - prev_buy) / max(prev_buy, 1)


def _compute_lowvol_score(close) -> float:
    """1/Volatilitaet(60d)."""
    if len(close) < 60:
        return 0
    returns = close.pct_change().dropna().iloc[-60:]
    vol = returns.std()
    return 1.0 / max(vol, 0.01)


def _percentile(values: list) -> list:
    """Konvertiert Rohwerte zu Perzentil-Ranks (0-1)."""
    arr = np.array([v for v in values if v is not None])
    if len(arr) == 0:
        return [0.5] * len(values)
    ranks = [np.sum(arr <= v) / len(arr) if v is not None else 0.5
             for v in values]
    return ranks


def main():
    con = _db_connect()
    cfg = _load_config()
    weights = cfg.get("factor_weights", {})
    today = date.today().isoformat()

    # Universum laden
    with open(UNIVERSE_PATH) as f:
        universe = json.load(f)

    print(f"[Factor Ranker] Universum: {len(universe)} Ticker", flush=True)

    # Alle Rohdaten sammeln
    results = []
    for ticker in universe[:200]:  # Limit auf 200 fuer Geschwindigkeit
        data = _fetch_price_data(ticker)
        if data is None:
            continue

        close = data["close"]

        mom = _compute_momentum_score(close)
        qual = _compute_quality_score(ticker)
        val = _compute_value_score(ticker)
        rev = _compute_revision_score(ticker)
        lowvol = _compute_lowvol_score(close)

        results.append({
            "ticker": ticker,
            "momentum_raw": mom,
            "quality_raw": qual,
            "value_raw": val,
            "revision_raw": rev,
            "lowvol_raw": lowvol,
        })

    if not results:
        print("[Factor Ranker] Keine validen Ticker.")
        con.close()
        return

    # Perzentil-Ranks
    mom_values = [r["momentum_raw"] for r in results]
    qual_values = [r["quality_raw"] for r in results]
    val_values = [r["value_raw"] for r in results]
    rev_values = [r["revision_raw"] for r in results]
    lowvol_values = [r["lowvol_raw"] for r in results]

    mom_rank = _percentile(mom_values)
    qual_rank = _percentile(qual_values)
    val_rank = _percentile(val_values)
    rev_rank = _percentile(rev_values)
    lowvol_rank = _percentile(lowvol_values)

    # Composite Score
    for i, r in enumerate(results):
        composite = (
            mom_rank[i] * weights.get("momentum", 0.30) +
            qual_rank[i] * weights.get("quality", 0.25) +
            val_rank[i] * weights.get("value", 0.20) +
            rev_rank[i] * weights.get("revision", 0.15) +
            lowvol_rank[i] * weights.get("lowvol", 0.10)
        ) * 100

        r["momentum_score"] = round(mom_rank[i], 4)
        r["quality_score"] = round(qual_rank[i], 4)
        r["value_score"] = round(val_rank[i], 4)
        r["revision_score"] = round(rev_rank[i], 4)
        r["lowvol_score"] = round(lowvol_rank[i], 4)
        r["composite_score"] = round(composite, 2)

    # Rank
    results.sort(key=lambda x: x["composite_score"], reverse=True)
    for rank, r in enumerate(results, 1):
        r["rank"] = rank

    # Write to DB
    for r in results:
        con.execute("DELETE FROM factor_scores WHERE date = ? AND ticker = ?",
                     (today, r["ticker"]))
        con.execute("""
            INSERT INTO factor_scores
            (date, ticker, momentum_score, quality_score, value_score,
             revision_score, lowvol_score, composite_score, rank_in_universe)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            today, r["ticker"],
            r["momentum_score"], r["quality_score"], r["value_score"],
            r["revision_score"], r["lowvol_score"],
            r["composite_score"], r["rank"],
        ))

    con.commit()
    con.close()

    top5 = results[:5]
    names = ", ".join(f"{r['ticker']}({r['composite_score']:.0f})" for r in top5)
    print(f"[Factor Ranker] DONE. Top 5: {names}", flush=True)


if __name__ == "__main__":
    main()