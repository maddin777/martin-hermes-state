"""
x_search Helper via twitterapi.io (Standard seit 01.09.2026).

Die frühere Grok/xAI-`x_search`-Integration wurde entfernt (Dienst nicht mehr genutzt).
Stattdessen wird twitterapi.io für X-Suchen genutzt: generische Keyword-Suche über
`advanced_search`, dann Sentiment-Extraktion via OpenRouter (DeepSeek). Das JSON-Format
(sentiment/confidence/mention_count/breaking_news/top_signals) bleibt unverändert,
damit die aufbauenden Helper (conviction_boost, breaking_news_check, disk) weiter laufen.
"""
import sys, os, json, re

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

def _twapi_key():
    return os.environ.get("TWITTERAPI_IO_KEY", "").strip()

def _search_tweets(query, max_results=15):
    """Führt eine twitterapi.io advanced_search durch. Liefert Liste von Tweet-Dicts."""
    import requests
    key = _twapi_key()
    if not key:
        return []
    r = requests.get(
        "https://api.twitterapi.io/twitter/tweet/advanced_search",
        headers={"X-API-Key": key},
        params={"query": query, "queryType": "Latest"},
        timeout=20,
    )
    if r.status_code != 200:
        print(f"  ✗ twitterapi.io HTTP {r.status_code}", flush=True)
        return []
    return r.json().get("tweets", [])[:max_results]

def _extract_sentiment(texts):
    """Lässt DeepSeek aus Roh-Tweets sentiment/mention_count/breaking_news erzeugen."""
    import requests
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key or not texts:
        return {"sentiment": "neutral", "confidence": 0.5, "mention_count": len(texts),
                "top_signals": [], "breaking_news": False, "breaking_summary": None}
    joined = "\n---\n".join(t[:300] for t in texts[:15])[:2500]
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek/deepseek-v4-flash-0731", "max_tokens": 400,
                "messages": [{
                    "role": "system",
                    "content": """Analysiere diese Tweets zu einem Ticker/Unternehmen. Antworte NUR mit JSON:
{"sentiment":"bullish|bearish|neutral","confidence":0.0,"mention_count":<n>,
 "top_signals":[{"ticker":"NVDA","handle":"@x","text":"...","sentiment":"bullish"}],
 "breaking_news":false,"breaking_summary":null}
Wenn die Tweets negative/Positive Haltung zu einem börsennotierten Unternehmen zeigen, setze sentiment entsprechend."""
                }, {"role": "user", "content": joined}]
            }, timeout=30)
        data = r.json()
        content = data["choices"][0]["message"].get("content")
        if content:
            return _parse_first_json(content)
    except Exception as e:
        print(f"  ✗ Sentiment-Extraktion Fehler: {e}", flush=True)
    return {"sentiment": "neutral", "confidence": 0.5, "mention_count": len(texts),
            "top_signals": [], "breaking_news": False, "breaking_summary": None}

def _parse_first_json(text):
    dec = json.JSONDecoder()
    for idx, ch in enumerate(text or ""):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None

def x_search(query, hours=24, allowed_handles=None):
    """X-Suche via twitterapi.io — liefert dasselbe JSON wie die frühere Grok-Variante.

    query: Keyword/Ticker-String. allowed_handles: optional, auf Accounts einschränken.
    """
    try:
        # Zeitfenster → since-Query (24h/48h etc.)
        since = ""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        since = now - datetime.timedelta(hours=hours)
        since_str = since.strftime("%Y-%m-%d_%H:%M:%S_UTC")

        if allowed_handles:
            # Account-spezifische Abfrage: from:handle
            handles = "," .join(h.lstrip("@") for h in allowed_handles)
            q = f"from:{handles} since:{since_str}"
        else:
            # generische Keyword-Suche
            q = f'{query} since:{since_str}'

        tweets = _search_tweets(q, max_results=15)
        if not tweets:
            return {"sentiment": "neutral", "confidence": 0.5, "mention_count": 0,
                    "top_signals": [], "breaking_news": False, "breaking_summary": None}
        texts = [t.get("text", "") for t in tweets if t.get("text")]
        result = _extract_sentiment(texts)
        result["mention_count"] = len(texts)
        return result
    except Exception as e:
        print(f"  x_search(twitterapi.io) Fehler: {e}", flush=True)
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
    result = x_search("Aktie kaufen Empfehlung bullish Deutschland USA 2026", hours=24)
    if not result:
        return []
    return result.get("top_signals", [])


def discover_finance_accounts(query=None, hours=72):
    """Findet aktive Finanz-Twitter-Accounts via twitterapi.io-Suche.

    Liefert Liste von Dicts: [{handle, snippet, sentiment}, ...].
    """
    if query is None:
        query = "Aktie kaufen Empfehlung Analyse bullish"
    try:
        tweets = _search_tweets(query, max_results=15)
        handles = []
        seen = set()
        for t in tweets:
            handle_raw = (t.get("author", {}) or {}).get("handle", "")
            if not handle_raw:
                continue
            handle = handle_raw.lstrip("@").lower().strip()
            if not handle or len(handle) < 3 or handle in seen:
                continue
            seen.add(handle)
            handles.append({
                "handle": handle,
                "snippet": (t.get("text", "") or "")[:120],
                "sentiment": "neutral",
            })
        return handles
    except Exception as e:
        print(f"  discover_finance_accounts Fehler: {e}", flush=True)
        return []
