"""
Drawdown Monitor — Portfolio-Level Risk Tracking.
3-Stufen: Soft (-10%), Hard (-15%), Auto-Pause (-20%).
"""
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import sqlite3
import requests
from datetime import date, datetime, timedelta

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(msg)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"[Drawdown] Telegram-Fehler: {e}")


def _get_system_state(con, key: str) -> str:
    row = con.execute(
        "SELECT value FROM system_state WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else ""


def _set_system_state(con, key: str, value: str):
    con.execute("""
        INSERT OR REPLACE INTO system_state (key, value, updated_at)
        VALUES (?, ?, ?)
    """, (key, value, datetime.now().isoformat()))


def main():
    con = _db_connect()
    cfg_path = os.path.join(
        os.path.dirname(__file__), "config", "thematic_config.json"
    )
    with open(cfg_path) as f:
        cfg = json.load(f)
    thresholds = cfg.get("thresholds", {})

    today = date.today().isoformat()

    # Portfolio-Value berechnen
    portfolio = con.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
    if not portfolio:
        print("[Drawdown] Kein Portfolio-Eintrag.")
        con.close()
        return

    cash = portfolio["cash"] or 0
    open_pos_val = sum(
        p["position_size"] or 0 for p in con.execute(
            "SELECT position_size FROM positions WHERE status = 'open'"
        ).fetchall()
    )
    open_pnl = sum(
        p["pnl_eur"] or 0 for p in con.execute(
            "SELECT pnl_eur FROM positions WHERE status = 'open'"
        ).fetchall()
    )
    portfolio_value = cash + open_pos_val + open_pnl

    # All-Time-High
    ath_row = con.execute(
        "SELECT MAX(portfolio_value) as ath FROM drawdown_log"
    ).fetchone()
    ath = ath_row["ath"] if ath_row and ath_row["ath"] else portfolio_value
    ath = max(ath, portfolio_value)

    # Drawdown
    dd_pct = (portfolio_value - ath) / ath if ath > 0 else 0

    # Trigger-Level
    soft = thresholds.get("drawdown_soft_warning_pct", 0.10)
    hard = thresholds.get("drawdown_hard_restriction_pct", 0.15)
    pause = thresholds.get("drawdown_auto_pause_pct", 0.20)

    trigger = "none"
    action = ""

    if dd_pct <= -pause:
        trigger = "pause"
        paused = _get_system_state(con, "system_paused")
        if paused != "true":
            _set_system_state(con, "system_paused", "true")
            _set_system_state(con, "pause_reason", "drawdown_20pct")
            _set_system_state(con, "pause_timestamp", datetime.now().isoformat())
            cooling_hours = thresholds.get("reactivation_cooling_off_hours", 72)
            eligible = datetime.now() + timedelta(hours=cooling_hours)
            _set_system_state(
                con, "reactivation_eligible_at", eligible.isoformat()
            )
            action = "AUTO-PAUSE aktiviert. Briefings pausiert. 72h Cooling-Off."
            _send_telegram(
                f"🛑 <b>AUTO-PAUSE: Portfolio Drawdown -20%</b>\n"
                f"Portfolio: {portfolio_value:.2f}€ | ATH: {ath:.2f}€\n"
                f"Drawdown: {dd_pct:.1%}\n\n"
                f"Reaktivierung fruehestens: {eligible.strftime('%d.%m.%Y %H:%M')}"
            )
    elif dd_pct <= -hard:
        trigger = "hard"
        action = "Hard Restriction: Alle neuen Kaeufe blockiert, Trailing Stops verschaerft."
        _send_telegram(
            f"⚠ <b>HARD RESTRICTION: Portfolio Drawdown -15%</b>\n"
            f"Portfolio: {portfolio_value:.2f}€ | ATH: {ath:.2f}€\n"
            f"Drawdown: {dd_pct:.1%}\n\n"
            f"Alle neuen Kaeufe blockiert."
        )
    elif dd_pct <= -soft:
        trigger = "soft"
        action = "Soft Warning: Tier-C-Kaeufe blockiert."
        _send_telegram(
            f"🟡 <b>SOFT WARNING: Portfolio Drawdown -10%</b>\n"
            f"Portfolio: {portfolio_value:.2f}€ | ATH: {ath:.2f}€\n"
            f"Drawdown: {dd_pct:.1%}"
        )

    # Log
    con.execute("""
        INSERT INTO drawdown_log
        (date, portfolio_value, all_time_high, drawdown_pct, trigger_level, action_taken)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        today,
        round(portfolio_value, 2),
        round(ath, 2),
        round(dd_pct * 100, 2),
        trigger,
        action,
    ))

    con.commit()
    con.close()

    print(
        f"[Drawdown] Portfolio={portfolio_value:.2f}€, "
        f"ATH={ath:.2f}€, DD={dd_pct:.1%}, Trigger={trigger}",
        flush=True,
    )


if __name__ == "__main__":
    main()