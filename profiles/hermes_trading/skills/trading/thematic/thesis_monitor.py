"""
Thesis Monitor — Taegliche Pruefung ob die Investment-These noch intakt ist.
LLM-basiert mit News + Polymarket-Signalen.
"""
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import sqlite3
import requests
from datetime import date, datetime
from thematic.lib import llm_client, tavily_client, prompt_loader, polymarket_client

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_HOME_CHANNEL = os.environ.get("TELEGRAM_HOME_CHANNEL")


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
        print(f"  ⚠ Telegram-Fehler: {e}")


def _load_position_themes(con, pos):
    """Laedt Theme-Info fuer eine offene Position."""
    tid = pos["thesis_theme_id"]
    if not tid:
        return {}, ""
    theme = con.execute("SELECT * FROM theme_definitions WHERE id = ?", (tid,)).fetchone()
    if not theme:
        return {}, ""
    return dict(theme), theme["description"] if theme["description"] else ""


def main(intraday: bool = False):
    con = _db_connect()
    today = date.today().isoformat()

    positions = con.execute("""
        SELECT * FROM positions WHERE status = 'open'
    """).fetchall()

    if not positions:
        print(f"[Thesis Monitor] Keine offenen Positionen.")
        con.close()
        return

    print(f"[Thesis Monitor] {len(positions)} Positionen...", flush=True)
    model = llm_client.get_model("thesis_monitor")

    broken_count = 0
    weakening_count = 0

    for pos in positions:
        ticker = pos["ticker"]
        thesis_raw = pos["thesis_text"] or ""
        theme_dict, theme_desc = _load_position_themes(con, pos)
        theme_name = theme_dict.get("name", "–")

        # Kein Thesis-Check wenn weder thesis_theme_id noch thesis_text vorhanden
        # → verhindert false "BROKEN" Meldungen für rein sentiment-basierte Trades
        has_theme  = bool(pos["thesis_theme_id"])
        has_thesis = bool(thesis_raw.strip()) and thesis_raw.strip() != "Keine These dokumentiert."
        if not has_theme and not has_thesis:
            # Status auf no_thesis setzen (einmalig, ohne Telegram-Alert)
            con.execute(
                "UPDATE positions SET thesis_current_status='no_thesis' WHERE id=?",
                (pos["id"],)
            )
            print(f"  {ticker}: kein Thesis-Eintrag → übersprungen (no_thesis)", flush=True)
            continue

        thesis = thesis_raw if has_thesis else "Keine explizite These – Bewertung auf Basis des Themas."

        # News holen
        news = tavily_client.fetch_ticker_news(ticker, days=1)
        news_text = "\n".join(
            f"- [{a.get('title', '')}]({a.get('url', '')}): {a.get('content', '')[:200]}"
            for a in news[:8]
        ) or "Keine aktuellen News."

        # Polymarket-Signale
        pm_data = polymarket_client.fetch_top_movers(min_delta_7d=0.0, limit=5)
        pm_text = "\n".join(
            f"- \"{m['question']}\": Price {m['current_yes_price']:.2f}, "
            f"7d Delta: {m['delta_7d']:+.2f}"
            for m in pm_data
        ) if pm_data else "Keine verknuepften PM-Maerkte."

        # LLM-Call
        prompt = prompt_loader.load_prompt(
            "thesis_check_v1.md",
            ticker=ticker,
            company_name=pos["name"] if pos["name"] else ticker,
            thesis_text=thesis,
            theme_name=theme_name,
            theme_description=theme_desc,
            entry_date=(pos["entry_date"] or "")[:10],
            news_snippets_with_urls=news_text,
            prediction_markets_with_prices_and_deltas=pm_text,
        )

        result = llm_client.call_llm(prompt, model, temperature=0.3, json_mode=True)
        data = llm_client.parse_json_response(result)

        verdict    = data.get("verdict", "UNCERTAIN")
        confidence = float(data.get("confidence", 0.5))
        rationale  = data.get("rationale", "")

        # Schutzfilter: LLM-Antworten die nur sagen "es gibt keine These" ablehnen
        # Diese entstehen wenn der Prompt-Kontext unzureichend war
        no_thesis_phrases = [
            "no documented thesis",
            "keine dokumentierte these",
            "impossible for the thesis to be intact",
            "there was no documented",
            "no thesis was provided",
        ]
        is_no_thesis_verdict = any(p.lower() in rationale.lower() for p in no_thesis_phrases)
        if is_no_thesis_verdict:
            print(f"  {ticker}: LLM-Rationale enthält 'no thesis'-Phrase → verdict auf UNCERTAIN gesetzt", flush=True)
            verdict    = "UNCERTAIN"
            confidence = 0.3
            rationale  = f"[Gefiltert: keine Thesis vorhanden] {rationale}"

        # Log
        con.execute("""
            INSERT INTO thesis_status_log
            (position_id, ticker, theme_id, check_date, status, confidence,
             rationale, news_summary, triggering_urls, llm_model_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pos["id"], ticker,
            pos["thesis_theme_id"],
            today, verdict, confidence,
            rationale,
            news_text[:1000],
            json.dumps(data.get("triggering_urls", [])),
            model,
        ))

        # Position-Status updaten
        con.execute(
            "UPDATE positions SET thesis_current_status = ? WHERE id = ?",
            (verdict, pos["id"])
        )

        print(f"  {ticker}: {verdict} (Conf={confidence:.2f})", flush=True)

        if verdict == "BROKEN" and confidence >= 0.7:
            broken_count += 1
            _send_telegram(
                f"🔴 <b>THESIS BROKEN: {pos['name']} ({ticker})</b>\n"
                f"Thema: {theme_name}\n"
                f"Confidence: {confidence:.0%}\n"
                f"Rationale: {rationale}\n\n"
                f"<i>SL wurde automatisch auf 0.5×ATR enger gezogen.</i>"
            )
        elif verdict == "WEAKENING":
            weakening_count += 1

    # 3-Tage-Weakening-Check
    _check_weakening_streak(con, today)

    con.commit()
    con.close()
    print(f"[Thesis Monitor] DONE: {broken_count} BROKEN, {weakening_count} WEAKENING", flush=True)


def _check_weakening_streak(con, today):
    """Prueft ob eine Position 3 Tage in Folge WEAKENING ist."""
    weakening_pos = con.execute("""
        SELECT p.id, p.name, p.ticker
        FROM positions p
        WHERE p.status = 'open' AND p.thesis_current_status = 'WEAKENING'
    """).fetchall()

    for pos in weakening_pos:
        streak = con.execute("""
            SELECT status FROM thesis_status_log
            WHERE position_id = ?
            ORDER BY check_date DESC LIMIT 3
        """, (pos["id"],)).fetchall()
        if len(streak) >= 3 and all(r["status"] == "WEAKENING" for r in streak):
            _send_telegram(
                f"🟡 <b>THESIS WEAKENING (3 Tage): {pos['name']} ({pos['ticker']})</b>\n"
                f"Empfehlung: 50%-Reduktion"
            )


if __name__ == "__main__":
    import sys
    intraday = "--intraday" in sys.argv
    main(intraday=intraday)