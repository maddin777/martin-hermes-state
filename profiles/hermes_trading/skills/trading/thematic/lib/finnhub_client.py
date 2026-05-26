"""
Finnhub Client — Fundamentaldaten, Earnings, Insider-Trades.
Free Tier: 60 calls/min.
"""
import os
import time
import requests
from typing import Optional

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY")
FINNHUB_URL = "https://finnhub.io/api/v1"

_last_call = 0
MIN_INTERVAL = 1.1  # Sekunden (60/min ~ 1s pro Call)


def _rate_limit():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call = time.time()


def _get(endpoint: str, params: Optional[dict] = None) -> dict:
    if not FINNHUB_KEY:
        return {}
    params = params or {}
    params["token"] = FINNHUB_KEY
    _rate_limit()
    try:
        resp = requests.get(f"{FINNHUB_URL}{endpoint}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[Finnhub] Fehler {endpoint}: {e}")
        return {}


def get_company_profile(ticker: str) -> dict:
    """Company Profile v2: marketCap, industry, exchange."""
    return _get("/stock/profile2", {"symbol": ticker})


def get_basic_financials(ticker: str) -> dict:
    """Basic Financials: PE, ROE, Revenue Growth, etc."""
    return _get("/stock/metric", {"symbol": ticker, "metric": "all"})


def get_earnings_calendar(ticker: str, from_date: str = None,
                          to_date: str = None) -> dict:
    """Earnings Calendar."""
    params = {"symbol": ticker}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return _get("/calendar/earnings", params)


def get_peers(ticker: str) -> list:
    """Sektor-Peers eines Tickers."""
    return _get("/stock/peers", {"symbol": ticker})


def get_insider_transactions(ticker: str) -> dict:
    """SEC Form 4 Insider-Transaktionen."""
    return _get("/stock/insider-transactions", {"symbol": ticker})


def get_short_interest(ticker: str) -> float:
    """Short Interest in Prozent."""
    data = _get("/stock/short-interest", {"symbol": ticker})
    if isinstance(data, list) and data:
        return float(data[0].get("shortPercentOfFloat", 0)) * 100
    return 0.0


def get_quote(ticker: str) -> dict:
    """Aktueller Quote: current price, change, high, low."""
    return _get("/quote", {"symbol": ticker})


def get_recommendation_trends(ticker: str) -> list:
    """Analyst Recommendation Trends."""
    return _get("/stock/recommendation", {"symbol": ticker})