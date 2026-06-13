#!/usr/bin/env python3
"""
breaking_news_monitor.py – Überwacht Breaking News für offene Positionen.

Prüft via Tavily ob es stark negative News zu offenen Positionen gibt.
Bei Score >= 0.7 negativ: SL auf 0.5×ATR ziehen + Telegram-Alert.
Bei Pre/After-Hours-Bewegung > 5%: direkter Exit-Alert.

Läuft idealerweise stündlich (oder in active_exit_check integriert).

AUSFÜHREN:
    python3 breaking_news_monitor.py
"""
import sqlite3, os, sys, json, requests
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa
from datetime import datetime
from config import DB_PATH, db_connect
from utils import get_price_data_cached, get_logger

log = get_logger("breaking_news")

TAVILY_KEY        = os.environ.get("TAVILY_API_KEY")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL  = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_CHAT_ID", "")
OPENROUTER_KEY    = os.environ.get("OPENROUTER_API_KEY")

NEWS_NEGATIVE_THRESHOLD = 0.65   # Tavily-Score: ab hier als negativ werten
PRICE_MOVE_THRESHOLD    = 0.05   # 5% Pre/After-Hours Bewegung → Alert


def _fetch_news(company_name: str, ticker: str) -> list:
    """Holt die letzten 24h News via Tavily."""
    if not TAVILY_KEY:
        return []
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_KEY,
                "query": f"{company_name} {ticker} news",
                "search_depth": "basic",
                "max_results": 5,
                "days": 1,
            },
            timeout=15,
        )
        data = r.json()
        return data.get("results", [])
    except Exception as e:
        log.warning("Tavily-Fehler für %s: %s", ticker, e)
        return []


def _score_news_sentiment(news_items: list, company_name: str) -> tuple:
    """
    Bewertet die Nachrichten-Stimmung via LLM.
    Gibt (score, summary) zurück: score 0=positiv, 1=negativ.
    """
    if not news_items or not OPENROUTER_KEY:
        return 0.0, ""

    snippets = "\n".join(
        f"- {n.get('title', '')}: {n.get('content', '')[:150]}"
        for n in news_items[:5]
    )
    prompt = (
        f"Bewerte folgende News zu {company_name} auf einer Skala:\n"
        f"0.0 = sehr positiv, 0.5 = neutral (keine klare Richtung, unvollständige Infos), "
        f"1.0 = sehr negativ\n\n"
        f"WICHTIG: Score UND Summary müssen konsistent sein. "
        f"Wenn die News keine klare negative Tendenz haben, ist der Score maximal 0.6.\n\n"
        f"{snippets}\n\n"
        f"Antworte NUR mit JSON: {{\"score\": 0.5, \"summary\": \"kurze Begründung\"}}"
    )
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "deepseek/deepseek-v4-flash", "max_tokens": 200,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        text = r.json()["choices"][0]["message"]["content"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        score = float(data.get("score", 0.5))
        summary = data.get("summary", "")
        # Plausibilitäts-Check: Wenn die Summary "neutral/unklar/keine" sagt, Score deckeln
        import re as _re
        if _re.search(r'\b(neutral|unklar|unvollständig|keine\s*klare|keine\s*konkrete)\b', summary, _re.IGNORECASE):
            score = min(score, 0.6)
        return score, summary
    except Exception as e:
        log.warning("LLM-Sentiment-Fehler: %s", e)
        return 0.5, ""


def _send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHANNEL:
        print(msg)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHANNEL, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning("Telegram-Fehler: %s", e)


def main():
    log.info("Breaking News Monitor gestartet")
    con = db_connect()
    positions = con.execute(
        "SELECT * FROM positions WHERE status='open'"
    ).fetchall()

    if not positions:
        print("Keine offenen Positionen.")
        con.close()
        return

    print(f"[Breaking News] Prüfe {len(positions)} Positionen...", flush=True)
    alerts = []

    for pos in positions:
        ticker    = pos["ticker"]
        name      = pos["name"] or ticker
        direction = pos["direction"]
        entry     = pos["entry_price"]
        sl        = pos["stop_loss"]

        # 1. News holen + bewerten
        news = _fetch_news(name, ticker)
        if not news:
            continue

        neg_score, summary = _score_news_sentiment(news, name)
        print(f"  {ticker}: neg_score={neg_score:.2f} | {summary[:60]}", flush=True)

        # 2. Bei stark negativen News: SL enger ziehen
        if neg_score >= NEWS_NEGATIVE_THRESHOLD:
            price, atr, _ = get_price_data_cached(ticker)
            if price and atr:
                if direction == "LONG":
                    tight_sl = price - (0.5 * atr)
                    if tight_sl > sl:
                        con.execute(
                            "UPDATE positions SET stop_loss=?, trailing_sl=? WHERE id=?",
                            (round(tight_sl, 2), round(tight_sl, 2), pos["id"])
                        )
                        alerts.append(
                            f"📰 <b>Neg. News: {name}</b>\n"
                            f"Score: {neg_score:.0%} negativ\n"
                            f"SL enger: {sl:.2f} → {tight_sl:.2f}\n"
                            f"{summary}"
                        )
                else:  # SHORT
                    tight_sl = price + (0.5 * atr)
                    if tight_sl < sl:
                        con.execute(
                            "UPDATE positions SET stop_loss=?, trailing_sl=? WHERE id=?",
                            (round(tight_sl, 2), round(tight_sl, 2), pos["id"])
                        )
                        alerts.append(
                            f"📰 <b>Neg. News: {name}</b>\n"
                            f"Score: {neg_score:.0%} negativ\n"
                            f"SL enger: {sl:.2f} → {tight_sl:.2f}\n"
                            f"{summary}"
                        )

        # 3. Pre/After-Hours Check (yfinance pre/post market)
        try:
            import yfinance as yf
            ticker_obj = yf.Ticker(ticker)
            fast = ticker_obj.fast_info
            pm_price = getattr(fast, 'pre_market_price', None) or \
                       getattr(fast, 'post_market_price', None)
            regular  = getattr(fast, 'last_price', entry)
            if pm_price and regular:
                move = abs(pm_price - regular) / regular
                if move >= PRICE_MOVE_THRESHOLD:
                    direction_emoji = "📈" if pm_price > regular else "📉"
                    alerts.append(
                        f"{direction_emoji} <b>Pre/After-Hours: {name}</b>\n"
                        f"Bewegung: {move:+.1%} ({regular:.2f} → {pm_price:.2f})\n"
                        f"Bitte Position manuell prüfen!"
                    )
        except Exception:
            pass

    con.commit()
    con.close()

    if alerts:
        for alert in alerts:
            _send_telegram(alert)
        print(f"  {len(alerts)} Alert(s) gesendet", flush=True)
    else:
        print("  Keine kritischen News.", flush=True)


if __name__ == "__main__":
    main()
