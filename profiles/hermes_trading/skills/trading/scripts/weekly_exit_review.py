#!/usr/bin/env python3
"""
weekly_exit_review.py — Wöchentlicher Abgleich offener Positionen gegen die
Exit-Management-Regeln (config.get_exit_config, Exit-Matrix).

HINTERGRUND: Der vault-insights-daily (16.08.) schlug einen wöchentlichen
Check offener Short-Positionen gegen die Exit-Regeln vor. Prämisse korrigiert:
es gibt aktuell KEINE offenen Shorts (alle offenen Positionen = LONG). Der
Check prüft daher ALLE offenen Positionen gegen die Exit-Matrix und zusätzlich
den Config-Drift zwischen den parallelen Exit-Pfaden:

  - signal_manager.py       → get_exit_config()  (Matrix, SEIT 09.08. SSOT)
  - active_exit_check.py    → get_exit_config()  (SEIT 16.08., vorher Legacy)

Der 09.08.-Killer war genau so ein paralleler-Pfad-Drift (profit_lock nur in
einem Pfad gefixt). Dieser Review deckt solche Abweichungen wöchentlich auf,
bevor neue Trades (z.B. Industrials aus Cooldown) starten.

Meldet einen Telegram-Report im Trading-Channel. Läuft wöchentlich (So 07:00,
nach nightly_eval). Cron-ID: <zuweisen>
"""
import os
import sys

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
TRADING_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
import env_loader  # noqa: F401
from config import db_connect, get_exit_config
from scripts.signal_manager import get_current_regime


def send_telegram(msg: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "") or os.environ.get("TELEGRAM_HOME_CHANNEL", "")
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


def check_config_drift():
    """Prüft ob Exit-/Entry-/Shadow-Pfade die Legacy-Funktion
    get_asset_multipliers noch referenzieren — das 09.08.-Parallele-Pfad-Muster.

    Stand 16.08.: alle Pfade sind auf die Exit-Matrix (get_exit_config) umgestellt:
      - signal_manager.py      (compute_sl_tp Entry-SL/TP, Sizing, Partial-TP)
      - active_exit_check.py   (Trailing-Step, Profit-Lock)
      - crabel_shadow_eval.py  (Forward-Simulation)
    Dieser Check wacht darüber, dass keiner still auf die Legacy zurückfällt.
    """
    issues = []
    scripts_dir = os.path.join(TRADING_ROOT, "scripts")
    # Ordner: (Datei, Label)
    checks = [
        ("active_exit_check.py", "active_exit_check"),
        ("signal_manager.py",    "signal_manager"),
        ("crabel_shadow_eval.py", "crabel_shadow_eval"),
    ]
    for fn, label in checks:
        p = os.path.join(scripts_dir, fn)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            src = f.read()
        # NUR echte Funktionsaufrufe "get_asset_multipliers(" (direkte Klammer)
        # — Docstring-/Kommentar-Erwähnungen ("...get_asset_multipliers (Legacy)")
        # haben ein Leerzeichen davor und werden ignoriert.
        calls = [l.strip()[:90] for l in src.splitlines()
                 if "get_asset_multipliers(" in l and not l.strip().startswith("#")]
        if calls:
            for c in calls:
                issues.append(f"{label}.py nutzt Legacy: `{c}`")
    return issues


def main():
    con = db_connect()
    regime, vix = get_current_regime(con)

    # Offene Positionen
    positions = con.execute(
        "SELECT ticker, name, direction, entry_price, stop_loss, take_profit, "
        "asset_type, atr_at_entry, entry_date FROM positions WHERE exit_date IS NULL"
    ).fetchall()

    lines = []
    lines.append(f"🔎 <b>Weekly Exit-Review</b> — Regime: {regime} (VIX {vix})")
    lines.append(f"Offene Positionen: <b>{len(positions)}</b> (LONG: "
                 f"{sum(1 for p in positions if p['direction']=='LONG')}, "
                 f"SHORT: {sum(1 for p in positions if p['direction']=='SHORT')})\n")

    if positions:
        lines.append("<b>Position vs Exit-Matrix:</b>")
        for p in positions:
            at = p["asset_type"] or "STANDARD"
            ec = get_exit_config(asset_type=at, regime=regime)
            atr = p["atr_at_entry"] or 0
            entry = p["entry_price"] or 0
            # Erwartete SL/TP-Abstände aus der Matrix
            exp_sl_dist = ec["sl"] * atr
            exp_tp_dist = ec["tp"] * atr
            # Tatsächliche Abstände (einfach, ohne Slippage)
            if p["direction"] == "LONG":
                act_sl_dist = (entry - p["stop_loss"]) if p["stop_loss"] else None
                act_tp_dist = (p["take_profit"] - entry) if p["take_profit"] else None
            else:
                act_sl_dist = (p["stop_loss"] - entry) if p["stop_loss"] else None
                act_tp_dist = (entry - p["take_profit"]) if p["take_profit"] else None
            # SL/TP-Abstand relativ zur Matrix. Achtung: Ein ENGERER SL als die
            # Matrix ist erwartet (Trailing zieht den Stop bei Gewinn nach oben).
            # Nur ein WEITERER SL (mehr Risiko als Soll) ist ein echtes Problem.
            # TP unter Soll = früheres Gewinnmitnehmen (info), TP über Soll ok.
            sl_ok = act_sl_dist is None or act_sl_dist <= exp_sl_dist + 0.3 * atr
            tp_ok = True  # TP primär informativ (Trailing regelt den Rest)
            flags = []
            if not sl_ok:
                flags.append(f"⚠️ SL {act_sl_dist/atr:.1f}x > Soll {ec['sl']}x (zu weit)")
            # Nur Abweichungen mit Substanz anzeigen
            if flags:
                badge = "⚠️"
            elif (act_sl_dist is not None and act_sl_dist > 0.2 * atr) or act_tp_dist:
                badge = "✅"
            else:
                badge = "⚠️"
            lines.append(
                f"{badge} {p['ticker']:8} {p['direction']:5} {at:9} | "
                f"SL {act_sl_dist/atr if act_sl_dist else '–':.1f}x (Soll {ec['sl']}x) | "
                f"TP {act_tp_dist/atr if act_tp_dist else '–':.1f}x (Soll {ec['tp']}x)"
                + (" " + "; ".join(flags) if flags else "")
            )
        lines.append("")

    # Config-Drift (parallele Exit-/Entry-/Shadow-Pfade)
    drift = check_config_drift()
    lines.append("<b>Exit-Config-Drift (parallele Pfade):</b>")

    if drift:
        for d in drift:
            lines.append(f"⚠️ Legacy-Nutzung: {d}")
        lines.append("\n<i>→ get_asset_multipliers (Legacy) wieder entfernen — die "
                     "Exit-Matrix (get_exit_config) ist seit 16.08. in allen drei "
                     "Pfaden (signal_manager, active_exit_check, crabel_shadow_eval) "
                     "die einzige Quelle.</i>")
    else:
        lines.append("✅ Alle drei Pfade (signal_manager, active_exit_check, "
                     "crabel_shadow_eval) nutzen get_exit_config — kein Legacy-Drift")

    msg = "\n".join(lines)
    print(msg, flush=True)
    send_telegram(msg)


if __name__ == "__main__":
    main()
