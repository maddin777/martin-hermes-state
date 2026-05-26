"""
Theme Discovery — Identifiziert taeglich 3-5 aktive Investment-Themen.
Nutzt Tavily API fuer News + Polymarket fuer zusaetzliche Signale.
"""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from thematic.lib import llm_client, tavily_client, prompt_loader, embedding_client
from thematic.lib.polymarket_client import fetch_top_movers

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)
THEMATIC_DIR = os.path.dirname(__file__)

CATEGORIES = [
    "macro", "sector", "geopolitical", "tech_disruption",
    "demographic", "regulatory",
]


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _persist_news(con, articles: list):
    """Schreibt News-Artikel in news_references (dedupliziert via URL)."""
    for a in articles:
        url = a.get("url", "")
        if not url:
            continue
        existing = con.execute(
            "SELECT id FROM news_references WHERE url = ?", (url,)
        ).fetchone()
        if existing:
            continue
        con.execute("""
            INSERT INTO news_references
            (url, title, source_domain, published_at, content_snippet, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            url,
            a.get("title", ""),
            a.get("source_domain", ""),
            date.today().isoformat(),
            a.get("content", "")[:2000],
            datetime.now().isoformat(),
        ))


def _mark_dormant_themes(con):
    """Markiert Themen die >14 Tage nicht gesehen wurden als dormant."""
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    con.execute("""
        UPDATE theme_definitions SET status = 'dormant'
        WHERE status = 'active' AND last_seen < ?
    """, (cutoff,))


def _run_theme_merge(new_theme: dict, con) -> int:
    """
    Theme-Merge-Logik. Returns theme_id (bestehend oder neu).
    Wird in theme_merge_engine.py ausgelagert und hier importiert.
    """
    from thematic.theme_merge_engine import check_and_merge
    return check_and_merge(new_theme, con)


def main():
    con = _db_connect()
    today = date.today().isoformat()

    print(f"[{datetime.now():%H:%M:%S}] Theme Discovery start...", flush=True)

    # 1. Polymarket Top-Movers (als Zusatzsignal)
    pm_movers = fetch_top_movers(min_delta_7d=0.05, limit=10)
    pm_text = "Keine signifikanten PM-Bewegungen."
    if pm_movers:
        lines = ["Top Prediction-Market-Bewegungen (7d):"]
        for m in pm_movers:
            lines.append(
                f"- \"{m['question']}\": "
                f"Price {m['current_yes_price']:.2f}, "
                f"Delta 7d: {m['delta_7d']:+.2f}, "
                f"Volume 24h: ${m['volume_24h_usd']:,}"
            )
        pm_text = "\n".join(lines)

    # 2. News via Tavily
    print(f"[{datetime.now():%H:%M:%S}] Tavily-News-Abruf...", flush=True)
    articles = tavily_client.fetch_theme_news()
    if not articles:
        print("[Theme Discovery] Keine News gefunden. Abbruch.")
        _mark_dormant_themes(con)
        con.commit()
        con.close()
        return

    _persist_news(con, articles)

    # News-Snippets formatieren
    snippets = "\n\n---\n\n".join(
        f"TITLE: {a.get('title', '')}\n"
        f"SOURCE: {a.get('source_domain', '')}\n"
        f"CONTENT: {a.get('content', '')[:600]}"
        for a in articles[:30]
    )

    # 3. LLM-Call: Theme Discovery
    print(f"[{datetime.now():%H:%M:%S}] LLM Theme Discovery...", flush=True)
    prompt = prompt_loader.load_prompt(
        "theme_discovery_v1.md",
        NEWS_SNIPPETS=snippets,
        POLYMARKET_TOP_MOVES=pm_text,
    )

    model = llm_client.get_model("theme_discovery")
    result = llm_client.call_llm(prompt, model, temperature=0.3, json_mode=True)
    data = llm_client.parse_json_response(result)

    themes = data.get("themes", [])
    if not themes:
        print("[Theme Discovery] LLM hat keine Themen identifiziert.")
        _mark_dormant_themes(con)
        con.commit()
        con.close()
        return

    print(f"[Theme Discovery] {len(themes)} Themen identifiziert.", flush=True)

    # 4. Pro Theme: Merge-Check + Insert/Update
    new_count = 0
    updated_count = 0
    for t in themes:
        name = t.get("name", "").strip()
        if not name:
            continue

        category = t.get("category", "sector")
        if category not in CATEGORIES:
            category = "sector"

        description = t.get("description", "")
        momentum = t.get("momentum", "steady")
        underreported = float(t.get("underreported_score", 0.5))
        key_sources = json.dumps(t.get("key_sources", []))
        pm_signal = t.get("pm_signal", "not_available")
        pm_rationale = t.get("pm_rationale", "")

        theme_data = {
            "name": name,
            "category": category,
            "description": description,
            "momentum": momentum,
            "underreported_score": underreported,
            "key_sources": key_sources,
            "pm_signal": pm_signal,
            "pm_rationale": pm_rationale,
        }

        existing_id = _run_theme_merge(theme_data, con)
        if existing_id > 0:
            updated_count += 1
        else:
            new_count += 1

    _mark_dormant_themes(con)
    con.commit()
    con.close()

    print(
        f"[{datetime.now():%H:%M:%S}] Theme Discovery DONE: "
        f"{new_count} neu, {updated_count} aktualisiert",
        flush=True,
    )


if __name__ == "__main__":
    main()