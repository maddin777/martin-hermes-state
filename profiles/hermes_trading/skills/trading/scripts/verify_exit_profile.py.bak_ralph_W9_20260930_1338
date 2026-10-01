#!/usr/bin/env python3
"""Rechnet einen Exit-Profil-Wechsel auf echten Trades durch, BEVOR er live geht.

Aufruf:
    python3 scripts/verify_exit_profile.py                 # current vs. wider_stop
    python3 scripts/verify_exit_profile.py --time-stop 5    # zusaetzlich Time-Stop testen

Warum es das gibt: Der Vorgaenger dieser Pruefung (strategy_optimizer vor dem
18.09.2026) verglich Parameter nur am realisierten Exit-PREIS und empfahl
deshalb systematisch zu enge Stops. Hier laeuft stattdessen
exit_rules.replay_exit_path ueber die echten OHLC-Bars — dieselbe Funktion,
die auch der Optimizer benutzt.

Das Skript aendert NICHTS. Es druckt nur den Vergleich inkl. Split-Half und
Bootstrap-Konfidenzintervall, damit man sieht, ob ein Unterschied belastbar
ist oder im Rauschen liegt.
"""
import argparse
import random
import statistics
import sys

from config import db_connect, get_exit_config, EXIT_PROFILES
from exit_rules import replay_exit_path
from trade_paths import attach_paths


def load_trades(con):
    rows = con.execute("""
        SELECT * FROM positions
        WHERE status='closed' AND entry_price IS NOT NULL
        ORDER BY entry_date ASC
    """).fetchall()
    return [dict(r) for r in rows]


def run(trades, sl_scale, time_stop, cfg):
    """Replay aller Trades mit einem Stop-Skalierungsfaktor. Returns Liste R."""
    donchian_primary = (bool(cfg.get("donchian_exit_enabled"))
                        and cfg.get("donchian_exit_mode") == "primary")
    out = []
    for t in trades:
        ex = get_exit_config(asset_type=t.get("asset_type") or "STANDARD",
                             regime="sideways")
        res = replay_exit_path(
            t["_bars"], t["_entry_idx"], t["entry_price"],
            t.get("direction", "LONG"), t["_atr"],
            sl_mult=round(ex["sl"] * sl_scale, 2),
            partial_atr=ex["partial_atr"],
            partial_pct=(cfg.get("partial_tp_pct", 0.5)
                         if cfg.get("partial_tp_enabled", True) else 0.0),
            profit_lock_atr=ex["profit_lock_atr"],
            chandelier_mult=ex["chandelier_mult"],
            donchian_primary=donchian_primary,
            donchian_period=cfg.get("donchian_exit_period", 10),
            time_stop_bars=time_stop,
            tp_mult=None,
        )
        if res["r_multiple"] is not None:
            out.append(res["r_multiple"])
    return out


def describe(rs):
    w = [x for x in rs if x > 0] or [0.0]
    l = [x for x in rs if x <= 0] or [-1e-9]
    return {
        "n": len(rs),
        "meanR": statistics.mean(rs),
        "wr": 100 * len([x for x in rs if x > 0]) / len(rs),
        "pf": sum(w) / abs(sum(l)),
    }


def line(label, rs):
    d = describe(rs)
    print(f"  {label:34s} n={d['n']:3d}  meanR={d['meanR']:+.3f}  "
          f"WR={d['wr']:5.1f}%  PF={d['pf']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-stop", type=int, default=None,
                    help="Time-Stop, den die Variante testen soll "
                         "(Default: unveraendert aus der Config)")
    ap.add_argument("--profile", default="wider_stop",
                    help="Zu testendes Profil aus EXIT_PROFILES")
    args = ap.parse_args()

    if args.profile not in EXIT_PROFILES:
        print(f"❌ Unbekanntes Profil '{args.profile}'. "
              f"Bekannt: {', '.join(EXIT_PROFILES)}")
        return 1

    import json
    from config import STRATEGY_CONFIG_PATH
    try:
        cfg = json.load(open(STRATEGY_CONFIG_PATH))
    except Exception:
        cfg = {}

    con = db_connect()
    trades = load_trades(con)
    con.close()
    print(f"📦 {len(trades)} geschlossene Trades geladen")

    stats = attach_paths(trades)
    trades = [t for t in trades if t.get("_bars")]
    if stats["coverage"] < 0.70:
        print(f"❌ Pfad-Abdeckung nur {stats['coverage']:.0%} — zu wenig für eine "
              f"belastbare Aussage. Abbruch.")
        return 1

    ts_now = cfg.get("time_stop_trading_days", 7)
    ts_new = args.time_stop if args.time_stop is not None else ts_now
    scale_new = EXIT_PROFILES[args.profile]["sl_scale"]

    donch = (bool(cfg.get("donchian_exit_enabled"))
             and cfg.get("donchian_exit_mode") == "primary")
    print(f"\n⚙️  Live-Mechanik: "
          f"{'Donchian-primary (ATR-Chandelier ist abgeschaltet)' if donch else 'ATR-Chandelier'}"
          f" | Time-Stop {ts_now}d\n")

    base = run(trades, 1.0, ts_now, cfg)
    var  = run(trades, scale_new, ts_new, cfg)

    print("=== Gesamt ===")
    line(f"IST (current, TimeStop {ts_now}d)", base)
    line(f"{args.profile} (x{scale_new}, TimeStop {ts_new}d)", var)
    print(f"\n  Δ meanR = {statistics.mean(var) - statistics.mean(base):+.3f} R/Trade")

    half = len(trades) // 2
    print("\n=== Split-Half (Robustheit über die Zeit) ===")
    for lbl, subset in (("1. Hälfte", trades[:half]), ("2. Hälfte", trades[half:])):
        b = run(subset, 1.0, ts_now, cfg)
        v = run(subset, scale_new, ts_new, cfg)
        print(f"  {lbl}: IST {statistics.mean(b):+.3f}  →  "
              f"{args.profile} {statistics.mean(v):+.3f}  "
              f"({'besser' if statistics.mean(v) > statistics.mean(b) else 'SCHLECHTER'})")

    print("\n=== Bootstrap 95%-KI für die Differenz (2000 Resamples) ===")
    random.seed(17)
    pairs = list(zip(base, var))
    diffs = []
    for _ in range(2000):
        smp = random.choices(pairs, k=len(pairs))
        diffs.append(statistics.mean(v - b for b, v in smp))
    diffs.sort()
    lo, hi = diffs[50], diffs[1949]
    print(f"  Δ meanR = {statistics.mean(var) - statistics.mean(base):+.3f}  "
          f"KI = [{lo:+.3f}, {hi:+.3f}]")
    if lo > 0:
        print("  ✅ KI komplett über null — der Unterschied ist belastbar.")
    else:
        print("  ⚠️  KI schließt die Null ein — richtungsweisend, NICHT bewiesen.")
        print("     Das ist bei ~80 Trades der Normalfall und kein Grund, nichts")
        print("     zu tun — aber ein Grund, die Änderung als Experiment mit")
        print("     Abbruchkriterium zu fahren, nicht als 'Lösung'.")

    print(f"\n📊 Ganze Leiter zum Vergleich (TimeStop {ts_new}d):")
    for name in sorted(EXIT_PROFILES, key=lambda k: EXIT_PROFILES[k]["sl_scale"]):
        d = describe(run(trades, EXIT_PROFILES[name]["sl_scale"], ts_new, cfg))
        mark = " <- gewaehlt" if name == args.profile else (
            " <- aktiv" if name == cfg.get("exit_profile", "current") else "")
        print(f"  {name:24s} x{EXIT_PROFILES[name]['sl_scale']:.2f}  "
              f"meanR={d['meanR']:+.3f}  WR={d['wr']:5.1f}%  PF={d['pf']:.2f}{mark}")

    print(f"\n📋 Scharfschalten (ändert nichts an diesem Skript):")
    print(f'   strategy_config.json:  "exit_profile": "{args.profile}"')
    if ts_new != ts_now:
        print(f'                          "time_stop_trading_days": {ts_new}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
