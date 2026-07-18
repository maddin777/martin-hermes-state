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
from utils import get_price_data_cached

# Devil's Advocate (Rollen-Sprint R2): Stufe 2 greift nur bei Verlustpositionen
DEVIL_PNL_TRIGGER = -0.03      # -3% unrealisiert
DEVIL_KILL_ALERT  = 0.85       # ab hier zusätzliche Telegram-Info (reine Info)

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_HOME_CHANNEL = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_CHAT_ID", "")


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


def _migrate_devil_columns(con):
    """Idempotente Migration: devil_kill_prob / devil_reasons in thesis_status_log."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(thesis_status_log)").fetchall()}
    if "devil_kill_prob" not in cols:
        con.execute("ALTER TABLE thesis_status_log ADD COLUMN devil_kill_prob REAL")
        print("  📝 thesis_status_log: devil_kill_prob-Spalte hinzugefügt", flush=True)
    if "devil_reasons" not in cols:
        con.execute("ALTER TABLE thesis_status_log ADD COLUMN devil_reasons TEXT")
        print("  📝 thesis_status_log: devil_reasons-Spalte hinzugefügt", flush=True)
    con.commit()


def _unrealized_pnl_pct(pos):
    """
    Richtungssicherer unrealisierter PnL als Dezimalwert.

    LONG:  (price − entry) / entry
    SHORT: (entry − price) / entry

    Preis und entry_price sind beide in der Heimwährung des Tickers – keine
    FX-Umrechnung nötig, das Verhältnis ist währungsneutral.

    Returns: float oder None (Preis nicht ermittelbar → Stufe 2 überspringen).
    """
    try:
        entry = pos["entry_price"]
        if not entry or float(entry) <= 0:
            return None
        price, _atr, _df = get_price_data_cached(pos["ticker"])
        if not price:
            return None
        entry = float(entry)
        price = float(price)
        if (pos["direction"] or "LONG").upper() == "SHORT":
            return (entry - price) / entry
        return (price - entry) / entry
    except Exception:
        return None


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
    con.execute("PRAGMA busy_timeout=30000;")
    today = date.today().isoformat()
    _migrate_devil_columns(con)

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

        # ── Stufe 2: Devil's Advocate (Rollen-Sprint R2) ───────────────────
        # Trigger: Stufe-1-Verdict INTACT/UNCERTAIN UND Position ≥3% im Minus.
        # Andere Fälle kosten 0 Zusatz-Tokens. Anderer Provider als Stufe 1
        # (DeepSeek statt Gemini) – sonst bestätigt sich derselbe Bias selbst.
        devil = {"ok": False}
        if verdict in ("INTACT", "UNCERTAIN"):
            pnl_pct = _unrealized_pnl_pct(pos)
            if pnl_pct is not None and pnl_pct <= DEVIL_PNL_TRIGGER:
                try:
                    from roles import budget as _role_budget
                    from roles.devils_advocate import (
                        run_devils_advocate, merge_verdict,
                    )
                    if _role_budget.check_and_reserve(con, "devils_advocate", today):
                        devil = run_devils_advocate(
                            con, ticker,
                            pos["name"] if pos["name"] else ticker,
                            thesis, theme_name,
                            news_text,                     # wiederverwendet – kein 2. Tavily-Call
                            pos["entry_date"] or "",
                            pnl_pct,
                            (pos["direction"] or "LONG").upper(),
                        )
                        if devil.get("ok"):
                            old_verdict = verdict
                            verdict, rationale = merge_verdict(verdict, rationale, devil)
                            kp = devil["kill_probability"]
                            print(f"  😈 {ticker}: Devil's Advocate p={kp:.2f} "
                                  f"(PnL {pnl_pct:+.1%}) → {old_verdict} → {verdict}",
                                  flush=True)
                            if kp >= DEVIL_KILL_ALERT:
                                reasons_md = "\n".join(
                                    f"• {r}" for r in devil["kill_reasons"]
                                )
                                _send_telegram(
                                    f"😈 <b>DEVIL'S ADVOCATE: {pos['name']} ({ticker})</b>\n"
                                    f"Kill-Wahrscheinlichkeit: {kp:.0%} | "
                                    f"PnL: {pnl_pct:+.1%}\n\n{reasons_md}\n\n"
                                    f"<i>Reine Information – keine automatische Aktion.</i>"
                                )
                except Exception as e:
                    # Fail-Open: Stufe-1-Verdict gilt unverändert.
                    print(f"  ⚠ {ticker}: Devil's-Advocate-Stufe übersprungen ({e})",
                          flush=True)
                    devil = {"ok": False}

        try:
            from roles.devils_advocate import to_db_fields as _to_db_fields
            devil_prob, devil_reasons = _to_db_fields(devil)
        except Exception:
            devil_prob, devil_reasons = None, None

        # Log
        con.execute("""
            INSERT INTO thesis_status_log
            (position_id, ticker, theme_id, check_date, status, confidence,
             rationale, news_summary, triggering_urls, llm_model_used,
             devil_kill_prob, devil_reasons)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pos["id"], ticker,
            pos["thesis_theme_id"],
            today, verdict, confidence,
            rationale,
            news_text[:1000],
            json.dumps(data.get("triggering_urls", [])),
            model,
            devil_prob, devil_reasons,
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