#!/usr/bin/env python3
"""Einmalige, BEDINGTE Umstellung von time_stop_trading_days 7 -> 5.

Warum bedingt und nicht einfach gesetzt (18.09.2026):
Am 18.09. standen 5 der 8 offenen Positionen bereits 5-6 Handelstage im Markt.
time_stop_trading_days=5 sofort zu setzen haette sie am naechsten Pipeline-Lauf
alle auf einmal geschlossen — darunter OKTA mit +48,81 EUR. Der Backtest, auf
dem die Empfehlung beruht, hat TS=5 aber AB ENTRY simuliert und nie rueckwirkend
auf laufende Positionen angewandt. Das waere ein anderes Experiment gewesen.

Dieses Skript wartet deshalb, bis der Bestand von selbst durchgelaufen ist:
angewandt wird erst, wenn KEINE offene Position durch die Umstellung sofort
geschlossen wuerde. Bis dahin protokolliert es und tut nichts.

Idempotent und selbst-deaktivierend: sobald die Umstellung sitzt, entfernt das
Skript seine eigene Cron-Zeile und laeuft nie wieder an.

Aufruf:
    python3 scripts/apply_time_stop_5.py           # bedingt anwenden
    python3 scripts/apply_time_stop_5.py --status  # nur Lagebild, nie schreiben
"""
import json
import subprocess
import sys
from datetime import datetime

from config import STRATEGY_CONFIG_PATH, db_connect
from exit_rules import trading_days_held

TARGET = 5
CRON_MARKER = "apply_time_stop_5.py"


def _log(msg):
    print(f"[apply_time_stop_5 {datetime.now():%Y-%m-%d %H:%M}] {msg}", flush=True)


def blocking_positions(target=TARGET):
    """Offene Positionen, die der neue Time-Stop sofort schliessen wuerde."""
    con = db_connect()
    try:
        rows = con.execute(
            "SELECT ticker, direction, entry_date, pnl_eur "
            "FROM positions WHERE status='open' ORDER BY entry_date"
        ).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        held = trading_days_held(r["entry_date"].replace(" ", "T"))
        if held >= target:
            out.append((r["ticker"], r["direction"], held, r["pnl_eur"] or 0.0))
    return out


def disable_own_cron():
    """Entfernt die eigene Cron-Zeile, damit der Einmal-Job nicht ewig laeuft."""
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if cur.returncode != 0:
            _log("Crontab nicht lesbar — Zeile bitte manuell entfernen.")
            return
        kept = [l for l in cur.stdout.splitlines() if CRON_MARKER not in l]
        if len(kept) == len(cur.stdout.splitlines()):
            return  # war nicht drin
        p = subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n",
                           text=True, capture_output=True)
        if p.returncode == 0:
            _log("Eigene Cron-Zeile entfernt — Einmal-Job abgeschlossen.")
        else:
            _log(f"Cron-Zeile NICHT entfernt ({p.stderr.strip()}) — bitte manuell.")
    except Exception as exc:
        _log(f"Cron-Aufraeumen fehlgeschlagen ({exc}) — bitte manuell entfernen.")


def main(status_only=False):
    cfg = json.load(open(STRATEGY_CONFIG_PATH))
    current = cfg.get("time_stop_trading_days")

    if current == TARGET:
        _log(f"time_stop_trading_days steht bereits auf {TARGET} — nichts zu tun.")
        if not status_only:
            disable_own_cron()
        return 0

    blockers = blocking_positions()
    if blockers:
        _log(f"Noch nicht anwendbar: {len(blockers)} offene Position(en) wuerden "
             f"durch TS={TARGET} sofort geschlossen.")
        for tk, d, held, pnl in blockers:
            _log(f"    {tk:9s} {d:5s} {held} Handelstage  P&L {pnl:+.2f}")
        _log(f"time_stop_trading_days bleibt bei {current}. Naechster Versuch morgen.")
        return 0

    if status_only:
        _log(f"Anwendbar: keine offene Position wuerde durch TS={TARGET} sofort "
             f"geschlossen. (--status: es wird nichts geschrieben)")
        return 0

    backup = f"{STRATEGY_CONFIG_PATH}.bak-{datetime.now():%Y%m%d-%H%M%S}-pre-ts{TARGET}"
    with open(backup, "w") as fh:
        json.dump(cfg, fh, indent=2)
    cfg["time_stop_trading_days"] = TARGET
    with open(STRATEGY_CONFIG_PATH, "w") as fh:
        json.dump(cfg, fh, indent=2)

    check = json.load(open(STRATEGY_CONFIG_PATH))
    if check.get("time_stop_trading_days") != TARGET:
        _log("FEHLER: Schreiben nicht wirksam — Backup liegt unter " + backup)
        return 1

    _log(f"time_stop_trading_days {current} -> {TARGET} gesetzt. Backup: {backup}")
    _log("Damit laeuft der Agent auf der Konfiguration, die verify_exit_profile.py "
         "geprueft hat (exit_profile=wider_stop + TS=5).")
    disable_own_cron()
    return 0


if __name__ == "__main__":
    sys.exit(main(status_only="--status" in sys.argv))
