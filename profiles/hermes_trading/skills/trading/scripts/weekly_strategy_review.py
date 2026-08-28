#!/usr/bin/env python3
"""
weekly_strategy_review.py — Woechentlicher Strategie-Review nach dem 6-Monats-Review-Umbau.

Trackt die KE-Zahle die entscheiden ob die Umbauten (Momentum-Gate + Exit-Asymmetrie)
wirklichen Edge erzeugen, auf Live-Data:
  - SL_HIT-Quote (Ziel < 60 % der Exits)
  - Payoff-Ratio (Ziel > 1.5, Ideal >= 2)
  - Win-Rate, avg R-Multiple, EV/Trade
  - Momentum-Gate: wie viele Entries wurden durch momentum-gate geblockt
  - Exit-Verteilung: TIME_STOP vs SL_HIT vs Donchian/Chandelier
Vergleich: "vor Umbau" (vor 2026-08-27) vs "nach Umbau" (ab 2026-08-27).

Sendet Telegram-Report in den Trading-Channel. Wird sonntags 09:00 ausgefuehrt.

Usage:
    cd /root/.hermes/profiles/hermes_trading/skills/trading
    PYTHONPATH=. /root/.pyenv/versions/3.12.13/bin/python3 scripts/weekly_strategy_review.py
"""
from __future__ import annotations
import os, sqlite3, requests, html
from datetime import datetime, timedelta

TRADING_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(TRADING_ROOT)
DATA_DIR = os.path.join(TRADING_ROOT, "data")
DB = os.path.join(DATA_DIR, "trading.db")
CUTOFF = "2026-08-27"   # Tag des Umbaus (Momentum-Gate + Exit-Asymmetrie live)

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(msg: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        print(f"[send_telegram] keine Telegram-Creds (token={bool(TG_TOKEN)}, chat={bool(TG_CHAT)})")
        print(msg)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=15,
        )
        print(f"[send_telegram] HTTP {r.status_code}")
    except Exception as e:
        print(f"[send_telegram] Fehler: {e}")


def compute_stats(con, start_date: str, label: str) -> dict:
    """Berechne Kennzahlen fuer einen Trade-Zeitraum (entry_date >= start_date)."""
    rows = con.execute("""
        SELECT pnl_eur, pnl_pct, exit_reason, direction
        FROM positions
        WHERE exit_date IS NOT NULL AND pnl_eur IS NOT NULL AND entry_date >= ?
    """, (start_date,)).fetchall()
    n = len(rows)
    if n == 0:
        return {"label": label, "n": 0}
    pnls = [r["pnl_eur"] for r in rows]
    total = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else -1
    payoff = avg_win / abs(avg_loss) if avg_loss else float('inf')
    ev = total / n
    reasons = {}
    for r in rows:
        reasons[r["exit_reason"]] = reasons.get(r["exit_reason"], 0) + 1
    sl_cnt = sum(v for k, v in reasons.items() if "SL" in str(k).upper())
    sl_quote = sl_cnt / n if n else 0
    return {
        "label": label, "n": n, "total_pnl": total, "wr": wr,
        "avg_win": avg_win, "avg_loss": avg_loss, "payoff": payoff,
        "ev": ev, "reasons": reasons, "sl_quote": sl_quote,
    }


def compute_source_stats(con) -> list:
    """Abgeschlossene Trades nach ursprünglicher Screener-/Social-Quelle."""
    return [dict(row) for row in con.execute("""
        SELECT COALESCE(NULLIF(signal_source, ''), 'unknown') AS source,
               COUNT(*) AS trades,
               ROUND(SUM(pnl_eur), 2) AS pnl_eur,
               ROUND(AVG(CASE WHEN pnl_eur > 0 THEN 1.0 ELSE 0.0 END), 3) AS win_rate
        FROM positions
        WHERE exit_date IS NOT NULL AND pnl_eur IS NOT NULL
        GROUP BY COALESCE(NULLIF(signal_source, ''), 'unknown')
        ORDER BY trades DESC, source
    """).fetchall()]


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    pre = compute_stats(con, "2026-01-01", "VOR Umbau (vor 27.08.)")
    post = compute_stats(con, CUTOFF, "NACH Umbau (ab 27.08.)")
    source_stats = compute_source_stats(con)

    # momentum-gate Blockaden (blocked_entries) seit Umbau
    try:
        mg = con.execute(
            "SELECT COUNT(*) FROM blocked_entries WHERE gate='momentum-gate' "
            "AND blocked_at >= ?", (CUTOFF,)
        ).fetchone()[0]
    except Exception:
        mg = None
    # exit-verlauf offene positionen aktuell
    openn = con.execute("SELECT COUNT(*) FROM positions WHERE exit_date IS NULL").fetchone()[0]

    con.close()

    def fmt(s):
        if not s or s.get("n", 0) == 0:
            return f"  {html.escape(s['label'] if s else '')}: noch keine Trades"
        return (f"  {html.escape(s['label'])}:\n"
                f"    Trades: {s['n']} | PnL: {s['total_pnl']:+.0f}€ | WR: {s['wr']:.0%}\n"
                f"    Payoff: {s['payoff']:.2f} | EV: {s['ev']:+.1f}€/Trade\n"
                f"    SL_HIT-Quote: {s['sl_quote']:.0%} | Exits: {html.escape(str(s['reasons']))}")

    lines = ["📊 <b>Wöchentlicher Strategie-Review (Trading)</b>",
             f"Umbau-Cutoff: {CUTOFF} (Momentum-Gate + Exit-Asymmetrie)", ""]
    # Vergleich
    if pre.get("n") and post.get("n"):
        d_pay = post["payoff"] - pre["payoff"]
        d_sl = post["sl_quote"] - pre["sl_quote"]
        lines.append(f"<b>Delta vs vorher:</b> Payoff {pre['payoff']:.2f}→{post['payoff']:.2f} "
                     f"({d_pay:+.2f}) | SL_Quote {pre['sl_quote']:.0%}→{post['sl_quote']:.0%} "
                     f"({d_sl:+.0%})")
    else:
        lines.append("<b>Delta vs vorher:</b> (noch ungenügend Post-Umbau-Daten)")
    lines += ["", fmt(pre), "", fmt(post)]
    if mg is not None:
        lines.append(f"\n🚦 Momentum-Gate blockierte seit Umbau: <b>{mg}</b> Entries")
    lines.append(f"🔓 Offene Positionen aktuell: {openn}")
    if source_stats:
        lines += ["", "<b>Trades nach Quelle:</b>"]
        lines += [f"  {html.escape(row['source'])}: {row['trades']} Trades | "
                  f"PnL {row['pnl_eur']:+.0f}€ | WR {row['win_rate']:.0%}"
                  for row in source_stats]
    lines += ["", "Zielmarken: SL_Quote unter 60% | Payoff über 1.5 | EV über 0"]

    msg = "\n".join(lines)
    print(msg)
    print("=" * 40)
    send_telegram(msg)


if __name__ == "__main__":
    main()
