"""
daily_report.py — Tagesend-Auswertung für den Forex-Paper-Bot.

Nutzung:
  python3 daily_report.py          # Erstellt Report für heute + Telegram-Delivery
  python3 daily_report.py --test   # Nur Report bauen, kein Telegram

Läuft nach Session-Ende (Cron ~22:15 MEZ, Mo-Fr).
Report: Trades des Tages, Gesamt-PnL netto (inkl. Spreads), Win-Rate, Profit-Faktor,
        Drawdown-Stand. Speichert als Markdown + optional Telegram.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg


def today_key():
    return datetime.now().strftime("%Y-%m-%d")


def build_report(con, day=None):
    """Erstellt die Tagesstatistik als Markdown + Metriken."""
    day = day or today_key()
    rows = con.execute(
        "SELECT * FROM trades WHERE date(exit_time) = ? OR (status='open' AND date(entry_time)=?)",
        (day, day)
    ).fetchall()
    closed = [r for r in rows if r["status"] == "closed"]

    gross = sum(r["pnl_gross"] or 0 for r in closed)
    net = sum(r["pnl_net"] or 0 for r in closed)
    wins = [r for r in closed if (r["pnl_net"] or 0) > 0]
    losses = [r for r in closed if (r["pnl_net"] or 0) <= 0]
    wr = len(wins) / len(closed) if closed else 0.0
    gross_win = sum(r["pnl_net"] for r in wins)
    gross_loss = abs(sum(r["pnl_net"] for r in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0)

    open_now = con.execute("SELECT COUNT(*) FROM trades WHERE status='open'").fetchone()[0]
    dd = cfg.drawdown_pct(con)
    p = cfg.get_portfolio(con)

    lines = []
    lines.append(f"# 📊 Forex Paper-Bot — Tagesreport {day}")
    lines.append("")
    lines.append(f"**Zeit:** {datetime.now().strftime('%H:%M')} | **Offene Trades:** {open_now}")
    lines.append(f"**Equity:** {p['cash']:.2f}€ | **Realisierter PnL:** {p['realized_pnl']:.2f}€ | **Drawdown:** {dd:.1%}")
    lines.append("")
    lines.append("## Heute")
    lines.append(f"- **Geschlossene Trades:** {len(closed)}")
    lines.append(f"- **PnL gross:** {gross:.2f}€ | **PnL netto (inkl. Spreads):** {net:.2f}€")
    lines.append(f"- **Win-Rate:** {wr:.1%}")
    lines.append(f"- **Profit-Faktor:** {pf:.2f}")
    lines.append("")
    if closed:
        lines.append("| Paar | Richtung | Entry | Exit | PnL netto | Reason |")
        lines.append("|------|----------|-------|------|-----------|--------|")
        for r in closed:
            lines.append(f"| {r['pair']} | {r['direction']} | {r['entry_price']:.5f} | "
                         f"{r['exit_price']:.5f} | {r['pnl_net']:.2f}€ | {r['exit_reason']} |")
    else:
        lines.append("_Keine Trades heute._")

    report_md = "\n".join(lines)
    return {
        "day": day, "trades": len(closed), "gross": gross, "net": net,
        "wr": wr, "pf": pf, "dd": dd, "md": report_md, "open_now": open_now
    }


def save_report(con, report, day=None):
    day = day or today_key()
    con.execute(
        "INSERT OR REPLACE INTO daily_reports "
        "(report_date, trades_count, gross_pnl, net_pnl, win_rate, profit_factor, drawdown_pct, report_md) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (day, report["trades"], report["gross"], report["net"], report["wr"], report["pf"],
         report["dd"], report["md"])
    )
    con.commit()
    # Markdown in reports/ speichern
    reports_dir = os.path.join(cfg.SKILL_DIR, cfg.CONFIG["reports_dir"])
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, f"report_{day}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report["md"])
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--day")
    args = ap.parse_args()

    con = cfg.db_connect()
    cfg.init_db(con)
    report = build_report(con, args.day)
    path = save_report(con, report, args.day)
    # Report als stdout ausgeben — der no_agent Hermes-Cron (deliver=telegram)
    # liefert den stdout automatisch an den Ziel-Chat. Kein eigenes send_telegram
    # nötig (vermeidet doppelte Delivery).
    print(report["md"])
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
