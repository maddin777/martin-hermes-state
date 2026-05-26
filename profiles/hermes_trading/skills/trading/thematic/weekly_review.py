"""
Weekly Review — Woechentliche Checks (Sonntag 08:00).
- Theme-Lifecycle-Review
- Position-30-Tage-Review
- Tax-Year-Summary konsolidieren
"""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from thematic.lib import llm_client, prompt_loader

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _theme_lifecycle_review(con):
    """Markiert Themen mit >14 Tagen without update als dormant."""
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    con.execute("""
        UPDATE theme_definitions SET status = 'dormant'
        WHERE status = 'active' AND last_seen < ?
    """, (cutoff,))
    con.commit()
    print(f"[Weekly] Theme-Lifecycle done.", flush=True)


def _position_30day_review(con):
    """Review von Positionen die >=30 Tage offen sind."""
    cutoff = (date.today() - timedelta(days=30)).isoformat()

    positions = con.execute("""
        SELECT * FROM positions
        WHERE status = 'open' AND entry_date <= ?
    """, (cutoff,)).fetchall()

    if not positions:
        print("[Weekly] Keine 30d-Positionen.")
        return

    model = llm_client.get_model("thesis_monitor")

    for pos in positions:
        thesis = pos.get("thesis_text") or "Keine These."

        # Thesis-Check-Historie
        checks = con.execute("""
            SELECT status, confidence, rationale FROM thesis_status_log
            WHERE position_id = ? ORDER BY check_date DESC LIMIT 10
        """, (pos["id"],)).fetchall()

        summary = "\n".join(
            f"- {c['check_date']}: {c['status']} (Conf={c['confidence']:.0%})"
            for c in checks
        )

        theme_row = con.execute(
            "SELECT * FROM theme_definitions WHERE id = ?",
            (pos.get("thesis_theme_id"),)
        ).fetchone()

        prompt = prompt_loader.load_prompt(
            "position_review_v1.md",
            ticker=pos["ticker"],
            company_name=pos.get("name", pos["ticker"]),
            entry_date=(pos.get("entry_date") or "")[:10],
            thesis_text=thesis,
            pnl_pct=f"{pos.get('pnl_pct') or 0:.1f}%",
            thesis_status=pos.get("thesis_current_status") or "intact",
            theme_momentum=dict(theme_row).get("momentum", "steady") if theme_row else "steady",
            thesis_check_summary=summary,
        )

        result = llm_client.call_llm(prompt, model, temperature=0.3, json_mode=True)
        data = llm_client.parse_json_response(result)

        action = data.get("action", "HOLD")
        rationale = data.get("rationale", "")

        print(f"  {pos['ticker']}: {action} — {rationale[:100]}", flush=True)

    con.commit()
    print(f"[Weekly] 30d-Review done: {len(positions)} Positionen.", flush=True)


def main():
    con = _db_connect()
    print(f"[Weekly Review] {date.today().isoformat()}", flush=True)

    _theme_lifecycle_review(con)
    _position_30day_review(con)

    con.close()
    print("[Weekly Review] DONE.", flush=True)


if __name__ == "__main__":
    main()