"""
Social Scanner
- RSS Feeds (aus source_registry DB, Fallback zu config/sources.json)
- Twitter/X Accounts (aus source_registry DB, Fallback zu config/sources.json) via twitterapi.io
Extrahiert Unternehmensnennungen und speichert in external_mentions.

Twitter/X-Zugang (seit 01.09.2026): twitterapi.io ist der PRIMÄRE (und einzige)
X-Anbieter. Die frühere Grok/xAI-x_search-Integration wurde entfernt (Dienst nicht
mehr genutzt). twitterapi.io bietet strukturierte Account-Suche (from:handle ...).
"""
import sqlite3
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import re
import time
import locale
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from config import DB_PATH, SOURCES_CONFIG_PATH, db_connect
from utils import retry, get_logger
log = get_logger("social_scanner")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "deepseek/deepseek-v4-flash-0731"

DAYS = 2

def load_config():
    with open(SOURCES_CONFIG_PATH) as f:
        return json.load(f)


def parse_date(entry):
    for attr in ["published_parsed", "updated_parsed"]:
        t = getattr(entry, attr, None)
        if t:
            import time
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return datetime.now(tz=timezone.utc)

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
FEED_TIMEOUT = 20


def _empty_result(error=False):
    r = {"companies": [], "market_outlook": "neutral"}
    if error:
        r["error"] = True
    return r


def _normalize_result(parsed):
    """Bringt eine LLM-Antwort in die Form {"companies": [...], "market_outlook": str}.

    K6 (30.09.2026): Der Prompt verlangt bei „keine Unternehmen“ ein leeres Array; das Modell antwortet dann
    mit `[]` (eine Liste). Aufrufer riefen darauf .get() und beendeten damit den ganzen Feed. Listen von
    Firmenobjekten werden eingewickelt. Gibt None zurück, wenn die Antwort nicht verwertbar ist."""
    if isinstance(parsed, list):
        parsed = {"companies": parsed}
    if not isinstance(parsed, dict):
        return None
    companies = parsed.get("companies", [])
    if not isinstance(companies, list):
        return None
    outlook = parsed.get("market_outlook")
    return {"companies": [c for c in companies if isinstance(c, dict)],
            "market_outlook": outlook if isinstance(outlook, str) and outlook else "neutral"}


def _checked_result(raw):
    """None = LLM-Fehler (Artikel NICHT als erledigt markieren, nächster Lauf versucht es erneut)."""
    if isinstance(raw, dict) and raw.get("error"):
        return None
    return _normalize_result(raw)


def extract_companies(title, content, source_name):
    """Liefert immer ein Dict; {"error": True, ...} bei Fehlern (kein Inhalt, kein gültiges JSON, Netz)."""
    text = f"{title}\n\n{content[:2000]}"
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL, "max_tokens": 500,
                "messages": [{
                    "role": "system",
                    "content": """Extrahiere börsennotierte Unternehmen aus dem Text.
Antworte NUR mit JSON, keine Backticks:
{"companies": [{"name": "Apple", "sentiment": "bullish"}],
 "market_outlook": "neutral"}
sentiment: bullish|bearish|neutral
Wenn keine Unternehmen: leeres Array."""
                }, {"role": "user", "content": text}]
            }, timeout=30)
        data = r.json()
        msg_content = data["choices"][0]["message"].get("content")
        if not msg_content:
            log.warning("LLM content is None in social_scanner, skipping")
            return _empty_result(error=True)
        content_str = _FENCE_RE.sub("", msg_content.strip()).strip()
        result = _normalize_result(json.loads(content_str))
        return result if result is not None else _empty_result(error=True)
    except Exception:
        return _empty_result(error=True)


def _rss_entry(con, feed_cfg, entry, cutoff):
    """Verarbeitet einen RSS-Artikel. True = neu gespeichert."""
    pub_date = parse_date(entry)
    if pub_date < cutoff:
        return False
    title = entry.get("title", "")
    content = entry.get("summary", "") or entry.get("description", "")
    url = entry.get("link", "")
    if not url or not title:
        return False
    if con.execute("SELECT id FROM external_mentions WHERE url=?", (url,)).fetchone():
        return False
    result = _checked_result(extract_companies(title, content, feed_cfg["name"]))
    if result is None:
        return False   # LLM-Fehler: nicht als erledigt markieren, der nächste Lauf versucht es erneut
    companies_json = json.dumps(result["companies"], ensure_ascii=False)
    con.execute("""
        INSERT OR IGNORE INTO external_mentions
        (source_type, source_name, title, content, url,
         published_at, fetched_at, companies, sentiment)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, ("rss", feed_cfg["name"], title, content[:1000], url,
          pub_date.strftime("%Y-%m-%d %H:%M"),
          datetime.now().isoformat(), companies_json,
          result["market_outlook"]))
    con.commit()  # Lock kurz halten — nicht bis zum nächsten LLM-Call
    return True


def fetch_rss_feeds(con, feeds):
    print("\n📰 RSS Feeds...", flush=True)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=DAYS)
    new_articles = 0
    for feed_cfg in feeds:
        if not feed_cfg.get("enabled"):
            continue
        try:
            # M16 (30.09.2026): feedparser.parse(url) hat kein Timeout; ein hängender Server blockierte
            # den ganzen Job. Jetzt holt requests mit Timeout, feedparser parst nur den Inhalt.
            resp = requests.get(feed_cfg["url"], timeout=FEED_TIMEOUT,
                                headers={"User-Agent": getattr(feedparser, "USER_AGENT", "Mozilla/5.0")})
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            count = 0
            for entry in feed.entries:
                try:
                    if _rss_entry(con, feed_cfg, entry, cutoff):
                        count += 1
                        new_articles += 1
                except Exception as e:
                    # K6: ein Artikel darf nie den ganzen Feed beenden
                    log.warning("RSS-Artikel übersprungen (%s): %s", feed_cfg.get("name"), e)
            if count > 0:
                print(f"  ✓ {feed_cfg['name']:25} {count} neue Artikel", flush=True)
        except Exception as e:
            print(f"  ✗ {feed_cfg['name']}: {e}", flush=True)
    print(f"  → {new_articles} neue RSS-Artikel gespeichert", flush=True)


_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def parse_tweet_date(created):
    """twitterapi.io liefert z. B. 'Tue Dec 10 07:00:30 +0000 2024'. Rückgabe 'YYYY-MM-DD HH:MM' (UTC).

    K5 (30.09.2026): Der alte Code schnitt bei 19 Zeichen ab und parste ohne Jahr, dadurch stand bei 4.748 von
    4.751 Tweets 1900 als Jahr und das 2-Tage-Fenster nahm keinen einzigen auf. Locale-unabhängig.
    Nicht parsebares Datum: aktuelle Zeit (UTC), nie ein Jahr 1900."""
    try:
        parts = (created or "").split()
        if len(parts) == 6:
            _dow, mon, day, hms, tz, year = parts
            h, m, s = (int(x) for x in hms.split(":"))
            sign = -1 if tz.startswith("-") else 1
            off = timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5])) * sign
            dt = datetime(int(year), _MONTHS[mon], int(day), h, m, s, tzinfo=timezone(off))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        if created:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _tweet(con, acc, handle, tweet):
    """Verarbeitet einen Tweet. True = neu gespeichert."""
    tweet_id = tweet.get("id") or tweet.get("id_str", "")
    text = tweet.get("text", "")
    created = tweet.get("createdAt", "") or tweet.get("created_at", "")
    url = f"https://twitter.com/{handle}/status/{tweet_id}"
    if not text or not tweet_id:
        return False
    if con.execute("SELECT id FROM external_mentions WHERE url=?", (url,)).fetchone():
        return False
    pub_str = parse_tweet_date(created)
    result = _checked_result(extract_companies(text, "", acc["name"]))
    if result is None:
        return False   # LLM-Fehler: nicht als erledigt markieren
    companies_json = json.dumps(result["companies"], ensure_ascii=False)
    con.execute("""
        INSERT OR IGNORE INTO external_mentions
        (source_type, source_name, title, content, url,
         published_at, fetched_at, companies, sentiment)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, ("twitter", acc["name"], text[:200], text, url,
          pub_str, datetime.now().isoformat(),
          companies_json, result["market_outlook"]))
    con.commit()  # Lock kurz halten — nicht bis zum nächsten LLM-Call
    return True


def fetch_twitter(con, accounts):
    """Twitter/X via twitterapi.io — PRIMÄRER (einziger) X-Anbieter seit 01.09.2026."""
    print("\n🐦 Twitter/X Accounts (twitterapi.io, primär)...", flush=True)
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
                params={"query": query, "queryType": "Latest"}, timeout=15)
            if r.status_code != 200:
                print(f"  ✗ @{handle}: HTTP {r.status_code}", flush=True)
                continue
            tweets = r.json().get("tweets", [])
            count = 0
            for tweet in tweets:
                try:
                    if _tweet(con, acc, handle, tweet):
                        count += 1
                except Exception as e:
                    # K6: ein Tweet darf nie den ganzen Account beenden
                    log.warning("Tweet übersprungen (@%s): %s", handle, e)
            con.commit()
            if count > 0:
                print(f"  ✓ @{handle:20} {count} neue Tweets", flush=True)
            else:
                print(f"  – @{handle:20} keine neuen Tweets in 24h", flush=True)
        except Exception as e:
            print(f"  ✗ @{handle}: {e}", flush=True)

def inject_into_watchlist(con):
    print("\n🔄 Injiziere externe Mentions in Watchlist...", flush=True)
    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    mentions = con.execute("""
        SELECT source_name, companies, sentiment, published_at, url
        FROM external_mentions
        WHERE published_at >= ? AND companies != '[]'
    """, (cutoff,)).fetchall()
    injected = 0
    for m in mentions:
        try:
            companies = json.loads(m[1])
            for company in companies:
                name = company.get("name", "").strip()
                if not name or len(name) < 2:
                    continue
                sentiment = company.get("sentiment", m[2] or "neutral")
                con.execute("""
                    INSERT OR IGNORE INTO watchlist_mentions
                    (name, channel, video_id, video_title, sentiment, reason, mention_date)
                    VALUES (?,?,?,?,?,?,?)
                """, (name, f"RSS:{m[0]}", m[4], m[4][:100],
                      sentiment, f"Quelle: {m[0]}",
                      m[3][:10] if m[3] else datetime.now().strftime("%Y-%m-%d")))
                injected += 1
        except Exception:
            pass
    con.commit()
    print(f"  ✓ {injected} externe Mentions in Watchlist injiziert", flush=True)

def get_active_rss_feeds(con):
    """Lädt aktive RSS-Feeds aus source_registry DB."""
    rows = con.execute("""
        SELECT source_key as url, display_name as name, weight, language
        FROM source_registry
        WHERE source_type = 'rss'
        AND status IN ('active', 'probation')
        AND enabled = 1
    """).fetchall()
    return [{"name": r["name"], "url": r["url"], "enabled": True,
             "weight": r["weight"], "language": r["language"]} for r in rows]

def get_active_twitter_accounts(con):
    """Lädt aktive Twitter-Accounts aus source_registry DB."""
    rows = con.execute("""
        SELECT source_key as handle, display_name as name, weight, category
        FROM source_registry
        WHERE source_type = 'twitter'
        AND status IN ('active', 'probation')
        AND enabled = 1
    """).fetchall()
    return [{"handle": r["handle"], "name": r["name"], "enabled": True,
             "weight": r["weight"], "category": r["category"]} for r in rows]

def main():
    print("📡 Social Scanner gestartet", flush=True)
    con = db_connect()
    try:
        # Quellen aus DB laden (Fallback zu sources.json)
        try:
            rss_feeds = get_active_rss_feeds(con)
            twitter_accounts = get_active_twitter_accounts(con)
            if not rss_feeds and not twitter_accounts:
                config = load_config()
                rss_feeds = [f for f in config.get("rss_feeds", []) if f.get("enabled")]
                twitter_accounts = [a for a in config.get("twitter_accounts", []) if a.get("enabled")]
        except Exception:
            config = load_config()
            rss_feeds = [f for f in config.get("rss_feeds", []) if f.get("enabled")]
            twitter_accounts = [a for a in config.get("twitter_accounts", []) if a.get("enabled")]

        fetch_rss_feeds(con, rss_feeds)
        if twitter_accounts:
            # twitterapi.io ist der einzige Primär (kein Grok-Fallback mehr)
            fetch_twitter(con, twitter_accounts)
        inject_into_watchlist(con)

        print("\n✅ Social Scanner abgeschlossen", flush=True)
    finally:
        con.rollback()  # Offene Transaktion schließen — verhindert DB-Lock für nachfolgende Prozesse
        con.close()

if __name__ == "__main__":
    main()
