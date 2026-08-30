"""
walk_forward_1d.py — Out-of-Sample-Validierung der robusten 1D-Trendfolge.

Frage: Hält die Grid-Search-Profite (EMA8/150 etc.) sich out-of-sample vorwärts,
oder sind sie ein 4-Jahres-Fit?

Selbstdurchführend:
  - Zwei walk-forward Fenster:
      A: erstes 60% train (Param-Wahl), letzte 40% out-of-sample Test
      B: erstes 40% train, letzte 60% out-of-sample Test
  - In der Train-Phase wird über ein kleines Grid (fast/slow/Momentum) die beste
    robuste Paramgruppe (n_pos maximieren, dann netto) gewählt, NUR auf Train-Daten.
  - Dann die gewählten Params auf das Test-Fenster (out-of-sample) angewandt, netto nach Spread.
"""
import sys, os, json, itertools, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair
import pandas as pd
import numpy as np

from search_grid_1d import ema_np, atr_series, weekly_bias, metrics, _f


PAIRS_WANT = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "USDCHF=X"]

# Ab hier eigene, korrekte simulate mit mom_lb Param (selbsterklärend)
def atr_series_local(df, n=14):
    h = df["High"].astype(float); l = df["Low"].astype(float); c = df["Close"].astype(float)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def simulate_day(df, wk_b, fast, slow, mom_lb, min_strength, sl_mult, trail_mult,
                 hold_cap_days, pyramid=False):
    close = df["Close"].astype(float).to_numpy()
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    atr = atr_series_local(df, 14).to_numpy()
    fe = ema_np(close, fast); se = ema_np(close, slow)
    trades = []
    pos = None
    entry_bar = 0
    n = len(df)
    start = max(fast, slow) + mom_lb
    for i in range(start, n):
        a = atr[i]
        if pos is None:
            if np.isnan(a):
                continue
            cross_now = fe[i] > se[i]; cross_prev = fe[i - 1] > se[i - 1]
            prev = close[i - mom_lb] if i - mom_lb >= 0 else 0.0
            mom = (close[i] / prev - 1.0) if prev else 0.0
            wgb = wk_b[i] if i < len(wk_b) else 0.0
            long_ok = cross_now and not cross_prev and mom > min_strength and wgb == 1
            short_ok = (not cross_now) and cross_prev and mom < -min_strength and wgb == -1
            if long_ok:
                pos = {"dir": "LONG", "entry": close[i], "sl": close[i] - sl_mult * a, "extreme": close[i]}
                entry_bar = i
            elif short_ok:
                pos = {"dir": "SHORT", "entry": close[i], "sl": close[i] + sl_mult * a, "extreme": close[i]}
                entry_bar = i
        else:
            if np.isnan(a):
                a = atr[i - 1] if i > 0 else 0.0
            hi, lo = high[i], low[i]
            if pos["dir"] == "LONG":
                pos["extreme"] = max(pos["extreme"], hi - trail_mult * a)
                pos["sl"] = max(pos["sl"], pos["extreme"])
                if lo <= pos["sl"] or (i - entry_bar) >= hold_cap_days:
                    trades.append({"entry": pos["entry"], "exit": pos["sl"], "dir": "LONG"})
                    pos = None
            else:
                pos["extreme"] = min(pos["extreme"], lo + trail_mult * a)
                pos["sl"] = min(pos["sl"], pos["extreme"])
                if hi >= pos["sl"] or (i - entry_bar) >= hold_cap_days:
                    trades.append({"entry": pos["entry"], "exit": pos["sl"], "dir": "SHORT"})
                    pos = None
    if pos is not None:
        trades.append({"entry": pos["entry"], "exit": close[-1], "dir": pos["dir"]})
    return trades


def train_grid(rng):
    combos = []
    for fast in [5, 8, 13, 20]:
        for slow in [100, 150, 200]:
            if slow <= fast:
                continue
            for ms in [0.0002, 0.0005, 0.001, 0.002, 0.003]:
                for slm in [1.0, 1.5, 2.0, 2.5]:
                    for trm in [0.5, 1.0, 2.0]:
                        for mlb in [3, 5, 8]:
                            combos.append(dict(fast=fast, slow=slow, min_strength=ms,
                                               sl_mult=slm, trailing=trm, mom_lb=mlb))
    rng.shuffle(combos)
    seen = set(); dedup = []
    for c in combos:
        k = (c["fast"], c["slow"], c["min_strength"], c["sl_mult"], c["trailing"], c["mom_lb"])
        if k in seen:
            continue
        seen.add(k); dedup.append(c)
    return dedup[:50]


def run_window(pair_data, frac_train):
    """Train-Wahl + OOS-Test."""
    c = cfg.CONFIG
    hold_cap = c["walk_forward"]["holding_days_cap"]
    # Train-Subset: erste frac_train der Daten je Paar
    train_sets = {}
    for pair, pd_ in pair_data.items():
        n = len(pd_["df"])
        cut = int(n * frac_train)
        train_sets[pair] = {"df": pd_["df"].iloc[:cut], "bias": pd_["bias"][:cut],
                            "pip": pd_["pip"], "spread": pd_["spread"]}

    rng = random.Random(3)
    grid = train_grid(rng)
    best = None; best_score = -1e9
    for gp in grid:
        n_pos = 0; total_net = 0.0
        for pair, ts in train_sets.items():
            tr = simulate_day(ts["df"], ts["bias"], gp["fast"], gp["slow"], gp["mom_lb"],
                              gp["min_strength"], gp["sl_mult"], gp["trailing"], hold_cap)
            m = metrics(tr, ts["pip"], ts["spread"])
            if m["net"] > 0:
                n_pos += 1
            total_net += m["net"]
        score = n_pos * 100 + total_net  # Robustheit dominiert
        if score > best_score:
            best_score = score
            best = {**gp, "train_npos": n_pos, "train_net": round(total_net, 1)}
    # --- OOS Test ---
    test_out = {}
    if best is None:
        return None, None, None
    for pair, pd_ in pair_data.items():
        n = len(pd_["df"])
        cut = int(n * frac_train)
        if cut >= n:
            continue
        ts = pd_["df"].iloc[cut:], pd_["bias"][cut:]
        tr = simulate_day(ts[0], ts[1], best["fast"], best["slow"], best["mom_lb"],
                          best["min_strength"], best["sl_mult"], best["trailing"], hold_cap)
        m = metrics(tr, pd_["pip"], pd_["spread"])
        test_out[pair] = m
    return best, test_out, frac_train


def main():
    c = cfg.CONFIG
    LOOKBACK_DAYS = 1000
    pair_data = {}
    for pair in PAIRS_WANT:
        df = fetch_pair(pair, LOOKBACK_DAYS, "1d")
        if df is None or len(df) < 250:
            print(f"  ❌ {pair}: kein Daten")
            continue
        bias = weekly_bias(df, 20)
        pair_data[pair] = {"df": df, "bias": bias,
                           "pip": c["pairs"].get(pair, {}).get("pip_size", 0.0001),
                           "spread": c["pairs"].get(pair, {}).get("spread_pips", 1.0)}

    print("=== WALK-FORWARD OUT-OF-SAMPLE (1D, netto nach Spread) ===")
    for frac in [0.6, 0.4]:
        best, test_out, _ = run_window(pair_data, frac)
        print(f"\n--- Fenster: {int(frac*100)}% train / {int((1-frac)*100)}% test ---")
        if best is None:
            print("  keine Kombi")
            continue
        print(f"  Train-gewählte Params: EMA{best['fast']}/{best['slow']} schw={best['min_strength']} "
              f"sl={best['sl_mult']} trail={best['trailing']} momlb={best['mom_lb']}")
        print(f"  auf Train: nPos={best['train_npos']}/{len(pair_data)} net={best['train_net']}")
        # OOS-Aggregate
        tot = 0.0; trd = 0; npos = 0
        for p, m in test_out.items():
            tot += m["net"]; trd += m["trades"]
            if m["net"] > 0:
                npos += 1
        print(f"  >>> OUT-OF-SAMPLE: net={round(tot,1)} pips, {trd} Trades, nPos={npos}/{len(test_out)}")
        for p, m in test_out.items():
            print(f"       {p}: net={m['net']:>6} trd={m['trades']:>3} pf={m['pf']} wr={m['wr']}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports", "walk_forward_1d.txt")
    print(f"\n(Ergebnis nur Konsole; Detail nicht persistiert.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
