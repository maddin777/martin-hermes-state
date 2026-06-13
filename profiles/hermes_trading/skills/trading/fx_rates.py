"""
FX Rates Client — Taegliche EUR-Referenzkurse via European Central Bank API.
Kostenlos, keine API-Key erforderlich.
"""
import time
import requests
from datetime import date
from typing import Optional

ECB_URL = "https://api.frankfurter.app"

_cache = {}
_cache_date = None


def fetch_rates(target_date: Optional[date] = None) -> dict:
    """
    Fetcht EUR-Wechselkurse von der Frankfurter API.

    Returns: {"EUR": 1.0, "USD": 1.08, "JPY": 156.0, ...}
    """
    global _cache, _cache_date

    today = target_date or date.today()
    if _cache and _cache_date == today:
        return _cache

    url = f"{ECB_URL}/latest"
    if target_date and target_date != date.today():
        url = f"{ECB_URL}/{target_date.isoformat()}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        rates["EUR"] = 1.0
        _cache = rates
        _cache_date = today
        return rates
    except Exception as e:
        print(f"[FX] Fehler bei fetch_rates: {e}")
        return _cache or {"EUR": 1.0, "USD": 1.08, "JPY": 156.0,
                          "GBP": 0.85, "NOK": 11.5, "CHF": 0.95, "SEK": 11.2}


def get_rate(currency: str) -> float:
    """Holt Kurs EUR → currency."""
    rates = fetch_rates()
    eur_in_target = rates.get(currency)
    if eur_in_target and eur_in_target > 0:
        return eur_in_target
    return 1.0


def convert_to_eur(amount: float, from_currency: str) -> float:
    """Rechnet Betrag von Fremdwaehrung in EUR um."""
    rate = get_rate(from_currency)
    if rate <= 0:
        return amount
    return amount / rate