"""
Tavily Client — News-Aggregation via Tavily Search API.
Free Tier: 1000 queries/Monat.
"""
import os
import time
import json
import requests
from pathlib import Path
from typing import Optional
from thematic.lib import env_loader  # noqa: F401 (Side-effect: laedt .env)

TAVILY_KEY = os.environ.get("TAVILY_API_KEY")
TAVILY_URL = "https://api.tavily.com/search"

_last_call = 0
MIN_INTERVAL = 2.0  # Sekunden zwischen Calls (Free-Tier-Limit)

# M17 (30.09.2026): `days` wirkt bei Tavily nur zusammen mit topic="news". Ohne topic lieferte die Suche Kursseiten
# ohne Datum (Probe "Qualys QLYS news"). Mit topic=news und days=1 kamen frische, aber meist irrelevante Artikel;
# sinnvoll ist ein Fenster von 7 Tagen plus Namensfilter (filter_relevant). Anpassbar per TAVILY_NEWS_DAYS.
try:
    NEWS_DAYS = max(1, int(os.environ.get("TAVILY_NEWS_DAYS", "7")))
except ValueError:
    NEWS_DAYS = 7

_NAME_STOPWORDS = {
    "inc", "corp", "corporation", "company", "holdings", "holding", "group", "limited", "ltd", "plc", "the", "and",
    "aktiengesellschaft", "stock", "news", "analyst", "earnings", "international", "technologies", "technology",
    "systems", "services", "global", "partners", "industries",
}


def _name_terms(names) -> set:
    import re
    terms = set()
    for n in names or []:
        for t in re.findall(r"[a-z0-9]+", (n or "").lower()):
            if len(t) >= 5 and t not in _NAME_STOPWORDS:
                terms.add(t)
    return terms


def filter_relevant(results: list, names=None, ticker: Optional[str] = None) -> list:
    """Behält nur Treffer, in deren Titel/Text ein Namenswort (>= 5 Zeichen) oder das Tickersymbol (>= 3 Zeichen,
    ganzes Wort) vorkommt. Ohne Namen und Ticker bleibt alles erhalten."""
    import re
    terms = _name_terms(names)
    sym = (ticker or "").split(".")[0].upper()
    if not terms and len(sym) < 3:
        return list(results)
    kept = []
    for r in results:
        blob = f"{r.get('title', '')} {r.get('content', '')}"
        low = blob.lower()
        if any(re.search(rf"\b{re.escape(t)}", low) for t in terms):
            kept.append(r)
        elif len(sym) >= 3 and re.search(rf"\b{re.escape(sym)}\b", blob):
            kept.append(r)
    return kept


def _rate_limit():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call = time.time()


def search_news(
    query: str,
    search_depth: str = "basic",
    max_results: int = 10,
    include_domains: Optional[list] = None,
    days: Optional[int] = None,
) -> list:
    """
    Fuehrt eine Tavily-Suche durch.

    Args:
        query: Suchbegriff
        search_depth: 'basic' oder 'advanced' (advanced verbraucht mehr Credits)
        max_results: 5-20 (Free Tier max 10 empfohlen)
        include_domains: Optional Liste von Domains (z.B. ['bloomberg.com'])
        days: Zeitfenster in Tagen

    Returns: Liste von {"title": ..., "url": ..., "content": ..., "score": ...}
    """
    if not TAVILY_KEY:
        print("[Tavily] TAVILY_API_KEY nicht gesetzt – ueberspringe")
        return []

    _rate_limit()

    payload = {
        "api_key": TAVILY_KEY,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": False,
        "topic": "news",
        "days": days if days else NEWS_DAYS,
    }
    if include_domains:
        payload["include_domains"] = include_domains

    for attempt in range(3):
        try:
            resp = requests.post(TAVILY_URL, json=payload, timeout=20)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
        except Exception as e:
            if attempt == 2:
                print(f"[Tavily] Fehler bei '{query}': {e}")
                return []
            time.sleep(2)

    return []


def fetch_theme_news() -> list:
    """Sammelt News fuer Theme-Discovery mit kuratierten Queries."""
    queries = [
        "market moving news today financial",
        "sector rotation institutional flows",
        "emerging investment theme structural",
    ]
    all_results = []
    seen_urls = set()

    for q in queries:
        results = search_news(q, max_results=8)
        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    return all_results


def fetch_ticker_news(ticker: str, days: Optional[int] = None, company_name: Optional[str] = None) -> list:
    """Sammelt aktuelle News zu einem Ticker (M17: topic=news, Fenster NEWS_DAYS, nur relevante Treffer)."""
    queries = [
        f"{company_name or ticker} {ticker} stock news",
        f"{company_name or ticker} analyst earnings",
    ]
    all_results = []
    seen_urls = set()

    for q in queries:
        results = search_news(q, max_results=5, days=days)
        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    return filter_relevant(all_results, [company_name] if company_name else None, ticker)
