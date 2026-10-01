"""
Polymarket Client — dünner Wrapper um den bestehenden Hermes-Polymarket-Skill.
Importiert direkt aus dem Hermes-Research-Skill statt eigene Implementierung.
"""
import sys
import json
import time

import os

# FIX 28.09.2026: der alte Pfad im hermes-agent existiert nach einem Agent-Update
# nicht mehr (ModuleNotFoundError 'polymarket' -> thesis_monitor und
# prediction_market_scanner starteten nicht). Erster vorhandener Pfad gewinnt.
_PM_CANDIDATES = (
    "/root/.hermes/profiles/hermes_trading/skills/research/polymarket/scripts",
    "/root/.hermes/hermes-agent/optional-skills/finance/polymarket/scripts",
    "/root/.hermes/hermes-agent/skills/research/polymarket/scripts",
)
HERMES_PM_PATH = next((p for p in _PM_CANDIDATES if os.path.isdir(p)), _PM_CANDIDATES[0])
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
            tokens = _parse_json_field(m.get("clobTokenIds", "[]"))
            token_id = str(tokens[0]) if isinstance(tokens, list) and tokens else ""
            result.append({
                "market_id":        m.get("conditionId", ""),
                "token_id":         token_id,       # M18: die CLOB-History braucht die Token-ID, nicht die conditionId
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

def fetch_market_history(market_ref: str, interval: str = "1w", fidelity: int = 60) -> list:
    """Preisverlauf eines Markets: Liste {"t": Unix-Sekunden, "p": Preis}.

    M18 (30.09.2026): `market_ref` muss die CLOB-Token-ID (YES-Token) sein. Mit der conditionId lieferte die Abfrage
    0 Datenpunkte (Probe: mit Token-ID 1.440). `fidelity` in Minuten (60 = stündlich)."""
    try:
        data = _get(f"{CLOB}/prices-history?market={market_ref}&interval={interval}&fidelity={fidelity}")
        return data.get("history", [])
    except BaseException:       # _get beendet den Prozess per sys.exit() bei HTTP-Fehlern
        return []


def price_days_ago(history: list, days: float, now_ts: float = None, tolerance_days: float = 1.0):
    """Preis, der `days` Tage vor jetzt galt, oder None, wenn die Historie nicht so weit zurückreicht.

    M18: vorher wurde history[-2] als "Preis vor 7 Tagen" genommen (bei stündlichen Punkten: vor einer Stunde)."""
    if not history:
        return None
    now_ts = time.time() if now_ts is None else now_ts
    target = now_ts - days * 86400
    points = [(float(h["t"]), h["p"]) for h in history if h.get("p") not in (None, "")]
    if not points or min(t for t, _ in points) > target + tolerance_days * 86400:
        return None
    t, p = min(points, key=lambda tp: abs(tp[0] - target))
    return float(p)


def enrich_with_history(markets: list, max_markets: int = 60) -> list:
    """Ergänzt price_7d_ago, price_30d_ago und delta_7d für die `max_markets` größten Märkte (nach 24h-Volumen).
    Ohne Historie bleiben die Werte None (nicht 0)."""
    ranked = sorted(markets, key=lambda m: m.get("volume_24h_usd", 0) or 0, reverse=True)[:max_markets]
    for m in ranked:
        ref = m.get("token_id") or ""
        m.setdefault("price_7d_ago", None)
        m.setdefault("price_30d_ago", None)
        m.setdefault("delta_7d", None)
        if not ref:
            continue
        cur = m.get("current_yes_price")
        p7 = price_days_ago(fetch_market_history(ref, "1w", 60), 7)
        p30 = price_days_ago(fetch_market_history(ref, "1m", 720), 30, tolerance_days=2.0)
        m["price_7d_ago"], m["price_30d_ago"] = p7, p30
        if p7 is not None and cur is not None:
            m["delta_7d"] = round(cur - p7, 3)
    return markets

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
            history = fetch_market_history(m.get('token_id') or m['market_id'], interval='1w')
            old_price = price_days_ago(history, 7)
            if old_price is not None:
                new_price = m['current_yes_price']
                delta = abs(new_price - old_price)
                if delta >= min_delta_7d:
                    m['delta_7d'] = round(new_price - old_price, 3)
                    result.append(m)
        except Exception:
            pass
    result.sort(key=lambda x: abs(x.get('delta_7d', 0)), reverse=True)
    return result[:limit]
