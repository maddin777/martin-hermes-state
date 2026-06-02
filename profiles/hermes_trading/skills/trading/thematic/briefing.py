"""
Briefing — Taegliches Markdown-Briefing mit allen Thematic-Signalen.
Speichert in DB + sendet via Telegram.
"""
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import sqlite3
import requests
from datetime import date, datetime

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_HOME_CHANNEL"]


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_HOME_CHANNEL:
        print(msg)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_HOME_CHANNEL, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"[Briefing] Telegram-Fehler: {e}")


def _build_briefing_md(con, today: str) -> str:
    sections = []

    # 1. Neue Themen
    new_themes = con.execute("""
        SELECT * FROM theme_definitions
        WHERE first_detected = ? AND status = 'active'
        ORDER BY coverage_count DESC
    """, (today,)).fetchall()

    if new_themes:
        sections.append(f"## 🆕 Neue Themen ({len(new_themes)})\n")
        for t in new_themes:
            pm = t["pm_confirmation_status"] or "no_data"
            pm_marker = "🎯" if pm == "supporting" else "⚡" if pm == "mixed" else ""
            sections.append(
                f"### {t['name']} {pm_marker}\n"
                f"*Erkannt: {t['first_detected']} | Momentum: {t['momentum']} | "
                f"Underreported: {t['underreported_score']:.1f}*\n\n"
                f"{t['description']}\n"
            )

            # Beneficiaries
            bens = con.execute("""
                SELECT * FROM theme_beneficiaries
                WHERE theme_id = ? AND status IN ('candidate', 'watching')
            """, (t["id"],)).fetchall()

            by_type = {}
            for b in bens:
                pt = b["play_type"] or "other"
                by_type.setdefault(pt, []).append(
                    (b["ticker"], b["llm_confidence_count"] or 0)
                )

            for pt in ["direct", "picks_and_shovels", "second_derivative", "loser"]:
                items = by_type.get(pt, [])
                if items:
                    names = ", ".join(f"{tick}" + ("⭐" if conf >= 3 else "")
                                     for tick, conf in items)
                    sections.append(f"- **{pt.replace('_', ' ').title()}:** {names}\n")

            sections.append("\n---\n")

    # 2. RED ALERTS (Broken Thesen)
    broken = con.execute("""
        SELECT p.*, tsl.confidence, tsl.rationale, tsl.check_date
        FROM thesis_status_log tsl
        JOIN positions p ON tsl.position_id = p.id
        WHERE tsl.status = 'BROKEN' AND tsl.confidence >= 0.7
        AND tsl.check_date = ?
        ORDER BY tsl.check_date DESC
    """, (today,)).fetchall()

    if broken:
        sections.append(f"## 🔴 RED ALERTS ({len(broken)})\n")
        for b in broken:
            sections.append(
                f"### {b['name']} ({b['ticker']})\n"
                f"- **Exit-Empfehlung:** These BROKEN (Conf={b['confidence']:.0%})\n"
                f"- **Rationale:** {b['rationale']}\n"
            )
        sections.append("\n---\n")

    # 3. YELLOW ALERTS
    weakening = con.execute("""
        SELECT p.*, tsl.confidence, tsl.rationale
        FROM thesis_status_log tsl
        JOIN positions p ON tsl.position_id = p.id
        WHERE tsl.status = 'WEAKENING' AND tsl.check_date = ?
        ORDER BY tsl.check_date DESC
    """, (today,)).fetchall()

    if weakening:
        sections.append(f"## 🟡 YELLOW ({len(weakening)})\n")
        for w in weakening:
            sections.append(
                f"- **{w['name']} ({w['ticker']})**: {w['rationale'][:200]}\n"
            )
        sections.append("\n---\n")

    # 4. Active Positions
    active = con.execute("""
        SELECT * FROM positions WHERE status = 'open'
        ORDER BY entry_date DESC
    """).fetchall()

    if active:
        sections.append(f"## 🟢 Active Positions ({len(active)})\n")
        for p in active:
            thesis_status = p["thesis_current_status"] or "intact"
            pnl_eur = p["pnl_eur"] or 0
            emoji = "✅" if thesis_status == "INTACT" else "⚠"
            sections.append(
                f"- {emoji} **{p['name']} ({p['ticker']})**: "
                f"Entry {p['entry_price']:.2f}, P&L {pnl_eur:+.2f}€, "
                f"Thesis: {thesis_status}\n"
            )
        sections.append("\n---\n")

    # 5. Theme Health
    themes = con.execute("""
        SELECT t.*, COUNT(b.id) as beneficiary_count
        FROM theme_definitions t
        LEFT JOIN theme_beneficiaries b ON t.id = b.theme_id AND b.status != 'archived'
        WHERE t.status IN ('active', 'decelerating')
        GROUP BY t.id
        ORDER BY t.last_seen DESC
        LIMIT 10
    """).fetchall()

    if themes:
        sections.append("## 📊 Theme Health\n\n")
        sections.append("| Theme | Age | Status | Beneficiaries | PM |\n")
        sections.append("|-------|-----|--------|---------------|----|\n")
        for t in themes:
            pm = "🎯" if t["pm_confirmation_status"] == "supporting" else \
                 "⚡" if t["pm_confirmation_status"] == "mixed" else "—"
            sections.append(
                f"| {t['name'][:40]} | {t['first_detected']} | "
                f"{t['momentum']} | {t['beneficiary_count']} | {pm} |\n"
            )
        sections.append("\n")

    return "".join(sections)


def main():
    con = _db_connect()
    today = date.today().isoformat()

    md_content = _build_briefing_md(con, today)

    # Zaehler
    red_count = md_content.count("RED ALERT")
    yellow_count = md_content.count("YELLOW")
    new_theme_count = md_content.count("Neue Themen")

    # In DB speichern
    existing = con.execute(
        "SELECT id FROM briefings WHERE date = ?", (today,)
    ).fetchone()

    if existing:
        con.execute("""
            UPDATE briefings SET
                content_md = ?,
                new_themes_count = ?,
                red_alerts_count = ?,
                yellow_alerts_count = ?
            WHERE date = ?
        """, (md_content, new_theme_count, red_count, yellow_count, today))
    else:
        con.execute("""
            INSERT INTO briefings
            (date, content_md, new_themes_count, red_alerts_count,
             yellow_alerts_count, new_candidates_count, thesis_breaks_count)
            VALUES (?, ?, ?, ?, ?, 0, 0)
        """, (today, md_content, new_theme_count, red_count, yellow_count))

    con.commit()
    con.close()

    # Telegram (nur wenn Alerts)
    if red_count > 0 or yellow_count > 0:
        header = (
            f"📋 <b>Hermes Thematic Briefing — {today}</b>\n\n"
            f"🔴 {red_count} Red Alerts | 🟡 {yellow_count} Yellow\n"
        )

        # Telegram senden (nur Header + Alerts, nicht ganzes Briefing)
        _send_telegram(header)

    print(f"[Briefing] DONE: {new_theme_count} Themen, "
          f"{red_count} Red, {yellow_count} Yellow", flush=True)


if __name__ == "__main__":
    main()