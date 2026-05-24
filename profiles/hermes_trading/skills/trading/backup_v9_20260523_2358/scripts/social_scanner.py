"""
Social Scanner
- RSS Feeds (editierbar via config/sources.json)
- Twitter/X Accounts (editierbar via config/sources.json)
Extrahiert Unternehmensnennungen und speichert in external_mentions
"""
import sqlite3
import json
import os
import re
import requests
import feedparser
from datetime import datetime, timedelta, timezone

DB_PATH      = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
CONFIG_PATH  = "/root/.hermes/profiles/hermes_trading/skills/trading/config/sources.json"
SIGNALS_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading_signals.json"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "google/gemini-2.5-flash-lite"

DAYS = 2  # Nur Artikel der letzten 2 Tage

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def parse_date(entry):
    """Versucht Datum aus RSS-Entry zu lesen."""
    for attr in ["published_parsed", "updated_parsed"]:
        t = getattr(entry, attr, None)
        if t:
            import time
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return datetime.now(tz=timezone.utc)

def extract_companies(title, content, source_name):
    """Nutzt KI um Unternehmen aus Text zu extrahieren."""
    text = f"{title}\n\n{content[:2000]}"
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL,
                "max_tokens": 500,
                "messages": [{
                    "role": "system",
                    "content": """Extrahiere börsennotierte Unternehmen aus dem Text.
Antworte NUR mit JSON, keine Backticks:
{"companies": [{"name": "Apple", "sentiment": "bullish"}],
 "market_outlook": "neutral"}
sentiment: bullish|bearish|neutral
Wenn keine Unternehmen: leeres Array."""
                }, {
                    "role": "user",
                    "content": text
                }]
            },
            timeout=30
        )
        data = r.json()
        content_str = data["choices"][0]["message"]["content"].strip()
        return json.loads(content_str)
    except:
        return {"companies": [], "market_outlook": "neutral"}

def fetch_rss_feeds(con, feeds):
    """Holt und verarbeitet RSS Feeds."""
    print("\n📰 RSS Feeds...", flush=True)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=DAYS)
    new_articles = 0

    for feed_cfg in feeds:
        if not feed_cfg.get("enabled"):
            continue
        try:
            feed = feedparser.parse(feed_cfg["url"])
            count = 0
            for entry in feed.entries:
                pub_date = parse_date(entry)
                if pub_date < cutoff:
                    continue

                title   = entry.get("title", "")
                content = entry.get("summary", "") or entry.get("description", "")
                url     = entry.get("link", "")

                if not url or not title:
                    continue

                # Bereits vorhanden?
                existing = con.execute(
                    "SELECT id FROM external_mentions WHERE url=?", (url,)
                ).fetchone()
                if existing:
                    continue

                # Unternehmen extrahieren
                result = extract_companies(title, content, feed_cfg["name"])
                companies_json = json.dumps(result.get("companies", []),
                                           ensure_ascii=False)
                sentiment = result.get("market_outlook", "neutral")

                con.execute("""
                    INSERT OR IGNORE INTO external_mentions
                    (source_type, source_name, title, content, url,
                     published_at, fetched_at, companies, sentiment)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, ("rss", feed_cfg["name"], title, content[:1000], url,
                      pub_date.strftime("%Y-%m-%d %H:%M"),
                      datetime.now().isoformat(),
                      companies_json, sentiment))
                count += 1
                new_articles += 1

            if count > 0:
                print(f"  ✓ {feed_cfg['name']:25} {count} neue Artikel", flush=True)
            con.commit()

        except Exception as e:
            print(f"  ✗ {feed_cfg['name']}: {e}", flush=True)

    print(f"  → {new_articles} neue RSS-Artikel gespeichert", flush=True)

def fetch_twitter(con, accounts):
    """Holt Twitter/X Posts via twitterapi.io (keine Cookies noetig)."""
    print("\n🐦 Twitter/X Accounts (twitterapi.io)...", flush=True)

    TWAPI_KEY = os.environ.get("TWITTERAPI_IO_KEY", "")
    if not TWAPI_KEY:
        print("  ⚠ TWITTERAPI_IO_KEY nicht gesetzt - ueberspringe Twitter", flush=True)
        return

    since_dt = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    since_str = since_dt.strftime("%Y-%m-%d_%H:%M:%S_UTC")

    enabled = [a for a in accounts if a.get("enabled")]
    print(f"  Verarbeite {len(enabled)} Accounts...", flush=True)

    for acc in enabled:
        handle = acc["handle"]
        try:
            query = f"from:{handle} -is:retweet since:{since_str}"
            r = requests.get(
                "https://api.twitterapi.io/twitter/tweet/advanced_search",
                headers={"X-API-Key": TWAPI_KEY},
                params={"query": query, "queryType": "Latest"},
                timeout=15
            )
            if r.status_code != 200:
                print(f"  ✗ @{handle}: HTTP {r.status_code}", flush=True)
                continue

            tweets = r.json().get("tweets", [])
            count = 0
            for tweet in tweets:
                tweet_id = tweet.get("id") or tweet.get("id_str", "")
                text     = tweet.get("text", "")
                created  = tweet.get("createdAt", "") or tweet.get("created_at", "")
                url      = f"https://twitter.com/{handle}/status/{tweet_id}"
                if not text or not tweet_id:
                    continue
                existing = con.execute(
                    "SELECT id FROM external_mentions WHERE url=?", (url,)
                ).fetchone()
                if existing:
                    continue
                try:
                    pub_dt  = datetime.strptime(created[:19], "%a %b %d %H:%M:%S")
                    pub_str = pub_dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pub_str = datetime.now().strftime("%Y-%m-%d %H:%M")

                result        = extract_companies(text, "", acc["name"])
                companies_json = json.dumps(result.get("companies", []), ensure_ascii=False)
                con.execute("""
                    INSERT OR IGNORE INTO external_mentions
                    (source_type, source_name, title, content, url,
                     published_at, fetched_at, companies, sentiment)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, ("twitter", acc["name"], text[:200], text, url,
                      pub_str, datetime.now().isoformat(),
                      companies_json, result.get("market_outlook", "neutral")))
                count += 1

            con.commit()
            if count > 0:
                print(f"  ✓ @{handle:20} {count} neue Tweets", flush=True)
            else:
                print(f"  – @{handle:20} keine neuen Tweets in 24h", flush=True)

        except Exception as e:
            print(f"  ✗ @{handle}: {e}", flush=True)

def inject_into_watchlist(con):
    """
    Überträgt externe Mentions in watchlist_mentions Tabelle
    damit watchlist_manager sie beim nächsten Run aufnimmt.
    """
    print("\n🔄 Injiziere externe Mentions in Watchlist...", flush=True)

    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    mentions = con.execute("""
        SELECT source_name, companies, sentiment, published_at, url
        FROM external_mentions
        WHERE published_at >= ?
        AND companies != '[]'
    """, (cutoff,)).fetchall()

    injected = 0
    for m in mentions:
        try:
            companies = json.loads(m[1])
            for company in companies:
                name = company.get("name", "").strip()
                if not name or len(name) < 2:
                    continue
                # Sentiment aus Artikel übernehmen
                sentiment = company.get("sentiment", m[2] or "neutral")
                con.execute("""
                    INSERT OR IGNORE INTO watchlist_mentions
                    (name, channel, video_id, video_title,
                     sentiment, reason, mention_date)
                    VALUES (?,?,?,?,?,?,?)
                """, (name, f"RSS:{m[0]}", m[4],
                      m[4][:100],
                      sentiment, f"Quelle: {m[0]}",
                      m[3][:10] if m[3] else datetime.now().strftime("%Y-%m-%d")))
                injected += 1
        except:
            pass

    con.commit()
    print(f"  ✓ {injected} externe Mentions in Watchlist injiziert", flush=True)

def main():
    print("📡 Social Scanner gestartet", flush=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    config = load_config()

    # RSS Feeds
    fetch_rss_feeds(con, config["rss_feeds"])

    # Twitter (nur wenn twscrape installiert)
    enabled_twitter = [a for a in config["twitter_accounts"] if a.get("enabled")]
    if enabled_twitter:
        fetch_twitter(con, enabled_twitter)

    # In Watchlist injizieren
    inject_into_watchlist(con)

    con.close()
    print("\n✅ Social Scanner abgeschlossen", flush=True)

if __name__ == "__main__":
    main()
