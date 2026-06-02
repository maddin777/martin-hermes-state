"""
xAI x_search Helper via Hermes AIAgent
Nutzt Grok OAuth - kein separater API-Key nötig.
"""
import sys, os, json, re

sys.path.insert(0, '/root/.hermes/hermes-agent')

def _load_env():
    for env_path in [
        "/root/.hermes/profiles/hermes_trading/.env",
        "/root/.hermes/.env"
    ]:
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())

def _get_agent():
    _load_env()
    from run_agent import AIAgent
    return AIAgent(
        enabled_toolsets=["x_search"],
        quiet_mode=True,
        skip_memory=True,
    )

def x_search(query, hours=24, allowed_handles=None):
    """Fuehrt x_search via Hermes AIAgent aus."""
    try:
        time_hint  = "letzte {} Stunden".format(hours) if hours <= 24 else "letzte {} Tage".format(hours//24)
        handle_hint = "Accounts: {}.".format(', '.join(allowed_handles)) if allowed_handles else ""
        prompt = (
            'Suche auf X nach: "{}". '.format(query) +
            'Zeitraum: {}. {} '.format(time_hint, handle_hint) +
            'Antworte NUR mit validem JSON, keine Backticks: '
            '{"sentiment":"bullish|bearish|neutral","confidence":0.0,'
            '"mention_count":0,"top_signals":[],'
            '"breaking_news":false,"breaking_summary":null}'
        )
        agent    = _get_agent()
        response = agent.chat(prompt)
        m = re.search(r'\{.*\}', response, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return None
    except Exception as e:
        print("  x_search Fehler: {}".format(e), flush=True)
        return None


def conviction_boost(ticker, name, current_conviction):
    """Signal-Bestaetigung fuer Aktien mit Conviction >70%."""
    if current_conviction < 0.70:
        return current_conviction, "skipped"
    result = x_search("{} {} Aktie bullish Analyse".format(name, ticker), hours=24)
    if not result:
        return current_conviction, "no_result"
    sentiment  = result.get("sentiment", "neutral")
    confidence = result.get("confidence", 0.5)
    mentions   = result.get("mention_count", 0)
    if sentiment == "bullish" and mentions >= 2:
        boost    = min(0.10, confidence * 0.10)
        new_conv = min(1.0, current_conviction + boost)
        return new_conv, "boosted +{:.0%} (X: {} bullish Posts)".format(boost, mentions)
    elif sentiment == "bearish" and confidence > 0.6:
        penalty  = min(0.15, confidence * 0.15)
        new_conv = max(0.0, current_conviction - penalty)
        return new_conv, "reduced -{:.0%} (X: bearish Signal)".format(penalty)
    return current_conviction, "unchanged (X: {}, {} Posts)".format(sentiment, mentions)


def contradiction_check(name, ticker):
    """Gegencheck bei widersprüchlichen Signalen."""
    result = x_search("{} {} Aktie Meinung Analyse".format(name, ticker), hours=48)
    if not result:
        return "neutral", 0.5
    return result.get("sentiment", "neutral"), result.get("confidence", 0.5)


def breaking_news_check(ticker, name):
    """Breaking News Filter vor Kauf."""
    result = x_search("{} {}".format(ticker, name), hours=6)
    if not result:
        return False, None
    has_news   = result.get("breaking_news", False)
    sentiment  = result.get("sentiment", "neutral")
    summary    = result.get("breaking_summary")
    confidence = result.get("confidence", 0.5)
    if has_news and sentiment == "bearish" and confidence > 0.65:
        return True, summary
    return False, None


def watchlist_expansion():
    """Top-10 erwaehnte Aktien auf X finden."""
    result = x_search(
        "Aktie kaufen Empfehlung bullish Deutschland USA 2026",
        hours=24
    )
    if not result:
        return []
    return result.get("top_signals", [])


def discover_finance_accounts(query=None, hours=72):
    """
    Findet aktive Finanz-Twitter-Accounts via Grok-Suche.

    Extrahiert @handles aus den top_signals der Grok-Antwort.
    Gibt Liste von Dicts zurueck: [{handle, snippet, sentiment}, ...]
    Wird von source_lifecycle.discover_twitter_via_grok() aufgerufen.

    Vorteil gegenueber reiner LLM-Discovery: Handles existieren wirklich,
    weil Grok echte Tweets durchsucht.
    """
    if query is None:
        query = "Aktie kaufen Empfehlung Analyse bullish"
    try:
        time_hint = (
            "letzte {} Stunden".format(hours) if hours <= 24
            else "letzte {} Tage".format(hours // 24)
        )
        prompt = (
            'Suche auf X nach: "{}". '.format(query) +
            'Zeitraum: {}. '.format(time_hint) +
            'Finde aktive Accounts die Aktien analysieren. '
            'Antworte NUR mit validem JSON ohne Backticks. '
            'Jedes top_signals-Element MUSS ein "handle"-Feld haben: '
            '{"sentiment":"neutral","confidence":0.5,"mention_count":0,'
            '"top_signals":[{"ticker":"NVDA","handle":"@finanzguru","text":"Kaufe NVDA","sentiment":"bullish"}],'
            '"breaking_news":false,"breaking_summary":null}'
        )
        agent    = _get_agent()
        response = agent.chat(prompt)
        m = re.search(r'\{.*\}', response, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(0))
        handles = []
        seen    = set()
        for sig in data.get("top_signals", []):
            raw = sig.get("handle", "").lstrip("@").lower().strip()
            if not raw or len(raw) < 3 or raw in seen:
                continue
            seen.add(raw)
            handles.append({
                "handle":    raw,
                "snippet":   sig.get("text", "")[:120],
                "sentiment": sig.get("sentiment", "neutral"),
            })
        return handles
    except Exception as e:
        print("  discover_finance_accounts Fehler: {}".format(e), flush=True)
        return []
