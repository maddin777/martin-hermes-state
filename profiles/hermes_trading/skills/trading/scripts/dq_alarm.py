#!/usr/bin/env python3
"""
dq_alarm.py — Signal-Degradierungs-Alarm für die Watchlist.

Zählt .L-Microcaps OHNE Tech-Score in der Conviction-Watchlist (≥76%
oder gekauft) — also die Einträge, die der UK-Liquidity-Gate blockt, aber
die als echte Signale in Filter-View/Statistik durchgerutscht wären.

Verhalten (Watchdog-Pattern):
- DQ-Count < SCHWELLE  → SILENT (kein Output, kein Alert)
- DQ-Count >= SCHWELLE → Telegram-Alert im Trading-Channel

Läuft als no_agent Hermes-Cron (Mo–Fr nach dem Export, 22:40).
Cron-ID: <zuweisen>

SCHWELLE: 10 (Insight 16.08.: DQ explodierte 1→8→14 in 3 Nächten —
           >10 ist eine klare Signal-Degradierung und muss alarmiert werden).
"""
import os
import sys

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401
from config import db_connect

# Schwellenwert: Anzahl DQ-Microcaps (>=0.76 Conviction oder bought) bevor Alarm.
SCHWELLE = 10
# State-File: speichert letzten Count, um NUR Regressionen zu melden
# (kein Daily-Spam bei stabilem hohen Niveau). Liegt im Trading-data/-Ordner.
TRADING_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(TRADING_ROOT, "data", "dq_alarm_state.txt")


def count_dq_microcaps(con):
    """Zählt .L-Einträge ohne tech_score, die als Signale zählen würden."""
    row = con.execute("""
        SELECT COUNT(*)
        FROM watchlist w
        WHERE w.status IN ('watching','bought')
          AND w.ticker LIKE '%.L'
          AND w.ticker IS NOT NULL
          AND w.tech_score IS NULL
          AND (w.conviction_score >= 0.76 OR w.status = 'bought')
    """).fetchone()
    return row[0] if row else 0


def send_telegram_alert(msg: str) -> None:
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


def _read_last() -> int:
    try:
        with open(STATE_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return -1


def _write_last(val: int) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            f.write(str(val))
    except Exception:
        pass


def main():
    con = db_connect()
    dq = count_dq_microcaps(con)
    con.close()
    last = _read_last()
    _write_last(dq)

    print(f"DQ-Microcap-Check: {dq} (Schwelle {SCHWELLE}, vorher {last})", flush=True)

    # Alarm nur bei REGRESSION:
    #  (a) Schwelle gerade überschritten (letzter < SCHWELLE, jetzt >= SCHWELLE)
    #  (b) echte Zunahme über Schwelle (dq > last >= SCHWELLE)
    regression = (dq >= SCHWELLE) and (last < SCHWELLE or dq > last)
    if not regression:
        print("→ silent (keine Regression)", flush=True)
        return

    msg = (
        "🚨 <b>Signal-Degradierung: Watchlist wächst als Rauschen</b>\n"
        f"DQ-Microcaps (`.L` ohne Tech-Score, ≥76% Conviction): <b>{dq}</b> "
        f"(vorher {last}, Schwelle {SCHWELLE})\n\n"
        f"Quelle: `rss:share talk` spült AIM/Nano-Caps in die Conviction-"
        f"Watchlist. Sie verzerren Sektor-Verteilung, SHORT-Anteil und das "
        f"max-3-pro-Sektor-Constraint.\n"
        f"<i>Export (22:15) lagert sie bereits in den DQ-Block aus — hier "
        f"wird nur die Regression gemeldet.</i>"
    )
    send_telegram_alert(msg)
    print(f"🚨 DQ-Regressions-Alarm gesendet ({dq} >= {SCHWELLE})", flush=True)


if __name__ == "__main__":
    main()
