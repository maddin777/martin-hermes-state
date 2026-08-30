"""
search_grid_robust.py — Robuster, konzentrationsfreier Trendfolge-Test.

Ziel: Statt nach netto-hoch über alle Paare zu optimieren (was USDJPY-verzerrt),
finde Konfigurationen die in JEDEM einzelnen geprüften Paar positiv sind (robust).
Das eliminiert das Konzentrationsrisiko (1 dominantes Paar trägt alles).

Design:
  - Timeline: 1D UND 1W (Weekly) separat testen
  - Paare: EURUSD, GBPUSD, AUDUSD, USDCHF, (USDJPY zusätzlich, aber nicht dominierend)
  - Regime-Filter: Weekly (beim 1D-Test) / Monthly (beim 1W-Test) — immer an
  - Grid: breiter Parameterraum, random-sample bis 50
  - Ranking: SCORE = #Paare die positiv sind (robustheit) als Hauptkriterium,
    dann netto über die positiven. Eine Variante muss in ALLEN Paaren >0 sein,
    um als 'robust' zu gelten.

Bewertung je Konfiguration:
  - per_pair net
  - n_positiv = wie viele der N Paare net > 0
  - robust = True falls n_positiv == N und min(net) > 0 (alle positiv)
  - total_net = Summe
"""
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair
import pandas as pd
import numpy as np

from search_grid_1d import ema_np, atr_series, simulate, metrics, _f


def bias_to_tf(df, tf_span_idx, span=20):
    """Bias eines higher-TF (Weekly für 1D, Monthly für 1W) forward-filled."""
    # resample auf W oder ME
    if tf_span_idx == "W":
        d = df.resample("W").last().dropna()
    else:
        d = df.resample("ME").last().dropna()
    if len(d) < span + 3:
        return np.zeros(len(df))
    close = d["Close"].astype(float).to_numpy().ravel()
    e = ema_np(close, span)
    wk_bias = np.where(close > e, 1, np.where(close < e, -1, 0))
    wk_index = d.index
    times = pd.to_datetime(df.index)
    bias_arr = np.zeros(len(df))
    j = 0
    for i, t in enumerate(times):
        while j + 1 < len(wk_index) and wk_index[j + 1] <= t:
            j += 1
        if wk_index[j] <= t:
            bias_arr[i] = wk_bias[j]
    return bias_arr


def build_grid(rng):
    combos = []
    for fast in [5, 8, 13, 20, 26]:
        for slow in [34, 50, 100, 150, 200]:
            if slow <= fast:
                continue
            for ms in [0.0002, 0.0005, 0.001, 0.002, 0.003]:
                for slm in [1.0, 1.5, 2.0, 2.5, 3.0]:
                    for trm in [0.5, 1.0, 2.0]:
                        for mlb in [3, 5, 8]:
                            for pyr in [False, True]:
                                combos.append(dict(fast=fast, slow=slow, min_strength=ms,
                                                   sl_mult=slm, trailing=trm, mom_lb=mlb,
                                                   pyramid=pyr))
    rng.shuffle(combos)
    seen = set(); dedup = []
    for c in combos:
        k = (c["fast"], c["slow"], c["min_strength"], c["sl_mult"], c["trailing"], c["mom_lb"], c["pyramid"])
        if k in seen:
            continue
        seen.add(k); dedup.append(c)
    return dedup[:50]


def run_timeline(timeline, pairs, hold_cap_days, LOOKBACK_DAYS=1000):
    c = cfg.CONFIG
    rng = random.Random(11)
    grid = build_grid(rng)
    tf_index = "W" if timeline == "1d" else "ME"

    print(f"\n===== TIMELINE {timeline} | {len(grid)} Kombis × {len(pairs)} Paare | Lookback {LOOKBACK_DAYS}d =====")
    pair_data = {}
    for pair in pairs:
        df = fetch_pair(pair, LOOKBACK_DAYS, timeline)
        if df is None or len(df) < 200:
            print(f"  ❌ {pair} {timeline}: keine Daten")
            continue
        bias = bias_to_tf(df, tf_index, 20)
        pair_data[pair] = {"df": df, "bias": bias,
                           "pip": c["pairs"].get(pair, {}).get("pip_size", 0.0001),
                           "spread": c["pairs"].get(pair, {}).get("spread_pips", 1.0)}
    pairs_ok = list(pair_data.keys())
    if not pairs_ok:
        return

    results = []
    for gp in grid:
        per_pair = {}
        for pair, pd_ in pair_data.items():
            trades = simulate(pd_["df"], pd_["bias"], gp["fast"], gp["slow"], gp["mom_lb"],
                              gp["min_strength"], gp["sl_mult"], gp["trailing"], hold_cap_days,
                              use_weekly=True, pyramid=gp["pyramid"])
            m = metrics(trades, pd_["pip"], pd_["spread"])
            per_pair[pair] = m
        total_net = sum(m["net"] for m in per_pair.values())
        total_trades = sum(m["trades"] for m in per_pair.values())
        n_pos = sum(1 for m in per_pair.values() if m["net"] > 0)
        robust = n_pos == len(per_pair) and all(m["net"] > 0 for m in per_pair.values()) and total_trades >= 10
        results.append({"combo": gp, "net": round(total_net, 1), "trades": total_trades,
                        "n_pos": n_pos, "robust": robust, "per_pair": per_pair})

    robust_rows = [r for r in results if r["robust"]]
    robust_rows.sort(key=lambda r: -r["net"])
    others = [r for r in results if not r["robust"]]
    others.sort(key=lambda r: (-r["n_pos"], -r["net"]))
    ranking = robust_rows + others

    print(f"ROBUST (positiv in ALLEN {len(pairs_ok)} Paaren, >=10 Trades): {len(robust_rows)} / {len(results)}")
    print(f"\n=== TOP 15 (robuste zuerst, dann n_pos) ===")
    print(f"{'#':>3} {'net[pps]':>9}{'trd':>6}{'nPos':>5}  Beschreibung")
    for i, r in enumerate(ranking[:15]):
        g = r["combo"]
        desc = (f"EMA{g['fast']}/{g['slow']} schw={g['min_strength']} sl={g['sl_mult']} "
                f"trail={g['trailing']} momlb={g['mom_lb']} pyr={g['pyramid']}")
        flag = " ← ROBUST" if r["robust"] else ""
        print(f"{i+1:>3} {r['net']:>9}{r['trades']:>6}{r['n_pos']:>5}  {desc}{flag}")
    print(f"\n--- Netto je Paar der Top-5 (Robust-Check) ---")
    for i, r in enumerate(ranking[:5]):
        print(f"\n#{i+1} net={r['net']} trd={r['trades']} nPos={r['n_pos']}")
        for p, m in r["per_pair"].items():
            print(f"     {p}: net={m['net']:>6} trd={m['trades']:>3} pf={m['pf']} wr={m['wr']}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports", f"grid_robust_{timeline}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ranking": ranking}, f, indent=2, ensure_ascii=False)
    print(f"\nDetail: {out}")


def main():
    pairs_all = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "USDCHF=X"]
    c = cfg.CONFIG
    wf = c["walk_forward"]
    hold_cap_days = wf["holding_days_cap"]
    LOOKBACK_DAYS = 1000
    # 1D-Timeline
    run_timeline("1d", pairs_all, hold_cap_days, LOOKBACK_DAYS)
    # Weekly-Timeline (mehr Tage für genug Candles)
    run_timeline("1wk", pairs_all, hold_cap_days, LOOKBACK_DAYS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
