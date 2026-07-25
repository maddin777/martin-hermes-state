#!/usr/bin/env python3
"""
last30days_gate.py — Pre-Trade Gate für signal_manager.

Ruft zu einem Ticker aktuelle News ab (Google News RSS, kein API-Key nötig)
und prüft auf negative Signale. Shadow Validator — blockt nicht, warnt nur.

Nutzung: python3 last30days_gate.py <TICKER> [--name "Company Name"]
Output: JSON mit Verdict {ticker, verdict, sentiment, score, findings, sources}
Exit: 0=ok, 1=warning, 2=block
"""
import argparse
import json
import re
import sys
import requests
from bs4 import BeautifulSoup

NEGATIVE_KEYWORDS = [
    "downgrade", "sell-off", "crash", "lawsuit", "investigation",
    "recall", "fraud", "class action", "SEC", "fine", "penalty",
    "bankruptcy", "insolvency", "restructuring", "layoff", "layoffs",
    "profit warning", "guidance cut", "revenue miss", "loss",
    "bearish", "underperform", "reduce", "sell rating",
    "antitrust", "regulatory", "ban", "downgraded",
    "subpoena", "default", "investor", "settlement",
    "investigation", "probe", "accusation", "indictment"
]

POSITIVE_KEYWORDS = [
    "upgrade", "beat", "outperform", "buy rating", "overweight",
    "strong buy", "positive", "growth", "record", "partnership",
    "expansion", "innovation", "breakthrough", "FDA approval",
    "contract win", "dividend", "buyback", "guidance raise",
    "bullish", "upgraded", "price target raised", "record high",
    "all-time high", "profit", "revenue growth"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
}


def search_news(ticker: str, name: str = "", max_results: int = 10) -> list[dict]:
    """Sucht aktuelle News via Google News RSS (kein API-Key nötig)."""
    query = f"{ticker} stock"
    if name:
        query = f"{ticker} {name.split()[0]} stock"
    url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
    results = []
    seen_urls = set()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "xml")
        for item in soup.select("item")[:max_results]:
            title = item.find("title")
            link = item.find("link")
            desc = item.find("description")
            if title and link:
                t = title.get_text(strip=True)
                l = link.get_text(strip=True)
                if t and l and l not in seen_urls and len(t) > 15:
                    seen_urls.add(l)
                    results.append({
                        "title": t,
                        "url": l,
                        "snippet": desc.get_text(strip=True)[:200] if desc else ""
                    })
    except Exception as e:
        return [{"title": f"Fehler: {e}", "url": "", "snippet": ""}]
    return results[:max_results]


def analyze_sentiment(text: str) -> tuple[float, list[str], list[str]]:
    """Analysiert Text auf negative/positive Signale.
    Returns: (score 0-1, negative_findings, positive_findings)
    """
    text_lower = text.lower()
    neg_found = []
    pos_found = []

    for kw in NEGATIVE_KEYWORDS:
        if kw in text_lower:
            for s in re.split(r'[.!?]\s+', text):
                if kw in s.lower():
                    neg_found.append(s[:120].strip())
                    break
            else:
                neg_found.append(kw)

    for kw in POSITIVE_KEYWORDS:
        if kw in text_lower:
            for s in re.split(r'[.!?]\s+', text):
                if kw in s.lower():
                    pos_found.append(s[:120].strip())
                    break

    neg_weight = min(len(neg_found) * 0.12, 0.5)
    pos_weight = min(len(pos_found) * 0.08, 0.4)
    score = 0.5 + pos_weight - neg_weight
    score = max(0.0, min(1.0, score))

    return score, neg_found[:5], pos_found[:5]


def gate(ticker: str, name: str = "") -> dict:
    """Führt den Pre-Trade Gate Check durch."""
    results = search_news(ticker, name)

    errors = [r for r in results if "Fehler" in r.get("title", "")]
    if errors:
        return {
            "ticker": ticker,
            "verdict": "ok",
            "sentiment": "neutral",
            "score": 0.5,
            "findings": [],
            "sources": [],
            "error": errors[0]["title"]
        }

    if not results:
        return {
            "ticker": ticker,
            "verdict": "ok",
            "sentiment": "neutral",
            "score": 0.5,
            "findings": [],
            "sources": [],
            "error": "Keine News gefunden"
        }

    combined = " ".join(r["title"] for r in results if "title" in r)
    score, neg_findings, pos_findings = analyze_sentiment(combined)

    if score < 0.3:
        verdict = "block"
        sentiment = "bearish"
    elif score < 0.45:
        verdict = "warning"
        sentiment = "bearish"
    elif score > 0.65:
        verdict = "ok"
        sentiment = "bullish"
    else:
        verdict = "ok"
        sentiment = "neutral"

    return {
        "ticker": ticker,
        "verdict": verdict,
        "sentiment": sentiment,
        "score": round(score, 3),
        "findings": neg_findings[:3],
        "sources": [r["url"] for r in results[:5] if r.get("url")],
        "error": None
    }


def main():
    parser = argparse.ArgumentParser(description="Last30days Pre-Trade Gate")
    parser.add_argument("ticker", help="Ticker-Symbol (z.B. AAPL)")
    parser.add_argument("--name", default="", help="Unternehmensname")
    args = parser.parse_args()

    result = gate(args.ticker.upper(), args.name)
    print(json.dumps(result, indent=2))

    if result["verdict"] == "block":
        sys.exit(2)
    elif result["verdict"] == "warning":
        sys.exit(1)


if __name__ == "__main__":
    main()