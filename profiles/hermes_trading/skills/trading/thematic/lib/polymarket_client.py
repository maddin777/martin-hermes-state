"""
Polymarket Client — dünner Wrapper um den bestehenden Hermes-Polymarket-Skill.
Importiert direkt aus dem Hermes-Research-Skill statt eigene Implementierung.
"""
import sys
import json

HERMES_PM_PATH = "/root/.hermes/hermes-agent/skills/research/polymarket/scripts"
if HERMES_PM_PATH not in sys.path:
    sys.path.insert(0, HERMES_PM_PATH)

from polymarket import _get, _parse_json_field, _fmt_pct, _fmt_volume, GAMMA, CLOB


def _categorize_market(question: str, event_title: str) -> str:
    """Keyword-basierte Kategorisierung für Polymarket-Märkte."""
    text = (question + " " + event_title).lower()
    # Sport zuerst prüfen (höchste Priorität für Ausschluss)
    if any(k in text for k in ["world cup", "fifa", "nba", "nfl", "nhl", "mlb", "oscar", "grammy", "super bowl", "champion", "tournament", "win the", "game 7", "formula 1", "f1 ", "wimbledon"]):
        return "sport"
    if any(k in text for k in ["fed", "rate", "inflation", "gdp", "recession", "cpi", "employment", "jobs"]):
        return "economics"
    if any(k in text for k in ["election", "president", "senate", "congress", "vote", "poll", "trump", "biden", "harris"]):
        return "politics"
    if any(k in text for k in ["war", "ceasefire", "nato", "sanctions", "tariff", "china", "russia", "ukraine", "iran", "israel", "taiwan"]):
        return "geopolitics"
    if any(k in text for k in ["ai", "openai", "nvidia", "sec", "crypto", "bitcoin", "regulation", "antitrust", "merger", "ipo"]):
        return "tech"
    if any(k in text for k in ["fda", "drug", "approval", "climate", "carbon", "ban"]):
        return "regulatory"
    return "other"

def fetch_trending_markets(limit: int = 50, min_volume: float = 100_000) -> list:
    """Trending Events nach Volumen, gefiltert auf Mindest-Volumen."""
    events = _get(f"{GAMMA}/events?limit={limit}&active=true&closed=false&order=volume&ascending=false")
    result = []
    for evt in events:
        vol = float(evt.get("volume", 0))
        if vol < min_volume:
            continue
        for m in evt.get("markets", []):
            m_vol = float(m.get("volume", 0))
            if m_vol < 5_000:
                continue
            prices = _parse_json_field(m.get("outcomePrices", "[]"))
            yes_price = float(prices[0]) if isinstance(prices, list) and prices else 0.0
            result.append({
                "market_id":        m.get("conditionId", ""),
                "question":         m.get("question", ""),
                "category":         _categorize_market(m.get("question", ""), evt.get("title", "")),
                "resolution_date":  m.get("endDate", "")[:10] if m.get("endDate") else None,
                "current_yes_price": yes_price,
                "volume_24h_usd":   m_vol,
                "total_volume_usd": vol,
                "slug":             m.get("slug", ""),
                "event_title":      evt.get("title", ""),
            })
    return result

def fetch_market_history(condition_id: str, interval: str = "1w") -> list:
    """Preisverlauf für einen Market (für delta_7d Berechnung)."""
    try:
        data = _get(f"{CLOB}/prices-history?market={condition_id}&interval={interval}&fidelity=7")
        return data.get("history", [])
    except Exception:
        return []

def search_markets(query: str, min_volume: float = 50_000) -> list:
    """Suche nach Markets per Keyword."""
    import urllib.parse
    q = urllib.parse.quote(query)
    data = _get(f"{GAMMA}/public-search?q={q}")
    result = []
    for evt in data.get("events", []):
        for m in evt.get("markets", []):
            vol = float(m.get("volume", 0))
            if vol < min_volume:
                continue
            prices = _parse_json_field(m.get("outcomePrices", "[]"))
            yes_price = float(prices[0]) if isinstance(prices, list) and prices else 0.0
            result.append({
                "market_id":         m.get("conditionId", ""),
                "question":          m.get("question", ""),
                "current_yes_price": yes_price,
                "total_volume_usd":  vol,
                "slug":              m.get("slug", ""),
            })
    return result


def fetch_top_movers(min_delta_7d: float = 0.10, limit: int = 10) -> list:
    """Märkte mit größter 7-Tage-Preisbewegung."""
    markets = fetch_trending_markets(limit=200, min_volume=100_000)
    relevant = [m for m in markets if m['category'] not in ('other', 'sport')]
    # delta_7d berechnen via History
    result = []
    for m in relevant[:50]:
        try:
            history = fetch_market_history(m['market_id'], interval='1w')
            if len(history) >= 2:
                old_price = float(history[-2]['p']) if history[-2]['p'] else 0
                new_price = m['current_yes_price']
                delta = abs(new_price - old_price)
                if delta >= min_delta_7d:
                    m['delta_7d'] = round(new_price - old_price, 3)
                    result.append(m)
        except Exception:
            pass
    result.sort(key=lambda x: abs(x.get('delta_7d', 0)), reverse=True)
    return result[:limit]
