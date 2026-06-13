"""
Aktiver Exit-Check (2x täglich 09:30 + 15:30)
- Technische Verschlechterung erkennen → frühzeitiger Ausstieg
- Profit-Sicherung bei +2x ATR → TP aggressiv nachziehen
- Trailing Stop alle 0.5x ATR nachziehen
- Slippage + Commission bei PnL-Berechnung
- BUGFIX: Cash & Portfolio-Value bei jedem Exit aktualisieren
"""
import sqlite3
import json
import math
import os
import sys
import requests
import pandas_ta as ta
from datetime import datetime

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)

from utils import (
    get_logger, SLIPPAGE_PCT, COMMISSION_EUR,
    get_price_data_cached, prefetch_prices,
)
from config import DB_PATH, STRATEGY_CONFIG_PATH, db_connect

log = get_logger("active_exit_check")

TELEGRAM_TOKEN        = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_HOME_CHANNEL = os.environ.get("TELEGRAM_HOME_CHANNEL") \
                        or os.environ.get("TELEGRAM_CHAT_ID")


def load_config():
    try:
        with open(STRATEGY_CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_HOME_CHANNEL:
        print(msg)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_HOME_CHANNEL, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as exc:
        log.warning("Telegram-Fehler: %s", exc)


def get_tech_status(ticker):
    """Prüft ob technisches Setup noch intakt ist (nutzt utils-Cache)."""
    try:
        _, _, df = get_price_data_cached(ticker)
        if df is None or len(df) < 50:
            return None, None, None

        close = df["Close"].iloc[:, 0] if df["Close"].ndim > 1 else df["Close"]
        high  = df["High"].iloc[:, 0]  if df["High"].ndim  > 1 else df["High"]
        low   = df["Low"].iloc[:, 0]   if df["Low"].ndim   > 1 else df["Low"]

        ema20    = ta.ema(close, length=20)
        ema50    = ta.ema(close, length=50)
        macd     = ta.macd(close)
        atr_s    = ta.atr(high, low, close, length=14)
        hist_col = [c for c in macd.columns if "MACDh" in c][0]

        current_price = float(close.iloc[-1])
        atr_val       = float(atr_s.iloc[-1])

        ema_bullish = ema20.iloc[-1] > ema50.iloc[-1]
        macd_rising = macd[hist_col].iloc[-1] > macd[hist_col].iloc[-2]
        price_above = current_price > float(ema50.iloc[-1])

        bull_count = sum([ema_bullish, macd_rising, price_above])
        status = "intact" if bull_count >= 2 else "degraded" if bull_count == 1 else "broken"
        return current_price, atr_val, status

    except Exception as exc:
        log.warning("get_tech_status Fehler (%s): %s", ticker, exc)
        return None, None, None


def _close_position(con, pos, current_price, pnl_eur, pnl_pct_net, reason):
    """
    Schließt eine Position und aktualisiert Cash + Portfolio-Value konsistent.
    Wird von TECH_BROKEN und SL/TP-Hit genutzt.
    """
    con.execute("""
        UPDATE positions SET
            status='closed', exit_price=?, exit_date=?,
            exit_reason=?, pnl_eur=?, pnl_pct=?
        WHERE id=?
    """, (round(current_price, 2), datetime.now().isoformat(),
          reason, round(pnl_eur, 2), round(pnl_pct_net, 2), pos["id"]))

    # Cash-Rückbuchung: ursprüngliche Positionsgröße + PnL
    portfolio = con.execute(
        "SELECT cash FROM portfolio WHERE id=1"
    ).fetchone()
    if portfolio:
        new_cash = portfolio["cash"] + pos["position_size"] + pnl_eur
        still_invested = sum(
            r["position_size"] for r in con.execute(
                "SELECT position_size FROM positions WHERE status='open' AND id != ?",
                (pos["id"],)
            ).fetchall()
        )
        new_total = new_cash + still_invested
        con.execute(
            "UPDATE portfolio SET cash=?, total_value=?, updated_at=? WHERE id=1",
            (round(new_cash, 2), round(new_total, 2), datetime.now().isoformat())
        )


def main():
    print(f"🔍 Aktiver Exit-Check [{datetime.now().strftime('%H:%M')}]", flush=True)
    con = db_connect()
    cfg = load_config()

    positions = con.execute(
        "SELECT * FROM positions WHERE status='open'"
    ).fetchall()
    if positions:
        prefetch_prices([p["ticker"] for p in positions if p["ticker"]])

    print(f"  Offene Positionen: {len(positions)}", flush=True)
    actions = []

    for pos in positions:
        ticker    = pos["ticker"]
        entry     = pos["entry_price"]
        sl        = pos["stop_loss"]
        tp        = pos["take_profit"]
        atr_entry = pos["atr_at_entry"] or 0
        direction = pos["direction"]

        current_price, atr_now, tech_status = get_tech_status(ticker)

        if not current_price or math.isnan(current_price):
            continue

        atr = atr_now or atr_entry
        if not atr or atr == 0:
            continue

        if direction == "LONG":
            pnl_atr = (current_price - entry) / atr
        else:
            pnl_atr = (entry - current_price) / atr

        # PnL mit Slippage + Commission
        if direction == "LONG":
            effective_entry = entry * (1 + SLIPPAGE_PCT)
            effective_exit  = current_price * (1 - SLIPPAGE_PCT)
            pnl_pct_net     = (effective_exit - effective_entry) / effective_entry * 100
        else:
            effective_entry = entry * (1 - SLIPPAGE_PCT)
            effective_exit  = current_price * (1 + SLIPPAGE_PCT)
            pnl_pct_net     = (effective_entry - effective_exit) / effective_entry * 100

        pnl_eur = pnl_pct_net / 100 * pos["position_size"] - COMMISSION_EUR

        print(f"\n  [{pos['name']}] {ticker} | P&L: {pnl_pct_net:+.1f}% | "
              f"Tech: {tech_status} | ATR-P&L: {pnl_atr:+.1f}x", flush=True)

        # --- AKTION 0: Thesis BROKEN → SL enger ziehen (kein sofortiger Exit) ---
        thesis_status = pos["thesis_current_status"] or "no_thesis"
        if thesis_status.upper() == "BROKEN":
            thesis_log = con.execute("""
                SELECT rationale, confidence, check_date
                FROM thesis_status_log
                WHERE ticker=? AND (status='broken' OR status='BROKEN')
                ORDER BY id DESC LIMIT 1
            """, (ticker,)).fetchone()

            if direction == "LONG":
                tight_sl = current_price - (0.5 * atr)
                if tight_sl > sl:
                    con.execute(
                        "UPDATE positions SET stop_loss=?, trailing_sl=? WHERE id=?",
                        (round(tight_sl, 2), round(tight_sl, 2), pos["id"])
                    )
                    rationale = thesis_log["rationale"][:80] if thesis_log else "Thesis broken"
                    print(f"    📋 Thesis BROKEN → SL enger: {sl:.2f} → {tight_sl:.2f} "
                          f"(0.5×ATR | {rationale})", flush=True)
                    actions.append(
                        f"📋 <b>Thesis broken: {pos['name']}</b>\n"
                        f"Ticker: {ticker} | P&L: {pnl_pct_net:+.1f}%\n"
                        f"SL enger: {sl:.2f} → {tight_sl:.2f} (0.5×ATR)\n"
                        f"Grund: {rationale}"
                    )
            else:  # SHORT
                tight_sl = current_price + (0.5 * atr)
                if tight_sl < sl:
                    con.execute(
                        "UPDATE positions SET stop_loss=?, trailing_sl=? WHERE id=?",
                        (round(tight_sl, 2), round(tight_sl, 2), pos["id"])
                    )
                    rationale = thesis_log["rationale"][:80] if thesis_log else "Thesis broken"
                    print(f"    📋 Thesis BROKEN → SL enger: {sl:.2f} → {tight_sl:.2f} "
                          f"(0.5×ATR | {rationale})", flush=True)
                    actions.append(
                        f"📋 <b>Thesis broken: {pos['name']}</b>\n"
                        f"Ticker: {ticker} | P&L: {pnl_pct_net:+.1f}%\n"
                        f"SL enger: {sl:.2f} → {tight_sl:.2f} (0.5×ATR)\n"
                        f"Grund: {rationale}"
                    )

        # --- AKTION 1: Tech-Verschlechterung → Exit ---
        if tech_status == "broken" and pnl_pct_net < 5:
            print("    🚨 Tech BROKEN + kein großer Gewinn → frühzeitiger Exit", flush=True)
            _close_position(con, pos, current_price, pnl_eur, pnl_pct_net, "TECH_BROKEN")
            con.commit()
            emoji = "✅" if pnl_pct_net > 0 else "❌"
            actions.append(
                f"{emoji} <b>Exit (Tech degradiert): {pos['name']}</b>\n"
                f"Ticker: {ticker}\n"
                f"P&L: {pnl_pct_net:+.1f}% | EMA/MACD gedreht\n"
                f"Entry: {entry:.2f} → Exit: {current_price:.2f}"
            )
            continue

        # --- AKTION 2: Profit-Sicherung bei +2x ATR ---
        profit_lock_threshold = cfg.get("profit_lock_atr", 2.0)
        if pnl_atr >= profit_lock_threshold:
            if direction == "LONG":
                protected_tp = entry + (pnl_atr * 0.5 * atr)
                new_sl = max(sl, protected_tp)
            else:
                protected_tp = entry - (pnl_atr * 0.5 * atr)
                new_sl = min(sl, protected_tp)

            if (direction == "LONG" and new_sl > sl) or \
               (direction == "SHORT" and new_sl < sl):
                con.execute(
                    "UPDATE positions SET stop_loss=?, trailing_sl=? WHERE id=?",
                    (round(new_sl, 2), round(new_sl, 2), pos["id"])
                )
                print(f"    🔒 Profit gesichert: SL → {new_sl:.2f} "
                      f"(+{pnl_atr:.1f}x ATR im Plus)", flush=True)
                actions.append(
                    f"🔒 <b>Profit gesichert: {pos['name']}</b>\n"
                    f"Ticker: {ticker} | +{pnl_pct_net:.1f}% (+{pnl_atr:.1f}x ATR)\n"
                    f"Neuer SL: {new_sl:.2f} (50% Gewinn gesichert)"
                )

        # --- AKTION 3: Trailing Stop alle 0.5x ATR nachziehen ---
        trailing_step = cfg.get("trailing_step_atr", 0.5)
        if direction == "LONG":
            ideal_sl      = current_price - (cfg.get("atr_sl_multiplier", 1.5) * atr)
            next_sl_level = sl + (trailing_step * atr)
            if ideal_sl > next_sl_level and ideal_sl > sl:
                con.execute(
                    "UPDATE positions SET stop_loss=?, trailing_sl=?, "
                    "highest_price=? WHERE id=?",
                    (round(ideal_sl, 2), round(ideal_sl, 2),
                     round(current_price, 2), pos["id"])
                )
                print(f"    📈 Trailing SL → {ideal_sl:.2f} "
                      f"(Preis: {current_price:.2f})", flush=True)

        # --- SL/TP Hit Check ---
        if direction == "LONG":
            hit_sl = current_price <= sl
            hit_tp = current_price >= tp
        else:
            hit_sl = current_price >= sl
            hit_tp = current_price <= tp

        if hit_sl or hit_tp:
            reason = "TARGET_HIT" if hit_tp else "SL_HIT"
            _close_position(con, pos, current_price, pnl_eur, pnl_pct_net, reason)
            con.commit()
            emoji = "🎯" if hit_tp else "🛑"
            actions.append(
                f"{emoji} <b>{reason}: {pos['name']}</b>\n"
                f"Ticker: {ticker}\n"
                f"Entry: {entry:.2f} → Exit: {current_price:.2f}\n"
                f"P&L: {pnl_eur:+.2f}€ ({pnl_pct_net:+.1f}%)"
            )

    con.commit()

    if actions:
        send_telegram("\n\n".join(actions))
    else:
        print("  ✓ Keine Aktionen notwendig", flush=True)

    con.close()
    print("\n✅ Exit-Check abgeschlossen", flush=True)


if __name__ == "__main__":
    main()
