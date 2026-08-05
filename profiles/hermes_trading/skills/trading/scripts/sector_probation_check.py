"""
Sector Probation Check — Prüft ob Sektoren aus dem Cooldown sind
aber noch kein Probation-Trade gemacht wurde.

Feuert einen Telegram-Alert wenn ein Sektor bereit für Probation ist.
Läuft Mo-Fr 09:30 via Hermes Cron.
"""
import sys
import os
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import env_loader  # noqa: F401

from config import db_connect


def send_telegram_alert(msg: str) -> None:
    """Sendet Telegram-Benachrichtigung in den Trading-Channel."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def main():
    print("📊 Sector Probation Check", flush=True)
    con = db_connect()

    # 1. Sektoren mit abgelaufenem Cooldown + keiner Probation
    rows = con.execute("""
        SELECT sector, blocked_at, cooldown_days,
               probation_entry_ticker, probation_opened_at, probation_status
        FROM sector_blacklist
        WHERE probation_status IS NULL
           OR probation_status = 'failed'
        ORDER BY blocked_at DESC
    """).fetchall()

    now = datetime.now()
    ready_sectors = []

    for r in rows:
        try:
            blocked = datetime.strptime(str(r["blocked_at"])[:10], "%Y-%m-%d")
        except Exception:
            continue
        cooldown = int(r["cooldown_days"] or 14)
        cooldown_end = blocked + timedelta(days=cooldown)

        if now >= cooldown_end:
            status = str(r["probation_status"] or "none")
            ready_sectors.append({
                "sector": r["sector"],
                "blocked_at": r["blocked_at"],
                "cooldown_end": cooldown_end.strftime("%Y-%m-%d"),
                "days_since_cooldown": (now - cooldown_end).days,
                "probation_status": status,
                "last_ticker": r["probation_entry_ticker"],
                "last_opened": r["probation_opened_at"],
            })

    if not ready_sectors:
        print("  ✅ Keine Sektoren im offenen Probation-Fenster", flush=True)
        con.close()
        return

    print(f"  ⚠ {len(ready_sectors)} Sektor(en) mit offenem Probation-Fenster:", flush=True)

    alerts = []
    for s in ready_sectors:
        candidates = con.execute("""
            SELECT w.ticker, w.name, w.conviction_score,
                   w.tech_direction, w.tech_score
            FROM watchlist w
            JOIN companies c ON c.ticker = w.ticker
            WHERE c.sector = ?
              AND w.status NOT IN ('removed', 'closed', 'bought')
              AND w.conviction_score >= 0.70
            ORDER BY w.conviction_score DESC
            LIMIT 5
        """, (s["sector"],)).fetchall()

        print(f"\n  {s['sector']}: "
              f"Cooldown seit {s['days_since_cooldown']} Tagen abgelaufen, "
              f"Probation: {s['probation_status']}", flush=True)

        bought = con.execute("""
            SELECT COUNT(*) as cnt
            FROM watchlist w
            JOIN companies c ON c.ticker = w.ticker
            WHERE c.sector = ? AND w.status = 'bought'
        """, (s["sector"],)).fetchone()
        has_open_positions = int(bought["cnt"]) > 0 if bought else False

        if candidates:
            print(f"    Kandidaten (≥70%):", flush=True)
            for c in candidates:
                ticker = str(c["ticker"] or "?")[:8]
                name = str(c["name"] or "")[:25]
                cs = c["conviction_score"] or 0
                pct = int(cs * 100)
                direction = str(c["tech_direction"] or "?")[:8]
                tech = f'{c["tech_score"] or 0:.1f}'
                print(f"    • {ticker:8} {name:25} {pct:>3}% {direction:6} {tech}", flush=True)

            best_ticker = str(candidates[0]["ticker"] or "")
            best_name = str(candidates[0]["name"] or "")
            cs = candidates[0]["conviction_score"] or 0
            best_pct = int(cs * 100)

            if s["probation_status"] == "none":
                alert = (
                    f"⚠️ <b>Probation-Fenster: {s['sector']}</b>\n"
                    f"Cooldown seit {s['days_since_cooldown']} Tagen abgelaufen "
                    f"({s['cooldown_end']}), noch kein Probation-Trade.\n"
                    f"Top-Kandidat: <b>{best_ticker}</b> ({best_name}, {best_pct}%)\n"
                )
                if has_open_positions:
                    alert += "⚠ Bereits offene Positionen in diesem Sektor — Probation evtl. obsolet.\n"
                alert += "50% Size, min 14d Haltedauer empfohlen."
                alerts.append(alert)

        elif not has_open_positions:
            alert = (
                f"⚠️ <b>Probation-Fenster: {s['sector']}</b>\n"
                f"Cooldown seit {s['days_since_cooldown']} Tagen abgelaufen, "
                f"aber keine Kandidaten ≥70% und keine offene Position.\n"
                f"👉 Sektor faktisch nicht handelbar."
            )
            alerts.append(alert)

    if alerts:
        msg = "📊 <b>Sector Probation Check</b>\n\n" + "\n\n".join(alerts)
        print(f"\n  → Sende {len(alerts)} Alert(s)...", flush=True)
        send_telegram_alert(msg)

    con.close()
    print("\n✅ Sector Probation Check abgeschlossen", flush=True)


if __name__ == "__main__":
    main()
