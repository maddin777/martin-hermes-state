"""
Finnhub Client — Fundamentaldaten, Earnings, Insider-Trades.
Free Tier: 60 calls/min.
"""
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import time
import requests
from typing import Optional

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY")
FINNHUB_URL = "https://finnhub.io/api/v1"

# Sliding-Window Rate Limiter: max 50 calls pro 60s (Free Tier = 60/min, ~17% Puffer)
from collections import deque
_call_timestamps = deque()
MAX_CALLS_PER_WINDOW = 50
WINDOW_SECONDS = 60


def _rate_limit():
    """Sliding-Window Rate Limiter — blockiert wenn >50 Calls in den letzten 60s."""
    global _call_timestamps
    now = time.time()
    cutoff = now - WINDOW_SECONDS

    # Alte Einträge rauswerfen
    while _call_timestamps and _call_timestamps[0] < cutoff:
        _call_timestamps.popleft()

    if len(_call_timestamps) >= MAX_CALLS_PER_WINDOW:
        # Warte bis das Fenster wieder frei ist (ältester Timestamp + 60s - jetzt)
        wait = _call_timestamps[0] + WINDOW_SECONDS - now + 0.5  # +0.5s Puffer
        if wait > 0:
            print(f"[Finnhub] ⏳ Rate-Limit erreicht ({MAX_CALLS_PER_WINDOW}/60s) → warte {wait:.0f}s")
            time.sleep(wait)
        # Nach dem Warten nochmal aufräumen
        while _call_timestamps and _call_timestamps[0] < now - WINDOW_SECONDS:
            _call_timestamps.popleft()

    _call_timestamps.append(time.time())

MAX_RETRIES = 2

def _get(endpoint: str, params: Optional[dict] = None) -> dict:
    if not FINNHUB_KEY:
        return {}
    params = params or {}
    params["token"] = FINNHUB_KEY

    for attempt in range(MAX_RETRIES):
        _rate_limit()
        try:
            resp = requests.get(f"{FINNHUB_URL}{endpoint}", params=params, timeout=15)
            if resp.status_code == 429 or resp.status_code == 403:
                wait = 3 * (attempt + 1)
                print(f"[Finnhub] ⚠️ {endpoint}: {resp.status_code} (Rate-Limit) → retry in {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if attempt < MAX_RETRIES - 1:
                wait = 3 * (attempt + 1)
                print(f"[Finnhub] ⚠️ {endpoint}: {e} → retry in {wait}s")
                time.sleep(wait)
                continue
            print(f"[Finnhub] ⚠️ {endpoint}: {e}")
            return {}
        except Exception as e:
            print(f"[Finnhub] ⚠️ {endpoint}: {e}")
            return {}
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
