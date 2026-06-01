"""
Source Lifecycle Manager
========================
Wöchentlicher Job (Sonntag 07:00):
1. EVALUATE  — Performance aller aktiven Quellen bewerten
2. DEMOTE    — Schlechte Quellen suspendieren/entfernen
3. PROMOTE   — Gute Probation-Quellen zu Active befördern
4. DISCOVER  — Neue Quellen proaktiv finden und als Candidate eintragen

Datenfluss:
  candidate → probation → active ↔ suspended → removed
                ↓
             rejected
"""
import json, os, sqlite3, math, requests
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
from datetime import datetime, timedelta
from config import DB_PATH, SOURCES_CONFIG_PATH

# SOURCES_CONFIG_PATH → SOURCES_CONFIG_PATH aus config.py
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
DISCOVERY_MODEL = "meta-llama/llama-4-scout"

THRESHOLDS = {
    "min_trades_for_eval": 5,
    "suspend_win_rate": 0.30,
    "suspend_consecutive_losses": 5,
    "suspend_avg_pnl": -2.0,
    "remove_win_rate": 0.15,
    "remove_no_mention_days": 90,
    "promote_min_trades": 5,
    "promote_min_win_rate": 0.45,
    "promote_min_avg_pnl": -0.5,
    "candidate_max_age_days": 30,
    "boost_win_rate": 0.60,
    "boost_max_weight": 2.5,
    "penalize_win_rate": 0.35,
    "penalize_min_weight": 0.3,
    "max_candidates": 10,
    "min_subscribers_yt": 10000,
    "min_followers_x": 5000,
}


def ensure_schema(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS source_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            language TEXT DEFAULT 'en',
            region TEXT DEFAULT 'global',
            category TEXT DEFAULT 'general',
            status TEXT DEFAULT 'candidate',
            status_changed_at TEXT,
            added_at TEXT DEFAULT (datetime('now')),
            added_by TEXT DEFAULT 'manual',
            weight REAL DEFAULT 1.0,
            enabled INTEGER DEFAULT 1,
            scan_interval_hours INTEGER DEFAULT 6,
            total_mentions INTEGER DEFAULT 0,
            total_bought INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0,
            win_rate_alltime REAL DEFAULT 0,
            win_rate_90d REAL DEFAULT 0,
            avg_pnl_per_trade REAL DEFAULT 0,
            avg_conviction_at_buy REAL DEFAULT 0,
            last_mention_date TEXT,
            last_win_date TEXT,
            consecutive_losses INTEGER DEFAULT 0,
            probation_start TEXT,
            probation_trades INTEGER DEFAULT 0,
            probation_wins INTEGER DEFAULT 0,
            probation_target_trades INTEGER DEFAULT 5,
            discovery_reason TEXT,
            rejection_reason TEXT,
            subscriber_count INTEGER,
            content_frequency TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_source_status ON source_registry(status, source_type);
    """)


def migrate_existing_sources(con):
    count = con.execute("SELECT COUNT(*) as cnt FROM source_registry").fetchone()["cnt"]
    if count > 0:
        return
    print("🔄 Migriere bestehende Quellen in source_registry...", flush=True)
    try:
        with open(SOURCES_CONFIG_PATH) as f:
            rss_feeds = json.load(f)
        for feed in rss_feeds.get("rss_feeds", []):
            lang = feed.get("language", "en")
            region = "DACH" if lang == "de" else "US" if lang == "en" else "global"
            con.execute("""
                INSERT OR IGNORE INTO source_registry
                (source_type, source_key, display_name, language, region,
                 category, status, weight, enabled, added_by)
                VALUES ('rss', ?, ?, ?, ?, 'general', 'active', ?, ?, 'migration')
            """, (feed["url"], feed["name"], lang, region,
                  feed.get("weight", 1.0), 1 if feed.get("enabled", True) else 0))
    except Exception as e:
        print(f"  ⚠ RSS-Migration: {e}")

    # BUG-FIX: source_key = echte YT-URL (nicht display_name)
    # Format: (display_name, url, region, category, language)
    yt_channels = [
        # DACH
        ("mario lochner",             "https://www.youtube.com/@mario.lochner",                   "DACH", "general",      "de"),
        ("maxim investiert",           "https://www.youtube.com/@maximinvestiert",                  "DACH", "growth",       "de"),
        ("tipp checker",               "https://www.youtube.com/@tipp-checker",                     "DACH", "tech_analysis","de"),
        ("grey x capital",             "https://www.youtube.com/@GREYxCAPITAL",                     "DACH", "growth",       "de"),
        ("moritz hessel",              "https://www.youtube.com/@moritz.hessel.official",            "DACH", "general",      "de"),
        ("beating beta",               "https://www.youtube.com/@BeatingBeta_official",              "DACH", "general",      "de"),
        ("techaktien",                 "https://www.youtube.com/@Techaktien",                        "DACH", "sector_specific","de"),
        ("der aktionaer",              "https://www.youtube.com/@der.aktionaer",                     "DACH", "general",      "de"),
        ("ohne aktien wird schwer",    "https://www.youtube.com/@ohneaktienwirdschwer-podcast",      "DACH", "general",      "de"),
        ("aktienfinder",               "https://www.youtube.com/@Aktienfinder",                      "DACH", "value",        "de"),
        ("ticker symbol: you",         "https://www.youtube.com/@TickerSymbolYOU",                   "DACH", "growth",       "de"),
        ("markus koch closing bell",   "https://www.youtube.com/@markus_koch",                       "DACH", "macro",        "de"),
        # International EN
        ("real vision",                "https://www.youtube.com/@RealVisionFinance",                 "US",   "macro",        "en"),
        ("patrick boyle",              "https://www.youtube.com/@PBoyle",                            "UK",   "macro",        "en"),
        ("tastylive",                  "https://www.youtube.com/@tastylive",                          "US",   "options",      "en"),
        ("financial education",        "https://www.youtube.com/@FinancialEducation",                "US",   "growth",       "en"),
        ("meet kevin",                 "https://www.youtube.com/@MeetKevin",                          "US",   "growth",       "en"),
        ("trader university",          "https://www.youtube.com/@TraderUniversity",                   "US",   "tech_analysis","en"),
        ("joseph carlson show",        "https://www.youtube.com/@JosephCarlsonShow",                  "US",   "value",        "en"),
        ("the swedish investor",       "https://www.youtube.com/@TheSwedishInvestor",                 "global","value",       "en"),
    ]
    for (name, url, region, cat, lang) in yt_channels:
        con.execute("""
            INSERT OR IGNORE INTO source_registry
            (source_type, source_key, display_name, language, region,
             category, status, weight, enabled, added_by)
            VALUES ('youtube', ?, ?, ?, ?, ?, 'active', 1.0, 1, 'migration')
        """, (url, name, lang, region, cat))

    # Internationale RSS-Feeds
    rss_intl = [
        ("FT Alphaville", "https://www.ft.com/alphaville?format=rss", "UK", "en", "general"),
        ("Barron's", "https://www.barrons.com/feed", "US", "en", "general"),
        ("BörsenNEWS.de", "https://www.boersennews.de/rss/", "DACH", "de", "general"),
    ]
    for name, url, region, lang, cat in rss_intl:
        con.execute("""
            INSERT OR IGNORE INTO source_registry
            (source_type, source_key, display_name, language, region,
             category, status, weight, enabled, added_by)
            VALUES ('rss', ?, ?, ?, ?, ?, 'active', 1.0, 1, 'seed')
        """, (url, name, lang, region, cat))

    # Internationale Twitter-Accounts
    tw_intl = [
        ("unusual_whales", "Unusual Whales", "data", "US", "en"),
        ("MacroAl", "Alfonso Peccatiello", "macro", "global", "en"),
        ("GameofTrades_", "Game of Trades", "macro", "global", "en"),
        ("TrendSpider", "TrendSpider", "tech_analysis", "US", "en"),
        ("elerianm", "Mohamed El-Erian", "macro", "US", "en"),
        ("PeterLBrandt", "Peter Brandt", "tech_analysis", "US", "en"),
    ]
    for handle, name, cat, region, lang in tw_intl:
        con.execute("""
            INSERT OR IGNORE INTO source_registry
            (source_type, source_key, display_name, language, region,
             category, status, weight, enabled, added_by)
            VALUES ('twitter', ?, ?, ?, ?, ?, 'active', 1.0, 1, 'seed')
        """, (handle, name, lang, region, cat))

    con.commit()
    print("  ✅ Migration abgeschlossen")


def evaluate_active_sources(con):
    print("📊 Evaluiere aktive Quellen...", flush=True)
    active = con.execute("""
        SELECT * FROM source_registry WHERE status IN ('active', 'probation')
    """).fetchall()
    for src in active:
        sq = con.execute("""
            SELECT SUM(mentions_30d) as mentions, SUM(bought_30d) as bought,
                   AVG(win_rate_30d) as avg_wr, AVG(avg_pnl_30d) as avg_pnl
            FROM source_quality WHERE channel = ? AND date >= date('now', '-90 days')
        """, (src["display_name"],)).fetchone()
        recent = con.execute("""
            SELECT pnl_eur FROM positions WHERE status='closed'
            AND source_channel LIKE ? ORDER BY exit_date DESC LIMIT 10
        """, (f"%{src['display_name']}%",)).fetchall()
        consec = 0
        for t in recent:
            if (t["pnl_eur"] or 0) <= 0:
                consec += 1
            else:
                break
        total_bought = sq["bought"] or 0
        win_rate = sq["avg_wr"] or 0
        avg_pnl = sq["avg_pnl"] or 0
        con.execute("""
            UPDATE source_registry SET win_rate_90d=?, avg_pnl_per_trade=?,
                total_bought=total_bought+?, consecutive_losses=?,
                last_mention_date=COALESCE(
                    (SELECT MAX(mention_date) FROM watchlist_mentions WHERE channel=?),
                    last_mention_date)
            WHERE id=?
        """, (round(win_rate, 3), round(avg_pnl, 2), total_bought, consec,
              src["display_name"], src["id"]))
        icon = "🟢" if win_rate >= 0.5 else "🟡" if win_rate >= 0.35 else "🔴"
        print(f"  {icon} {src['display_name']:30} WR={win_rate:.0%} n={total_bought} avg_pnl={avg_pnl:+.1f}% consec_L={consec}")


def demote_bad_sources(con):
    print("\n🔻 Prüfe Demotions...", flush=True)
    T = THRESHOLDS
    now = datetime.now().isoformat()
    to_suspend = con.execute("""
        SELECT * FROM source_registry WHERE status='active' AND total_bought >= ?
        AND (win_rate_90d < ? OR consecutive_losses >= ? OR avg_pnl_per_trade < ?)
    """, (T["min_trades_for_eval"], T["suspend_win_rate"],
          T["suspend_consecutive_losses"], T["suspend_avg_pnl"])).fetchall()
    for src in to_suspend:
        reasons = []
        if src["win_rate_90d"] < T["suspend_win_rate"]:
            reasons.append(f"WR={src['win_rate_90d']:.0%}")
        if src["consecutive_losses"] >= T["suspend_consecutive_losses"]:
            reasons.append(f"{src['consecutive_losses']} consec losses")
        if src["avg_pnl_per_trade"] < T["suspend_avg_pnl"]:
            reasons.append(f"avg_pnl={src['avg_pnl_per_trade']:+.1f}%")
        con.execute("UPDATE source_registry SET status='suspended', enabled=0, status_changed_at=?, rejection_reason=? WHERE id=?",
                    (now, "; ".join(reasons), src["id"]))
        print(f"  ⏸️  SUSPENDED: {src['display_name']:30} ({'; '.join(reasons)})")

    to_remove = con.execute("""
        SELECT * FROM source_registry WHERE status IN ('active','suspended')
        AND ((total_bought >= 10 AND win_rate_90d < ?)
             OR (last_mention_date < date('now', ? || ' days'))
             OR (last_mention_date IS NULL AND added_at < date('now', ? || ' days')))
    """, (T["remove_win_rate"], f"-{T['remove_no_mention_days']}",
          f"-{T['remove_no_mention_days']}")).fetchall()
    for src in to_remove:
        con.execute("UPDATE source_registry SET status='removed', enabled=0, status_changed_at=?, rejection_reason=COALESCE(rejection_reason||'; ','')||'Auto-removed' WHERE id=?",
                    (now, src["id"]))
        print(f"  ❌ REMOVED: {src['display_name']:30}")

    old = con.execute("SELECT * FROM source_registry WHERE status='candidate' AND added_at < date('now', ? || ' days')",
                       (f"-{T['candidate_max_age_days']}",)).fetchall()
    for src in old:
        con.execute("UPDATE source_registry SET status='rejected', status_changed_at=?, rejection_reason='Timeout: no promotion within 30d' WHERE id=?",
                    (now, src["id"]))
        print(f"  🚫 REJECTED (timeout): {src['display_name']}")


def promote_good_sources(con):
    print("\n🔺 Prüfe Promotions...", flush=True)
    T = THRESHOLDS
    now = datetime.now().isoformat()
    for src in con.execute("SELECT * FROM source_registry WHERE status='probation'").fetchall():
        if src["probation_trades"] < T["promote_min_trades"]:
            print(f"  ⏳ {src['display_name']:30} Probation: {src['probation_trades']}/{T['promote_min_trades']} Trades")
            continue
        wr = src["probation_wins"] / src["probation_trades"] if src["probation_trades"] > 0 else 0
        if wr >= T["promote_min_win_rate"] and src["avg_pnl_per_trade"] >= T["promote_min_avg_pnl"]:
            con.execute("UPDATE source_registry SET status='active', weight=1.0, status_changed_at=? WHERE id=?",
                        (now, src["id"]))
            print(f"  🎉 PROMOTED: {src['display_name']:30} WR={wr:.0%}")
        else:
            con.execute("UPDATE source_registry SET status='rejected', status_changed_at=?, rejection_reason=? WHERE id=?",
                        (now, f"Probation failed: WR={wr:.0%}", src["id"]))
            print(f"  🚫 REJECTED: {src['display_name']} WR={wr:.0%}")


def adjust_weights(con):
    print("\n⚖️  Gewichte anpassen...", flush=True)
    T = THRESHOLDS
    for src in con.execute("SELECT * FROM source_registry WHERE status='active' AND total_bought >= ?",
                            (T["min_trades_for_eval"],)).fetchall():
        old_w = src["weight"]
        if src["win_rate_90d"] >= T["boost_win_rate"]:
            new_w = round(min(T["boost_max_weight"], old_w * 1.15), 2)
            direction = "↑"
        elif src["win_rate_90d"] < T["penalize_win_rate"]:
            new_w = round(max(T["penalize_min_weight"], old_w * 0.80), 2)
            direction = "↓"
        else:
            new_w = old_w
            direction = "="
        if new_w != old_w:
            con.execute("UPDATE source_registry SET weight=? WHERE id=?", (new_w, src["id"]))
            print(f"  {direction} {src['display_name']:30} {old_w:.2f} → {new_w:.2f} (WR={src['win_rate_90d']:.0%})")


def discover_new_sources(con):
    print("\n🔍 Suche neue Quellen...", flush=True)
    T = THRESHOLDS
    current_cands = con.execute("SELECT COUNT(*) as cnt FROM source_registry WHERE status='candidate'").fetchone()["cnt"]
    slots = T["max_candidates"] - current_cands
    if slots <= 0:
        print(f"  ⏳ Candidate-Slots voll ({current_cands}/{T['max_candidates']})")
        return
    if not OPENROUTER_KEY:
        print("  ⚠ OPENROUTER_API_KEY nicht gesetzt – Discovery übersprungen")
        return
    coverage = con.execute("SELECT region, category, COUNT(*) as cnt FROM source_registry WHERE status IN ('active','probation') GROUP BY region, category").fetchall()
    existing = {(r["region"], r["category"]): r["cnt"] for r in coverage}
    gaps = []
    for region in ["US", "DACH", "UK", "Asia", "global"]:
        for cat in ["macro", "tech_analysis", "growth", "value", "sector_specific"]:
            if existing.get((region, cat), 0) < 2:
                gaps.append({"region": region, "category": cat})
    if not gaps:
        print("  ✅ Keine Coverage-Lücken")
        return
    existing_names = [r[0] for r in con.execute("SELECT display_name FROM source_registry").fetchall()]
    for gap in sorted(gaps, key=lambda g: existing.get((g["region"], g["category"]), 0))[:3]:
        if slots <= 0:
            break
        # BUGFIX: f-String damit gap['region'] und gap['category'] interpoliert werden
        prompt = f"""Du bist ein Finanzmarkt-Experte. Ich suche hochwertige Informationsquellen für systematisches Aktien-Trading.

GESUCHTE LÜCKE:
- Region: {gap['region']}
- Kategorie: {gap['category']}
- Typ: YouTube-Kanäle, RSS-Feeds/Blogs, oder X/Twitter-Accounts

BEREITS VORHANDEN:
{json.dumps(existing_names[:30], indent=2)}

ANFORDERUNGEN:
- Quellen müssen regelmäßig Inhalte veröffentlichen (mind. wöchentlich)
- Konkrete Aktien-Erwähnungen oder Sektor-Analysen
- Nachweisbare Track-Records oder hohe fachliche Qualität

Antworte NUR mit einem JSON-Array von maximal 3 Vorschlägen (kein Markdown, kein Kommentar):
[{{"name": "Kanalname", "type": "youtube|rss|twitter", "url_or_handle": "URL oder @handle",
  "language": "en|de|fr|ja|zh", "reason": "Warum diese Quelle gut ist (1 Satz)",
  "estimated_frequency": "daily|weekly", "estimated_audience": 50000}}]"""

        # Modell-Fallback-Kette
        models_to_try = [
            "deepseek/deepseek-v4-flash",
            "openrouter/owl-alpha",
            "openai/gpt-4o-mini",
        ]

        resp_text = None
        used_model = None
        for model in models_to_try:
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                             "Content-Type": "application/json"},
                    json={"model": model,
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": 600, "temperature": 0.3},
                    timeout=30
                )
                data = resp.json()
                # API-Fehler sichtbar machen
                if "error" in data:
                    print(f"  ⚠ Modell {model}: {data['error'].get('message', data['error'])}")
                    continue
                resp_text = data["choices"][0]["message"]["content"].strip()
                used_model = model
                break
            except Exception as e:
                print(f"  ⚠ Modell {model} nicht erreichbar: {e}")
                continue

        if not resp_text:
            print(f"  ❌ Alle Modelle fehlgeschlagen für {gap['region']}/{gap['category']}")
            continue

        print(f"  🤖 {used_model} → {gap['region']}/{gap['category']}", flush=True)

        try:
            # JSON aus Antwort extrahieren (Modelle fügen manchmal Markdown hinzu)
            clean = resp_text.strip()
            if "```" in clean:
                import re
                match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', clean, re.DOTALL)
                if match:
                    clean = match.group(1)
            # Falls kein Array: ersten [ ... ] Block suchen
            if not clean.startswith("["):
                start = clean.find("[")
                end   = clean.rfind("]") + 1
                if start >= 0 and end > start:
                    clean = clean[start:end]

            suggestions = json.loads(clean)
            for s in suggestions:
                if slots <= 0:
                    break
                audience = s.get("estimated_audience", 0)
                if s["type"] == "youtube" and audience < T["min_subscribers_yt"]:
                    continue
                if s["type"] == "twitter" and audience < T["min_followers_x"]:
                    continue
                dup = con.execute(
                    "SELECT id FROM source_registry WHERE display_name=? OR source_key=?",
                    (s["name"], s.get("url_or_handle", ""))
                ).fetchone()
                if dup:
                    continue
                con.execute("""
                    INSERT INTO source_registry
                    (source_type, source_key, display_name, language, region, category,
                     status, added_by, discovery_reason, subscriber_count, content_frequency)
                    VALUES (?, ?, ?, ?, ?, ?, 'candidate', 'discovery_llm', ?, ?, ?)
                """, (s["type"], s.get("url_or_handle", ""), s["name"],
                      s.get("language", "en"), gap["region"], gap["category"],
                      s.get("reason", "LLM discovery"), audience,
                      s.get("estimated_frequency", "weekly")))
                print(f"  🆕 CANDIDATE: {s['name']:30} [{s['type']}] {gap['region']}/{gap['category']}")
                slots -= 1
            con.commit()
        except Exception as e:
            print(f"  ❌ JSON-Parse Fehler: {e}")
            print(f"     Antwort war: {resp_text[:200]}")


def activate_candidates(con):
    print("\n🔄 Candidates → Probation...", flush=True)
    now = datetime.now().isoformat()
    ready = con.execute("""
        SELECT * FROM source_registry WHERE status='candidate'
        AND source_key IS NOT NULL AND source_key != ''
        AND added_at < date('now', '-7 days')
    """).fetchall()
    for src in ready:
        con.execute("""
            UPDATE source_registry SET status='probation', probation_start=?,
                status_changed_at=?, enabled=1, weight=0.5 WHERE id=?
        """, (now, now, src["id"]))
        print(f"  🧪 PROBATION: {src['display_name']:30} (weight=0.5)")


def generate_source_report(con):
    print("\n📋 Quellen-Report:", flush=True)
    for status in ['active', 'probation', 'suspended', 'candidate', 'removed']:
        cnt = con.execute("SELECT COUNT(*) as cnt FROM source_registry WHERE status=?", (status,)).fetchone()["cnt"]
        icon = {"active": "🟢", "probation": "🧪", "suspended": "⏸️", "candidate": "🆕", "removed": "❌"}.get(status, "?")
        print(f"  {icon} {status:12}: {cnt}")
    print("\n  🏆 Top 5 (nach WR, min 5 Trades):")
    for t in con.execute("SELECT display_name, win_rate_90d, total_bought, avg_pnl_per_trade, weight FROM source_registry WHERE status='active' AND total_bought >= 5 ORDER BY win_rate_90d DESC LIMIT 5").fetchall():
        print(f"    {t['display_name']:30} WR={t['win_rate_90d']:.0%} n={t['total_bought']} pnl={t['avg_pnl_per_trade']:+.1f}% w={t['weight']:.1f}")


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    ensure_schema(con)
    migrate_existing_sources(con)
    evaluate_active_sources(con)
    demote_bad_sources(con)
    promote_good_sources(con)
    adjust_weights(con)
    discover_new_sources(con)
    activate_candidates(con)
    generate_source_report(con)
    con.commit()
    con.close()
    print("\n✅ Source Lifecycle abgeschlossen", flush=True)


if __name__ == "__main__":
    main()
