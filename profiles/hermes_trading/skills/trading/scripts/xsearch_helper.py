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
    """Führt x_search via Hermes AIAgent aus."""
    try:
        time_hint  = f"letzte {hours} Stunden" if hours <= 24 else f"letzte {hours//24} Tage"
        handle_hint = f"Accounts: {', '.join(allowed_handles)}." if allowed_handles else ""

        prompt = (
            f'Suche auf X nach: "{query}". '
            f'Zeitraum: {time_hint}. {handle_hint} '
            f'Antworte NUR mit validem JSON, keine Backticks: '
            f'{{"sentiment":"bullish|bearish|neutral","confidence":0.0,'
            f'"mention_count":0,"top_signals":[],'
            f'"breaking_news":false,"breaking_summary":null}}'
        )

        agent    = _get_agent()
        response = agent.chat(prompt)

        m = re.search(r'\{.*\}', response, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return None

    except Exception as e:
        print(f"  ✗ x_search Fehler: {e}", flush=True)
        return None


def conviction_boost(ticker, name, current_conviction):
    """Punkt 1: Signal-Bestätigung für Aktien mit Conviction >70%."""
    if current_conviction < 0.70:
        return current_conviction, "skipped"

    # Ohne Handle-Filter - breitere Suche liefert mehr Ergebnisse
    result = x_search(
        f"{name} {ticker} Aktie bullish Analyse",
        hours=24
    )
    if not result:
        return current_conviction, "no_result"

    sentiment  = result.get("sentiment", "neutral")
    confidence = result.get("confidence", 0.5)
    mentions   = result.get("mention_count", 0)

    if sentiment == "bullish" and mentions >= 2:
        boost    = min(0.10, confidence * 0.10)
        new_conv = min(1.0, current_conviction + boost)
        return new_conv, f"boosted +{boost:.0%} (X: {mentions} bullish Posts)"
    elif sentiment == "bearish" and confidence > 0.6:
        penalty  = min(0.15, confidence * 0.15)
        new_conv = max(0.0, current_conviction - penalty)
        return new_conv, f"reduced -{penalty:.0%} (X: bearish Signal)"

    return current_conviction, f"unchanged (X: {sentiment}, {mentions} Posts)"


def contradiction_check(name, ticker):
    """Punkt 2: Gegencheck bei widersprüchlichen Signalen."""
    result = x_search(f"{name} {ticker} Aktie Meinung Analyse", hours=48)
    if not result:
        return "neutral", 0.5
    return result.get("sentiment", "neutral"), result.get("confidence", 0.5)


def breaking_news_check(ticker, name):
    """Punkt 3: Breaking News Filter vor Kauf."""
    result = x_search(f"{ticker} {name}", hours=6)
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
    """Punkt 4: Top-10 erwähnte Aktien auf X finden."""
    result = x_search(
        "Aktie kaufen Empfehlung bullish Deutschland USA 2026",
        hours=24
    )
    if not result:
        return []
    return result.get("top_signals", [])
