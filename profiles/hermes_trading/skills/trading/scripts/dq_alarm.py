#!/usr/bin/env python3
"""
dq_alarm.py — Signal-Degradierungs-Alarm für die Watchlist.

Zählt (a) .L-Microcaps OHNE Tech-Score in der Conviction-Watchlist (≥76%
oder gekauft) — also die Einträge, die der UK-Liquidity-Gate blockt — und
(b) Einträge in watching/bought, deren EINZIGE Quelle deaktiviert ist
(enabled=0) — die Deaktivierungs-Verifikation (seit 24.08.2026).

Verhalten (Watchdog-Pattern):
- Count < SCHWELLE  → SILENT (kein Output, kein Alert)
- Count >= SCHWELLE → Telegram-Alert im Trading-Channel

Läuft als no_agent Hermes-Cron (Mo–Fr nach dem Export, 22:40).
Cron-ID: 37d505cbc47b

SCHWELLE: 10 (Insight 16.08.: DQ explodierte 1→8→14 in 3 Nächten —
           >10 ist eine klare Signal-Degradierung und muss alarmiert werden).

Deaktivierungs-Verifikation (Teil b, seit 24.08.2026):
- Wertet aus `source_registry` die Menge deaktivierter Quellen aus (enabled=0).
- Wertet aus `watchlist.channels` (JSON-Array) aus, ob ein Eintrag NUR aus
  deaktivierten Quellen besteht. Solche Einträge (z.B. .L-Microcaps, die zu
  100% aus rss:share talk stammen) sind komplett tot und beweisen, dass eine
  Deaktivierung nicht gegriffen hat → Meldung + Alarm.
- Ein Eintrag, der AUCH aus aktiven Quellen gespeist wird (z.B. AAPL mit
  mehreren aktiven YouTube-Kanälen), zählt NICHT — nur exklusiv-deaktiviert.
"""
import json
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


def _deactivated_channels(con):
    """Menge der deaktivierten Quellen (enabled=0) als lowercase-Set.

    channels-Strings sind entweder "rss:<lower display_name>" (für RSS-Quellen)
    oder reine Channel-Namen (YouTube etc.). Wir normalisieren beides:
    strip "rss:"-Präfix + lowercase + Vergleich gegen die enabled=0-Menge.
    """
    rows = con.execute(
        "SELECT display_name FROM source_registry WHERE enabled=0"
    ).fetchall()
    return {"rss:" + str(r[0]).strip().lower() for r in rows} | {
        str(r[0]).strip().lower() for r in rows
    }


def _parse_channels(channels_val):
    """Parsed watchlist.channels (JSON-Array string) zu einer Liste."""
    if not channels_val:
        return []
    try:
        return json.loads(channels_val)
    except Exception:
        return []


def count_deactivated_only(con):
    """Zählt .L-Microcaps in watching/bought, deren EINZIGE Quelle deaktiviert ist.

    Das ist die DQ-Restbestand-Verifikation: Wenn ein `.L`-Ticker (mit ODER
    ohne tech_score) zu 100% aus einer deaktivierten Quelle stammt (z.B.
    rss:share talk), ist er komplett tot. Wenn er nach der Deaktivierung
    stehen bleibt (statt gecleant zu werden), ist die Deaktivierung nicht
    gegriffen.

    Bewusst NUR auf `.L`-Ticker begrenzt — das ist die DQ-Flut-Quelle. Ein
    Large-Cap wie STLA (aus `patrick boyle`) oder AEM (aus `urban jäkle`)
    zählt NICHT, selbst wenn sein einziger Kanal inzwischen deaktiviert ist:
    solch ein Eintrag ist eine historische Bestands-Position, keine signifikante
    Signal-Degradierung, und würde sonst falsch-alarmen.
    """
    deactivated = _deactivated_channels(con)
    if not deactivated:
        return 0, []
    rows = con.execute(
        "SELECT ticker, name, channels, status FROM watchlist "
        "WHERE status IN ('watching','bought') AND ticker LIKE '%.L'"
    ).fetchall()
    count = 0
    subjects = []
    for r in rows:
        chans = [c.strip() for c in _parse_channels(r["channels"]) if c.strip()]
        if not chans:
            continue
        # Nur wenn der Eintrag ZU 100% aus deaktivierten Quellen besteht.
        if all(c in deactivated for c in chans):
            count += 1
            subjects.append(r["ticker"])
    return count, subjects[:12]


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
    deact_count, deact_subj = count_deactivated_only(con)
    con.close()
    last = _read_last()
    _write_last(dq)

    combined = dq + deact_count
    print(
        f"DQ-Microcap-Check: {dq} (Schwelle {SCHWELLE}, vorher {last})\n"
        f"Deaktivierungs-Check: {deact_count} exklusiv-deaktivierte Einträge",
        flush=True,
    )
    if deact_count:
        print(f"  ↳ aus deaktivierten Quellen: {', '.join(deact_subj)}", flush=True)

    # Alarm bei REGRESSION auf der kombinierten Kennzahl:
    regression = (combined >= SCHWELLE) and (last < SCHWELLE or combined > last)
    if not regression:
        print("→ silent (keine Regression)", flush=True)
        return

    msg = (
        "🚨 <b>Signal-Degradierung: Watchlist wächst als Rauschen</b>\n"
        f"DQ-Microcaps (`.L` ohne Tech-Score, ≥76% Conviction): <b>{dq}</b>\n"
        f"Exklusiv-deaktivierte Einträge (erledigte Quellen bleiben stehen): "
        f"<b>{deact_count}</b>\n\n"
    )
    if dq:
        msg += (
            "`.L`-Microcaps spülen AIM/Nano-Caps in die Conviction-Watchlist. "
            "Sie verzerren Sektor-Verteilung, SHORT-Anteil und das "
            "max-3-pro-Sektor-Constraint.\n"
        )
    if deact_count:
        msg += (
            f"⚠️ <b>Deaktivierung nicht gegriffen:</b> Diese Einträge stammen "
            f"ausschließlich aus deaktivierten Quellen und bleiben trotzdem in "
            f"watching/bought:\n{', '.join(deact_subj)}\n"
        )
    msg += (
        "<i>Export (22:15) lagert `.L`-Microcaps in den DQ-Block aus — hier "
        "wird nur die Regression gemeldet.</i>"
    )
    send_telegram_alert(msg)
    print(f"🚨 DQ-Regressions-Alarm gesendet (kombiniert {combined} >= {SCHWELLE})", flush=True)


if __name__ == "__main__":
    main()
