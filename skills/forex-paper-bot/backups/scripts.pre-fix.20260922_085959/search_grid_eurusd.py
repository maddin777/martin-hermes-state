"""
search_grid_eurusd.py — Konzentrationsrisiko-Test: Nur EUR/USD, 1D, mit zwangsweise
Weekly-Regime-Gate (jede profitable Variante MUSS ein Regime-Filter bestehen => robust,
nicht abhängig von einem einzelnen Paar wie USDJPY im 5-Paar-Grid).

Frage: Gibt es eine profitable 1D-EMA-Kreuz-Variante auf EUR/USD OHNE den
USDJPY-Verzerrungseffekt? Wenn nein auf EURUSD, ist die 5-Paar-Profite stattdessen
ein Paar-spezifischer Trend, kein robuster Effekt.

Parameterraum (breiter, nur EURUSD):
  ema_fast  [5, 8, 13, 20]
  ema_slow  [21, 34, 50, 100, 200] (>fast)
  min_strength [0.0002, 0.0005, 0.001, 0.002, 0.003]
  sl_mult   [1.0, 1.5, 2.0, 2.5, 3.0]
  trailing  [0.5, 1.0, 2.0, 3.0]
  momentum_lookback [3, 5, 8]
  use_weekly = ALWAYS True (Filter)
  pyramid   [False, True]

Random-Sample auf max 50 Kombis. Lookback 1000d.
"""
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair, _scalar
import pandas as pd
import numpy as np

from search_grid_1d import ema_np, atr_series, weekly_bias, simulate, metrics, _f


def build_grid(rng):
    combos = []
    for fast in [5, 8, 13, 20]:
        for slow in [21, 34, 50, 100, 200]:
            if slow <= fast:
                continue
            for ms in [0.0002, 0.0005, 0.001, 0.002, 0.003]:
                for slm in [1.0, 1.5, 2.0, 2.5, 3.0]:
                    for trm in [0.5, 1.0, 2.0, 3.0]:
                        for mlb in [3, 5, 8]:
                            for pyr in [False, True]:
                                combos.append(dict(fast=fast, slow=slow, min_strength=ms,
                                                   sl_mult=slm, trailing=trm, mom_lb=mlb,
                                                   use_weekly=True, pyramid=pyr))
    rng.shuffle(combos)
    seen = set(); dedup = []
    for c in combos:
        k = (c["fast"], c["slow"], c["min_strength"], c["sl_mult"], c["trailing"], c["mom_lb"], c["pyramid"])
        if k in seen:
            continue
        seen.add(k); dedup.append(c)
    return dedup[:50]


def main():
    c = cfg.CONFIG
    wf = c["walk_forward"]
    hold_cap_days = wf["holding_days_cap"]
    LOOKBACK_DAYS = 1000
    PAIR = "EURUSD=X"
    rng = random.Random(7)

    grid = build_grid(rng)
    df = fetch_pair(PAIR, LOOKBACK_DAYS, "1d")
    if df is None or len(df) < 250:
        print(f"❌ {PAIR}: unzureichende Daten")
        return 1
    wk = weekly_bias(df, 20)
    pip = c["pairs"][PAIR]["pip_size"]
    spread = c["pairs"][PAIR]["spread_pips"]

    print(f"=== EUR/USD-Konzentrationstest: {len(grid)} Kombis, Weekly-Gate IMMER an, Lookback {LOOKBACK_DAYS}d (netto) ===")
    rows = []
    for idx, gp in enumerate(grid):
        trades = simulate(df, wk, gp["fast"], gp["slow"], gp["mom_lb"], gp["min_strength"],
                          gp["sl_mult"], gp["trailing"], hold_cap_days, gp["use_weekly"], gp["pyramid"])
        m = metrics(trades, pip, spread)
        rows.append({"combo": {**gp}, "net": m["net"], "trades": m["trades"], "pf": m["pf"], "wr": m["wr"]})

    good = [r for r in rows if r["net"] > 0 and r["trades"] >= 8]
    rest = [r for r in rows if not (r["net"] > 0 and r["trades"] >= 8)]
    good.sort(key=lambda r: (-r["net"], -r["trades"]))
    rest.sort(key=lambda r: (-r["net"], -r["trades"]))
    ranking = good + rest

    print(f"\nProfitabel mit >=8 Trades: {len(good)} / {len(rows)}")
    print(f"\n=== TOP 12 (nur EUR/USD, Weekly-Gate) ===")
    print(f"{'#':>3} {'net[pps]':>10}{'trd':>6}{'PF':>7}{'WR':>6}  Beschreibung")
    for i, r in enumerate(ranking[:12]):
        g = r["combo"]
        desc = (f"EMA{g['fast']}/{g['slow']} schw={g['min_strength']} sl={g['sl_mult']} "
                f"trail={g['trailing']} momlb={g['mom_lb']} pyr={g['pyramid']}")
        print(f"{i+1:>3} {r['net']:>10}{r['trades']:>6}{r['pf']:>7}{r['wr']:>6}  {desc}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports", "grid_search_eurusd_result.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ranking": ranking}, f, indent=2, ensure_ascii=False)
    print(f"\nDetail: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
