"""
search_grid_1d.py — Grid-Search über eine 1D (Tages)-EMA-Trendfolge auf den 5 Forex-Majors.

Zweck: Nachdem die 15m-Variante strukturell unprofitabel war (Spread-Friktion), hier der
Test ob eine Tages-Timeline die Spread-Kosten relativ zur größeren Ziel-Bewegung trägt.

Timeline-Design (analog zum 15m-Bot, hochskaliert):
  - Einstiegs-TF: 1D (Tages-Candles), ~4 Jahre History (Lookback ~1000 Tage)
  - Trendfilter: 1W (Weekly) EMA — nur LONG wenn Weekly bullish, SHORT wenn bearish
  - EMA-Kreuz auf 1D (fast vs slow) + Momentum-Schwelle
  - SL/Trailing aus Tages-ATR (größere ATR => größere SL/Pip-Ziele)
  - Pyramiding (Nachkauf in Trendrichtung) optional
  - Holding-Cap in Tagen (config walk_forward.holding_days_cap)

Spread-Kosten: auf Entry UND Exit (netto), wie im Live-Bot.

Grid (max 50 Kombis):
  ema_fast [8, 20], ema_slow [21, 50, 100] (>fast), min_strength [0.0002,0.001,0.003],
  sl_mult [1.0, 1.5, 2.5], trailing [0.5, 1.0, 2.0], use_weekly [False, True], pyramid [False, True]
"""
import sys, os, json, itertools, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair
import pandas as pd
import numpy as np


def ema_np(arr, span):
    alpha = 2.0 / (span + 1.0)
    arr = np.asarray(arr).ravel()
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def atr_series(df, n=14):
    h = df["High"].astype(float); l = df["Low"].astype(float); c = df["Close"].astype(float)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def weekly_bias(df, span=20):
    """Weekly-Bias als +1/-1/0 je Daily-Candle (forward-filled aus Weekly-EMA)."""
    d = df.resample("W").last().dropna()  # Weekly schließen
    if len(d) < span + 3:
        return np.zeros(len(df))
    close = d["Close"].astype(float).to_numpy().ravel()
    e = ema_np(close, span)
    wk_bias = np.where(close > e, 1, np.where(close < e, -1, 0))
    wk_index = d.index
    # jedem Daily-Tag den letzten Weekly-Bias zuordnen (Datum <= Tag)
    times = pd.to_datetime(df.index)
    bias_arr = np.zeros(len(df))
    j = 0
    for i, t in enumerate(times):
        while j + 1 < len(wk_index) and wk_index[j + 1] <= t:
            j += 1
        if wk_index[j] <= t:
            bias_arr[i] = wk_bias[j]
        else:
            bias_arr[i] = np.nan
    # NaN am Anfang mit 0
    bias_arr = np.nan_to_num(bias_arr, nan=0.0)
    return bias_arr


def simulate(df, wk_b, fast, slow, mom_lb, min_strength, sl_mult, trail_mult,
             hold_cap_days, use_weekly, pyramid, pyr_every_atr=1.5, pyr_max=3):
    """1D-Trendfolge mit Weekly-Gate + Pyramiding + Chandelier-Trailing."""
    close = df["Close"].astype(float).to_numpy()
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    atr = atr_series(df, 14).to_numpy()
    fe = ema_np(close, fast); se = ema_np(close, slow)

    trades = []
    units = []  # offene Einheiten [{dir,entry,sl,extreme,bars}]
    n = len(df)
    start = max(fast, slow) + mom_lb
    i = start
    while i < n:
        a = atr[i]
        if len(units) == 0 and not np.isnan(a):
            cross_now = fe[i] > se[i]; cross_prev = fe[i - 1] > se[i - 1]
            prev = close[i - mom_lb] if i - mom_lb >= 0 else 0.0
            mom = (close[i] / prev - 1.0) if prev else 0.0
            wgb = wk_b[i] if i < len(wk_b) else 0.0
            long_ok = cross_now and not cross_prev and mom > min_strength
            short_ok = (not cross_now) and cross_prev and mom < -min_strength
            if use_weekly:
                long_ok = long_ok and wgb == 1
                short_ok = short_ok and wgb == -1
            if long_ok:
                units.append({"dir": "LONG", "entry": close[i], "sl": close[i] - sl_mult * a,
                              "extreme": close[i], "bars": 0})
            elif short_ok:
                units.append({"dir": "SHORT", "entry": close[i], "sl": close[i] + sl_mult * a,
                              "extreme": close[i], "bars": 0})
        if len(units) > 0:
            if np.isnan(a):
                a = atr[i - 1] if i > 0 else 0.0
            dir0 = units[0]["dir"]
            last_entry = units[-1]["entry"]
            adds = sum(1 for u in units if u["bars"] > 0)
            if dir0 == "LONG" and adds < pyr_max and close[i] >= last_entry + pyr_every_atr * a:
                units.append({"dir": "LONG", "entry": close[i], "sl": close[i] - sl_mult * a,
                              "extreme": close[i], "bars": 0})
            elif dir0 == "SHORT" and adds < pyr_max and close[i] <= last_entry - pyr_every_atr * a:
                units.append({"dir": "SHORT", "entry": close[i], "sl": close[i] + sl_mult * a,
                              "extreme": close[i], "bars": 0})
            exits = []
            for u in units:
                u["bars"] += 1
                hi, lo = high[i], low[i]
                if u["dir"] == "LONG":
                    u["extreme"] = max(u["extreme"], hi - trail_mult * a)
                    u["sl"] = max(u["sl"], u["extreme"])
                    if lo <= u["sl"] or u["bars"] >= hold_cap_days:
                        exits.append({"entry": u["entry"], "exit": u["sl"], "dir": "LONG"})
                else:
                    u["extreme"] = min(u["extreme"], lo + trail_mult * a)
                    u["sl"] = min(u["sl"], u["extreme"])
                    if hi >= u["sl"] or u["bars"] >= hold_cap_days:
                        exits.append({"entry": u["entry"], "exit": u["sl"], "dir": "SHORT"})
            for e in exits:
                trades.append(e)
                units.remove(next(u for u in units if u["entry"] == e["entry"]))
        i += 1
    for u in units:
        trades.append({"entry": u["entry"], "exit": close[-1], "dir": u["dir"]})
    return trades


def _f(v):
    if hasattr(v, "item"):
        return float(v.item())
    return float(v)


def metrics(trades, pip_size, spread_pips):
    if not trades:
        return {"trades": 0, "net": 0.0, "pf": 0.0, "wr": 0.0}
    pips = []
    for t in trades:
        p = (_f(t["exit"]) - _f(t["entry"])) / pip_size
        if t["dir"] == "SHORT":
            p = -p
        pips.append(p - 2.0 * spread_pips)
    wins = [p for p in pips if p > 0]
    losses = [p for p in pips if p <= 0]
    gw = sum(wins); gl = abs(sum(losses))
    pf = gw / gl if gl else (gw if gw else 0.0)
    return {"trades": len(trades), "net": round(sum(pips), 1),
            "pf": round(pf, 2), "wr": round(len(wins) / len(trades), 3)}


def build_grid():
    combos = []
    for fast, slow, ms, slm, trm, wk, pyr in itertools.product(
            [8, 20], [21, 50, 100], [0.0002, 0.001, 0.003],
            [1.0, 1.5, 2.5], [0.5, 1.0, 2.0], [False, True], [False, True]):
        if slow <= fast:
            continue
        combos.append(dict(fast=fast, slow=slow, min_strength=ms, sl_mult=slm,
                           trailing=trm, use_weekly=wk, pyramid=pyr))
    random.seed(42)
    random.shuffle(combos)
    seen = set(); dedup = []
    for c in combos:
        k = (c["fast"], c["slow"], c["min_strength"], c["sl_mult"], c["trailing"], c["use_weekly"], c["pyramid"])
        if k in seen:
            continue
        seen.add(k); dedup.append(c)
    return dedup[:50]


def main():
    c = cfg.CONFIG
    wf = c["walk_forward"]
    hold_cap_days = wf["holding_days_cap"]  # in Tagen
    mom_lb = 5
    LOOKBACK_DAYS = 1000

    grid = build_grid()
    pairs = list(c["pairs"].keys())
    print(f"=== GRID-SEARCH 1D: {len(grid)} Kombis × {len(pairs)} Paare, Lookback {LOOKBACK_DAYS}d (netto nach Spread) ===")

    pair_data = {}
    for pair in pairs:
        df = fetch_pair(pair, LOOKBACK_DAYS, "1d")
        if df is None or len(df) < 250:
            print(f"  ❌ {pair}: unzureichende 1D-Daten")
            continue
        wk = weekly_bias(df, 20)
        pair_data[pair] = {"df": df, "wk": wk,
                           "pip": c["pairs"][pair]["pip_size"], "spread": c["pairs"][pair]["spread_pips"]}

    rows = []
    for idx, gp in enumerate(grid):
        total_net = 0.0; total_trades = 0; per_pair = {}
        for pair, pd_ in pair_data.items():
            trades = simulate(pd_["df"], pd_["wk"], gp["fast"], gp["slow"], mom_lb,
                              gp["min_strength"], gp["sl_mult"], gp["trailing"], hold_cap_days,
                              gp["use_weekly"], gp["pyramid"])
            m = metrics(trades, pd_["pip"], pd_["spread"])
            per_pair[pair] = m
            total_net += m["net"]; total_trades += m["trades"]
        rows.append({"combo": gp, "net": round(total_net, 1), "trades": total_trades, "per_pair": per_pair})

    good = [r for r in rows if r["net"] > 0 and r["trades"] >= 8]
    rest = [r for r in rows if not (r["net"] > 0 and r["trades"] >= 8)]
    good.sort(key=lambda r: (-r["net"], -r["trades"]))
    rest.sort(key=lambda r: (-r["net"], -r["trades"]))
    ranking = good + rest

    print(f"\n=== TOP 15 (profitabel + anständige Trade-Anzahl zuerst) ===")
    print(f"{'#':>3} {'net[pips]':>10}{'trades':>8}  Beschreibung")
    for i, r in enumerate(ranking[:15]):
        g = r["combo"]
        desc = (f"EMA{g['fast']}/{g['slow']} schw={g['min_strength']} sl={g['sl_mult']} "
                f"trail={g['trailing']} wk={g['use_weekly']} pyr={g['pyramid']}")
        print(f"{i+1:>3} {r['net']:>10}{r['trades']:>8}  {desc}")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports", "grid_search_1d_result.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"ranking": ranking}, f, indent=2, ensure_ascii=False)
    print(f"\nDetail-Ranking: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
