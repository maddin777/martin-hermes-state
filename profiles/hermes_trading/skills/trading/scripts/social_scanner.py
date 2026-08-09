"""
Social Scanner
- RSS Feeds (aus source_registry DB, Fallback zu config/sources.json)
- Twitter/X Accounts (aus source_registry DB, Fallback zu config/sources.json)
Extrahiert Unternehmensnennungen und speichert in external_mentions
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

# xAI / Grok — via Hermes resolve_xai_http_credentials() (auto-refresh via OAuth)
XAI_BASE = "https://api.x.ai/v1"
XAI_MODEL = "grok-4.5"

DAYS = 2

def load_config():
    with open(SOURCES_CONFIG_PATH) as f:
        return json.load(f)


# ── xAI / Grok Helpers ──────────────────────────────────────────────

def _resolve_xai_token() -> str:
    """xAI OAuth-Token — primär via resolve_xai_http_credentials() (auto-refresh),
    Fallback auf auth.json direkt (ohne Cache, liest bei jedem Call frisch).

    Kein Session-Cache mehr — so wird ein via OAuth-Refresh aktualisierter
    Token beim nächsten Call sofort erkannt.
    Returns Leerstring wenn kein Token verfuegbar.
    """
    # Pfad 1: Hermes resolve_xai_http_credentials() mit auto-refresh
    try:
        from tools.xai_http import resolve_xai_http_credentials
        creds = resolve_xai_http_credentials()
        token = str(creds.get("api_key") or "").strip()
        if token:
            return token
    except Exception as e:
        log.debug("xAI Token via Hermes: %s", e)

    # Pfad 2: auth.json direkt (wenn Hermes-Import wegen Namespace-Kollision fehlschlägt)
    try:
        for candidate in [
            "/root/.hermes/auth.json",
            os.path.expanduser("~/.hermes/auth.json"),
        ]:
            if os.path.exists(candidate):
                with open(candidate) as f:
                    auth = json.load(f)
                # credential_pool.xai-oauth — aktuellster Eintrag
                pool = auth.get("credential_pool", {})
                entries = pool.get("xai-oauth", [])
                if entries:
                    valid = [e for e in entries if e.get("access_token")]
                    valid.sort(key=lambda e: e.get("last_refresh", ""), reverse=True)
                    if valid:
                        return valid[0]["access_token"]
                # providers.xai-oauth.tokens (fallback)
                providers = auth.get("providers", {})
                xai_state = providers.get("xai-oauth", {})
                tokens = xai_state.get("tokens", {})
                if tokens.get("access_token"):
                    return tokens["access_token"]
    except Exception as e:
        log.debug("xAI Token via auth.json: %s", e)

    # Pfad 3: XAI_API_KEY env var (letzter Fallback)
    return os.environ.get("XAI_API_KEY", "").strip()


def _call_x_search(query: str, handles: list = None,
                   from_date: str = "", to_date: str = "") -> dict | None:
    """Ruft xAI Responses API mit x_search-Tool auf.

    Single-Call: Grok sucht auf X/Twitter und extrahiert Unternehmen.
    Retry bei 429 (Rate-Limit), 5xx (Server-Fehler), Timeout.
    Returns {"answer": str, "citations": list} oder None bei Fehler.
    """
    token = _resolve_xai_token()
    if not token:
        return None

    tool_def: dict = {"type": "x_search"}
    if handles:
        tool_def["allowed_x_handles"] = [h.lstrip("@") for h in handles]
    if from_date:
        tool_def["from_date"] = from_date
    if to_date:
        tool_def["to_date"] = to_date

    payload = {
        "model": XAI_MODEL,
        "input": [{"role": "user", "content": query}],
        "tools": [tool_def],
        "store": False,
    }

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(
                f"{XAI_BASE}/responses",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=180,
            )

            # Rate-Limit: exponential backoff
            if r.status_code == 429:
                wait = 2 ** attempt
                log.warning("xAI 429 Rate-Limit (attempt %s/2), warte %ss", attempt + 1, wait)
                time.sleep(wait)
                continue

            # 5xx: retry
            if r.status_code >= 500:
                if attempt < max_retries:
                    wait = min(5.0, 1.5 * (attempt + 1))
                    log.warning("xAI %s (attempt %s/2), retry in %.1fs", r.status_code, attempt + 1, wait)
                    time.sleep(wait)
                    continue
                log.warning("xAI API HTTP %s nach %s Versuchen: %s", r.status_code, max_retries + 1, r.text[:200])
                return None

            if r.status_code != 200:
                log.warning("xAI API HTTP %s: %s", r.status_code, r.text[:200])
                return None

            data = r.json()

            # Antwort aus output[] extrahieren (Responses API Format)
            parts = []
            for item in data.get("output", []) or []:
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []) or []:
                    ctype = content.get("type")
                    if ctype in ("output_text", "text"):
                        text = (content.get("text") or "").strip()
                        if text:
                            parts.append(text)
            answer = "\n\n".join(parts).strip()

            # Citations aus inline annotations
            citations = list(data.get("citations") or [])
            if not citations:
                for item in data.get("output", []) or []:
                    if item.get("type") != "message":
                        continue
                    for content in item.get("content", []) or []:
                        for ann in content.get("annotations", []) or []:
                            if ann.get("type") == "url_citation" and ann.get("url"):
                                citations.append(ann["url"])

            if not answer:
                log.warning("xAI API: leere Antwort")
                return None
            return {"answer": answer, "citations": citations}

        except requests.Timeout:
            if attempt < max_retries:
                wait = min(5.0, 1.5 * (attempt + 1))
                log.warning("xAI Timeout (attempt %s/2), retry in %.1fs", attempt + 1, wait)
                time.sleep(wait)
                continue
            log.warning("xAI API Timeout nach 180s und %s Versuchen", max_retries + 1)
            return None

        except Exception as e:
            if attempt < max_retries:
                wait = min(5.0, 1.5 * (attempt + 1))
                log.warning("xAI Fehler (attempt %s/2): %s — retry in %.1fs", attempt + 1, e, wait)
                time.sleep(wait)
                continue
            log.warning("xAI API Fehler nach %s Versuchen: %s", max_retries + 1, e)
            return None

    return None


def _parse_grok_json(text: str) -> dict:
    """Extrahiert JSON aus Grok-Antwort — bereinigt Markdown-Wrapper."""
    text = text.strip()
    for marker in ["```json\n", "```json", "```"]:
        if marker in text:
            parts = text.split(marker)
            if len(parts) > 1:
                text = parts[1].split("```")[0].strip()
                break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Regex-Fallback: erstes JSON-Objekt
        import re
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def fetch_twitter_grok(con, accounts) -> bool:
    """Twitter/X via xAI x_search — Single-Call: Suche + Extraktion.

    Returns True wenn Grok erfolgreich war, False fuer Fallback.
    """
    print("\n🐦 Twitter/X Accounts (Grok x_search)...", flush=True)
    token = _resolve_xai_token()
    if not token:
        _send_telegram_alert("⚠️ Grok Twitter: xAI Token nicht verfügbar — Fallback auf twitterapi.io")
        print("  ⚠ xAI Token nicht verfuegbar — fallback zu twitterapi.io", flush=True)
        return False

    enabled = [a for a in accounts if a.get("enabled")]
    print(f"  Verarbeite {len(enabled)} Accounts via Grok...", flush=True)
    any_ok = False

    for acc in enabled:
        handle = acc["handle"]
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            query = (
                f"Search X for tweets from @{handle} in the last 24h (since {today}). "
                f"Extract ALL publicly traded companies mentioned in these tweets. "
                f"Return ONLY valid JSON — no markdown, no explanation, no extra text:\n"
                f'{{"companies": [{{"name": "CompanyName", "sentiment": "bullish|bearish|neutral"}}], '
                f'"market_outlook": "bullish|bearish|neutral"}}'
            )
            result = _call_x_search(query=query, handles=[handle],
                                    from_date=today)
            if not result or not result.get("answer"):
                print(f"  ✗ @{handle}: keine Antwort von Grok", flush=True)
                continue

            answer = result["answer"]
            citations = result.get("citations", [])
            parsed = _parse_grok_json(answer)
            companies = parsed.get("companies", [])
            outlook = parsed.get("market_outlook", "neutral")
            url = citations[0] if citations else f"https://x.com/{handle}"

            companies_json = json.dumps(companies, ensure_ascii=False)
            con.execute(
                """INSERT OR IGNORE INTO external_mentions
                   (source_type, source_name, title, content, url,
                    published_at, fetched_at, companies, sentiment)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                ("twitter", acc["name"], answer[:200], answer, url,
                 datetime.now().strftime("%Y-%m-%d %H:%M"),
                 datetime.now().isoformat(), companies_json, outlook))
            con.commit()

            print(f"  ✓ @{handle:20} {len(companies)} Unternehmen, "
                  f"{len(citations)} Tweets", flush=True)
            any_ok = True

        except json.JSONDecodeError as e:
            print(f"  ✗ @{handle}: JSON-Fehler: {e}", flush=True)
            if result:
                print(f"    Antwort: {result.get('answer', '')[:150]}...", flush=True)
        except Exception as e:
            print(f"  ✗ @{handle}: {e}", flush=True)

    if not any_ok and token:
        _send_telegram_alert("⚠️ Grok Twitter: Alle Accounts fehlgeschlagen — Fallback auf twitterapi.io")
    return any_ok


def _send_telegram_alert(msg: str) -> None:
    """Sendet eine Telegram-Benachrichtigung in den Trading-Channel."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass  # silent fail — Benachrichtigung darf den Scanner nicht blockieren


def fetch_x_search_grok(con, queries) -> None:
    """Generische X-Searches via Grok — Keyword/Thema statt Account-Scan.

    source_type='x_search' in external_mentions.
    """
    print("\n🔍 X Search Queries (Grok x_search)...", flush=True)
    token = _resolve_xai_token()
    if not token:
        print("  ⚠ xAI Token nicht verfuegbar — ueberspringe X Searches", flush=True)
        return

    enabled = [q for q in queries if q.get("enabled")]
    print(f"  Verarbeite {len(enabled)} Queries via Grok...", flush=True)

    for q in enabled:
        query_text = q["query"]
        name = q["name"]
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            prompt = (
                f"Search X for posts matching: {query_text} (last 24h, since {today}). "
                f"Extract ALL publicly traded companies mentioned. "
                f"Return ONLY valid JSON — no markdown, no explanation:\n"
                f'{{"companies": [{{"name": "CompanyName", "sentiment": "bullish|bearish|neutral"}}], '
                f'"market_outlook": "bullish|bearish|neutral"}}'
            )
            result = _call_x_search(query=prompt, from_date=today)
            if not result or not result.get("answer"):
                print(f"  ✗ {name}: keine Antwort von Grok", flush=True)
                continue

            answer = result["answer"]
            citations = result.get("citations", [])
            parsed = _parse_grok_json(answer)
            companies = parsed.get("companies", [])
            outlook = parsed.get("market_outlook", "neutral")
            url = citations[0] if citations else f"https://x.com/search?q={query_text}"

            companies_json = json.dumps(companies, ensure_ascii=False)
            con.execute(
                """INSERT OR IGNORE INTO external_mentions
                   (source_type, source_name, title, content, url,
                    published_at, fetched_at, companies, sentiment)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                ("x_search", name, answer[:200], answer, url,
                 datetime.now().strftime("%Y-%m-%d %H:%M"),
                 datetime.now().isoformat(), companies_json, outlook))
            con.commit()

            print(f"  ✓ {name:25} {len(companies)} Unternehmen, "
                  f"{len(citations)} Tweets", flush=True)

        except json.JSONDecodeError as e:
            print(f"  ✗ {name}: JSON-Fehler: {e}", flush=True)
            if result:
                print(f"    Antwort: {result.get('answer', '')[:150]}...", flush=True)
        except Exception as e:
            print(f"  ✗ {name}: {e}", flush=True)


def parse_date(entry):
    for attr in ["published_parsed", "updated_parsed"]:
        t = getattr(entry, attr, None)
        if t:
            import time
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return datetime.now(tz=timezone.utc)

def extract_companies(title, content, source_name):
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
            return []
        content_str = msg_content.strip()
        return json.loads(content_str)
    except Exception:
        return {"companies": [], "market_outlook": "neutral"}

def fetch_rss_feeds(con, feeds):
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
                title = entry.get("title", "")
                content = entry.get("summary", "") or entry.get("description", "")
                url = entry.get("link", "")
                if not url or not title:
                    continue
                existing = con.execute("SELECT id FROM external_mentions WHERE url=?", (url,)).fetchone()
                if existing:
                    continue
                result = extract_companies(title, content, feed_cfg["name"])
                companies_json = json.dumps(result.get("companies", []), ensure_ascii=False)
                con.execute("""
                    INSERT OR IGNORE INTO external_mentions
                    (source_type, source_name, title, content, url,
                     published_at, fetched_at, companies, sentiment)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, ("rss", feed_cfg["name"], title, content[:1000], url,
                      pub_date.strftime("%Y-%m-%d %H:%M"),
                      datetime.now().isoformat(), companies_json,
                      result.get("market_outlook", "neutral")))
                con.commit()  # Lock kurz halten — nicht bis zum LLM-Call des nächsten Artikels
                count += 1
                new_articles += 1
            if count > 0:
                print(f"  ✓ {feed_cfg['name']:25} {count} neue Artikel", flush=True)
        except Exception as e:
            print(f"  ✗ {feed_cfg['name']}: {e}", flush=True)
    print(f"  → {new_articles} neue RSS-Artikel gespeichert", flush=True)

def fetch_twitter(con, accounts):
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
                params={"query": query, "queryType": "Latest"}, timeout=15)
            if r.status_code != 200:
                print(f"  ✗ @{handle}: HTTP {r.status_code}", flush=True)
                continue
            tweets = r.json().get("tweets", [])
            count = 0
            for tweet in tweets:
                tweet_id = tweet.get("id") or tweet.get("id_str", "")
                text = tweet.get("text", "")
                created = tweet.get("createdAt", "") or tweet.get("created_at", "")
                url = f"https://twitter.com/{handle}/status/{tweet_id}"
                if not text or not tweet_id:
                    continue
                existing = con.execute("SELECT id FROM external_mentions WHERE url=?", (url,)).fetchone()
                if existing:
                    continue
                try:
                    # Twitter-Daten sind immer englisch – Locale temporär umstellen
                    old_locale = locale.setlocale(locale.LC_TIME, 'C')
                    try:
                        pub_dt = datetime.strptime(created[:19], "%a %b %d %H:%M:%S")
                        pub_str = pub_dt.strftime("%Y-%m-%d %H:%M")
                    finally:
                        locale.setlocale(locale.LC_TIME, old_locale)
                except Exception:
                    pub_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                result = extract_companies(text, "", acc["name"])
                companies_json = json.dumps(result.get("companies", []), ensure_ascii=False)
                con.execute("""
                    INSERT OR IGNORE INTO external_mentions
                    (source_type, source_name, title, content, url,
                     published_at, fetched_at, companies, sentiment)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, ("twitter", acc["name"], text[:200], text, url,
                      pub_str, datetime.now().isoformat(),
                      companies_json, result.get("market_outlook", "neutral")))
                con.commit()  # Lock kurz halten — nicht bis zum nächsten LLM-Call
                count += 1
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


def get_active_x_search_queries(con):
    """Lädt generische X-Search-Queries aus source_registry DB.

    source_type='x_search', source_key = Such-Query-String.
    """
    rows = con.execute("""
        SELECT source_key as query, display_name as name, weight, category
        FROM source_registry
        WHERE source_type = 'x_search'
        AND status IN ('active', 'probation')
        AND enabled = 1
    """).fetchall()
    return [{"query": r["query"], "name": r["name"], "enabled": True,
             "weight": r["weight"], "category": r["category"]} for r in rows]

def main():
    print("📡 Social Scanner gestartet", flush=True)
    con = db_connect()
    try:
        # Quellen aus DB laden (Fallback zu sources.json)
        try:
            rss_feeds = get_active_rss_feeds(con)
            twitter_accounts = get_active_twitter_accounts(con)
            x_search_queries = get_active_x_search_queries(con)
            if not rss_feeds and not twitter_accounts and not x_search_queries:
                config = load_config()
                rss_feeds = [f for f in config.get("rss_feeds", []) if f.get("enabled")]
                twitter_accounts = [a for a in config.get("twitter_accounts", []) if a.get("enabled")]
                x_search_queries = [q for q in config.get("x_search_queries", []) if q.get("enabled")]
        except Exception:
            config = load_config()
            rss_feeds = [f for f in config.get("rss_feeds", []) if f.get("enabled")]
            twitter_accounts = [a for a in config.get("twitter_accounts", []) if a.get("enabled")]
            x_search_queries = [q for q in config.get("x_search_queries", []) if q.get("enabled")]

        fetch_rss_feeds(con, rss_feeds)
        if twitter_accounts:
            # Grok primär, twitterapi.io als Fallback
            if not fetch_twitter_grok(con, twitter_accounts):
                print("  → Fallback zu twitterapi.io", flush=True)
                fetch_twitter(con, twitter_accounts)
        if x_search_queries:
            fetch_x_search_grok(con, x_search_queries)
        inject_into_watchlist(con)

        print("\n✅ Social Scanner abgeschlossen", flush=True)
    finally:
        con.rollback()  # Offene Transaktion schließen — verhindert DB-Lock für nachfolgende Prozesse
        con.close()

if __name__ == "__main__":
    main()
