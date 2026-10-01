"""
Prediction Market Scanner — Taegliches Scannen von Polymarket.
Market-Klassifikation via LLM, Verknuepfung mit Themes/Tickers.
"""
import json
import os
import sys
import sqlite3
from datetime import date, datetime

# thematic/ liegt unter skills/trading/, nicht unter scripts/
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")

from thematic.lib import polymarket_client, llm_client, prompt_loader
from config import db_connect

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)

PM_MIN_VOLUME = 100_000
PM_MIN_24H = 0  # 5_000


def _db_connect():
    con = db_connect()
    return con


def _normalize_market(m: dict, market_id: str, today: str) -> dict:
    """Übernimmt einen Markt aus polymarket_client.fetch_trending_markets.

    M18 (30.09.2026): Der Scanner las die Schlüssel "probability"/"price" (Preis), "volume" (Volumen) und
    "price_change_7d", die fetch_trending_markets gar nicht liefert. Alle 812 gespeicherten Märkte standen deshalb
    auf Preis 0,5, Volumen 0 und delta_7d 0. Richtig: current_yes_price, total_volume_usd; die Deltas kommen aus der
    Preishistorie (enrich_with_history) und bleiben ohne Historie None."""
    yes_price = m.get("current_yes_price")
    total_vol = m.get("total_volume_usd", 0) or 0
    return {
        "market_id": market_id,
        "token_id": m.get("token_id", ""),
        "platform": "polymarket",
        "question": m.get("question", ""),
        "category": m.get("category", "other"),
        "resolution_date": m.get("resolution_date", ""),
        "current_yes_price": yes_price,
        "price_7d_ago": None,
        "price_30d_ago": None,
        "delta_7d": None,
        "delta_24h": 0,
        "volume_24h_usd": m.get("volume_24h_usd", 0) or 0,
        "total_volume_usd": total_vol,
        "liquidity_score": min(total_vol / 1_000_000, 1.0),
        "last_updated": today,
    }


def _get_active_theme_list(con) -> str:
    """Erstellt Liste aktiver Themen fuer LLM-Klassifikation."""
    themes = con.execute("""
        SELECT id, name, description FROM theme_definitions
        WHERE status IN ('active', 'decelerating')
    """).fetchall()

    if not themes:
        return "Keine aktiven Themen."

    lines = []
    for t in themes:
        lines.append(f"- ID {t['id']}: {t['name']} — {t['description'][:150]}")
    return "\n".join(lines)


def main():
    con = _db_connect()
    today = date.today().isoformat()

    print(f"[PM Scanner] Fetching Polymarket...", flush=True)

    markets = polymarket_client.fetch_trending_markets(
        min_volume=PM_MIN_VOLUME, limit=500
    )

    if not markets:
        print("[PM Scanner] Keine Maerkte empfangen.")
        con.close()
        return

    # Filter
    filtered = []
    for m in markets:
        market_id = m.get("market_id", m.get("slug", ""))
        volume_24h = m.get("volume_24h_usd", 0)
        res_date = m.get("resolution_date", "")
        category = m.get("category", "other")

        if volume_24h < PM_MIN_24H:
            continue
        if category in ("other", "sport"):
            continue

        filtered.append(_normalize_market(m, market_id, today))

    polymarket_client.enrich_with_history(filtered)

    print(f"[PM Scanner] {len(filtered)} Markets nach Filter.", flush=True)

    # UPSERT
    for m in filtered:
        existing = con.execute(
            "SELECT id, classification_done FROM prediction_markets WHERE market_id = ?",
            (m["market_id"],)
        ).fetchone()

        if existing:
            con.execute("""
                UPDATE prediction_markets SET
                    current_yes_price = ?, price_7d_ago = ?, price_30d_ago = ?, delta_7d = ?,
                    delta_24h = ?, volume_24h_usd = ?, total_volume_usd = ?,
                    liquidity_score = ?, last_updated = ?
                WHERE id = ?
            """, (
                m["current_yes_price"], m["price_7d_ago"], m["price_30d_ago"], m["delta_7d"],
                m["delta_24h"], m["volume_24h_usd"], m["total_volume_usd"],
                m["liquidity_score"], m["last_updated"], existing["id"],
            ))
        else:
            con.execute("""
                INSERT INTO prediction_markets
                (platform, market_id, question, category, resolution_date,
                 current_yes_price, price_7d_ago, price_30d_ago,
                 delta_7d, delta_24h, volume_24h_usd, total_volume_usd,
                 liquidity_score, status, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """, (
                m["platform"], m["market_id"], m["question"], m["category"],
                m["resolution_date"], m["current_yes_price"], m["price_7d_ago"],
                m["price_30d_ago"], m["delta_7d"], m["delta_24h"],
                m["volume_24h_usd"], m["total_volume_usd"],
                m["liquidity_score"], m["last_updated"],
            ))

    # LLM-Klassifikation fuer neue Markets
    new_markets = con.execute("""
        SELECT * FROM prediction_markets WHERE classification_done = 0 LIMIT 20
    """).fetchall()

    if new_markets:
        print(f"[PM Scanner] Klassifiziere {len(new_markets)} neue Maerkte...", flush=True)
        theme_list = _get_active_theme_list(con)
        model = llm_client.get_model("pm_classifier")

        for nm in new_markets:
            prompt = prompt_loader.load_prompt(
                "pm_market_classifier_v1.md",
                question=nm["question"],
                category=(nm["category"] or "other"),
                resolution_date=nm["resolution_date"] or "unknown",
                list_of_active_theme_names_and_descriptions=theme_list,
            )

            result = llm_client.call_llm(prompt, model, temperature=0.3, json_mode=True)
            data = llm_client.parse_json_response(result)

            related_tickers = json.dumps(
                (data.get("related_tickers_positive") or []) +
                (data.get("related_tickers_negative") or [])
            )
            related_themes = json.dumps(data.get("related_theme_ids") or [])
            strength = data.get("connection_strength", "none")

            con.execute("""
                UPDATE prediction_markets SET
                    related_tickers = ?, related_themes = ?,
                    classification_done = 1
                WHERE id = ?
            """, (related_tickers, related_themes, nm["id"]))

            print(f"  {nm['question'][:60]}... → {strength}", flush=True)

    con.commit()
    con.close()
    print(f"[PM Scanner] DONE.", flush=True)


if __name__ == "__main__":
    main()
