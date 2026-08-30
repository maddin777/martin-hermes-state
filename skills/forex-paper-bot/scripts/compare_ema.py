"""
compare_ema.py — Sauberer A/B-Vergleich der EMA-Kreuz-Konfigurationen auf dem
Forex-Paper-Bot, mit GETREUER Live-Modellierung (H1-Gate + Trailing-Stop).

Vergleicht pro Paar über das Walk-Forward-Lookback (8 Wochen):
  - A) aktuell:  ema_fast=20, ema_slow=50, trailing_atr_mult=1.0
  - B) Vorschlag: ema_fast=8,  ema_slow=21, trailing_atr_mult=1.0

Beide mit identischem H1-Gate (EMA-20 auf 1h) und Trailing-Stop (Chandelier):
  - Einstieg nur wenn 15m-EMA-Kreuz zur H1-Richtung passt
  - Initial-SL = entry ∓ sl_mult*ATR
  - Trailing: SL zieht hinter her, hält max(hi)-trail_mult*ATR Abstand (LONG), nie zurück
  - Kein fixer TP im Live (Trailing dominiert) — TP ignoriert wie trade.py

Ausgabe: pro Paar Trades, WR, PF, net (in Paar-Pips-Termen) + Gesamtaggregat.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair, fetch_trend_timeframe, _scalar

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
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def bias_series(h_df, ema_span):
    """Array +1=bullish, -1=bearish, 0=neutral je Candle des gegebenen Timeframes."""
    close = h_df["Close"].astype(float).to_numpy().ravel()
    e = ema_np(close, ema_span)
    return np.where(close > e, 1, np.where(close < e, -1, 0)).astype(float)


def _bias_to_15m(bias_arr, src_df, df15):
    """Bias eines höheren Timeframes (1h/4h) forward-fill auf die 15m-Zeitachse."""
    src_times = pd.to_datetime(src_df.index)
    bias_s = pd.Series(np.asarray(bias_arr).ravel(), index=src_times)
    times15 = pd.to_datetime(df15.index)
    merged = bias_s.reindex(bias_s.index.union(times15)).ffill().bfill().reindex(times15)
    return merged.to_numpy(dtype=float)


def simulate(df, h1_bias_idx, bias_4h, fast, slow, mom_lb, min_strength, sl_mult, trail_mult, hold_cap_bars, use_4h=False):
    """Getreue Simulation mit H1-Gate (+optional 4H-Konfidenzfilter) + Chandelier-Trailing.

    h1_bias_idx/bias_4h: Arrays (+1/-1/0) je 15m-Zeile (forward-filled aus 1h bzw. 4h).
    use_4h=True: zusätzlich muss der 4H-Bias zur Entry-Richtung passen.
    """
    close = df["Close"].astype(float).to_numpy()
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    atr = atr_series(df, 14).to_numpy()
    fe = ema_np(close, fast)
    se = ema_np(close, slow)

    trades = []
    pos = None
    entry_bar = 0
    n = len(df)
    start = max(fast, slow) + mom_lb
    for i in range(start, n):
        if pos is None:
            cross_now = fe[i] > se[i]
            cross_prev = fe[i - 1] > se[i - 1]
            prev = close[i - mom_lb] if i - mom_lb >= 0 else 0.0
            cur = close[i]
            mom = (cur / prev - 1.0) if prev else 0.0
            a = atr[i]
            if np.isnan(a):
                continue
            h1 = h1_bias_idx[i] if i < len(h1_bias_idx) else 0.0
            h4 = (bias_4h[i] if i < len(bias_4h) else 0.0) if bias_4h is not None else h1

            # LONG: 15m-Kreuz up + Momentum + H1 bullish (+ optional 4H bullish)
            # SHORT: 15m-Kreuz down + Momentum neg + H1 bearish (+ optional 4H bearish)
            if cross_now and not cross_prev and mom > min_strength and h1 == 1 and (not use_4h or h4 == 1):
                pos = {"dir": "LONG", "entry": close[i], "sl": close[i] - sl_mult * a, "extreme": close[i]}
                entry_bar = i
            elif not cross_now and cross_prev and mom < -min_strength and h1 == -1 and (not use_4h or h4 == -1):
                pos = {"dir": "SHORT", "entry": close[i], "sl": close[i] + sl_mult * a, "extreme": close[i]}
                entry_bar = i
        else:
            hi = high[i]
            lo = low[i]
            a = atr[i]
            # Trailing-Stop nachziehen (Chandelier): nie zurückdrehen
            if pos["dir"] == "LONG":
                pos["extreme"] = max(pos["extreme"], hi - trail_mult * a)
                pos["sl"] = max(pos["sl"], pos["extreme"])
            else:
                pos["extreme"] = min(pos["extreme"], lo + trail_mult * a)
                pos["sl"] = min(pos["sl"], pos["extreme"])

            exited = False
            if pos["dir"] == "LONG":
                if lo <= pos["sl"]:
                    trades.append({"entry": pos["entry"], "exit": pos["sl"], "dir": "LONG", "reason": "SL"})
                    exited = True
            else:
                if hi >= pos["sl"]:
                    trades.append({"entry": pos["entry"], "exit": pos["sl"], "dir": "SHORT", "reason": "SL"})
                    exited = True
            if not exited and (i - entry_bar) >= hold_cap_bars:
                # Holding-Cap: am Cap-Candle mit Marktpreis schließen
                trades.append({"entry": pos["entry"], "exit": close[i], "dir": pos["dir"], "reason": "CAP"})
                exited = True
            if exited:
                pos = None
    return trades


def _f(v):
    if hasattr(v, "item"):
        return float(v.item())
    return float(v)


def aggregate(trades, pip_size, spread_pips):
    if not trades:
        return {"trades": 0, "wr": 0.0, "pf": 0.0, "net_pips": 0.0,
                "gross_pips": 0.0, "spread_cost_pips": 0.0}
    pips = []
    for t in trades:
        p = (_f(t["exit"]) - _f(t["entry"])) / pip_size
        if t["dir"] == "SHORT":
            p = -p
        pips.append(p)
    # Spread-Kosten auf Entry UND Exit (netto, live üblich) in pips
    spread_pips_total = 2.0 * spread_pips
    net_with_cost = [p - spread_pips_total for p in pips]
    wins = [p for p in net_with_cost if p > 0]
    losses = [p for p in net_with_cost if p <= 0]
    gross_w = sum(wins)
    gross_l = abs(sum(losses))
    pf = gross_w / gross_l if gross_l else (gross_w if gross_w else 0.0)
    return {"trades": len(trades), "wr": round(len(wins) / len(trades), 3),
            "pf": round(pf, 3), "net_pips": round(sum(net_with_cost), 1),
            "gross_pips": round(sum(pips), 1), "spread_cost_pips": round(spread_pips_total * len(trades), 1)}


def main():
    c = cfg.CONFIG
    wf = c["walk_forward"]
    lookback_days = wf["lookback_weeks"] * 7
    h1_ema = c["signal"]["h1_ema"]
    sl_m = c["sl_tp"]["sl_atr_mult"]
    hold_cap_days = wf["holding_days_cap"]
    hold_cap_bars = hold_cap_days * 4 * 16  # 15m-Bars/trading-day approx
    mom_lb = 8
    min_strength = 0.0002

    configs = [
        ("A: EMA20/50 (H1-Gate)", dict(fast=20, slow=50, trail=1.0, frame4h=False, min_strength=0.0002)),
        ("B: EMA8/21 (H1-Gate)", dict(fast=8, slow=21, trail=1.0, frame4h=False, min_strength=0.0002)),
        ("C: EMA8/21 + 4H-Filter", dict(fast=8, slow=21, trail=1.0, frame4h=True, min_strength=0.0002)),
        ("D: EMA20/50 + 4H-Filter", dict(fast=20, slow=50, trail=1.0, frame4h=True, min_strength=0.0002)),
        ("E: EMA20/50+4H, stärkere Schwelle(0.001)", dict(fast=20, slow=50, trail=1.0, frame4h=True, min_strength=0.001)),
        ("F: EMA20/50+4H, kräftige Schwelle(0.003)", dict(fast=20, slow=50, trail=1.0, frame4h=True, min_strength=0.003)),
        ("G: EMA20/50+4H, Schwelle(0.005)", dict(fast=20, slow=50, trail=1.0, frame4h=True, min_strength=0.005)),
        ("H: EMA20/50+4H, Schwelle(0.008)", dict(fast=20, slow=50, trail=1.0, frame4h=True, min_strength=0.008)),
    ]

    pairs = list(c["pairs"].keys())
    results = {name: {"per_pair": {}, "net_total": 0.0, "trades": 0, "gross_total": 0.0, "spread_total": 0.0} for name, _ in configs}

    print(f"=== TRENDFOLGE COMPARE (Lookback {lookback_days}d, 4H-Filter, Schwelle-Sweep) ===")
    for pair in pairs:
        df15 = fetch_pair(pair, lookback_days, "15m")
        dfh1 = fetch_trend_timeframe(pair, lookback_days, "1h")
        if df15 is None or dfh1 is None or len(df15) < 200:
            print(f"  ❌ {pair}: unzureichende Daten")
            continue
        # 1H- und 4H-Bias je 15m-Zeile (forward-filled)
        bias_1h = _bias_to_15m(bias_series(dfh1, h1_ema), dfh1, df15)
        # fetch 4h
        dfh4 = fetch_trend_timeframe(pair, lookback_days, "4h")
        bias_4h = _bias_to_15m(bias_series(dfh4, h1_ema), dfh4, df15) if dfh4 is not None and len(dfh4) > 5 else None
        pip = c["pairs"][pair]["pip_size"]
        spread = c["pairs"][pair]["spread_pips"]

        for name, cparams in configs:
            trades = simulate(df15, bias_1h, bias_4h, cparams["fast"], cparams["slow"], mom_lb,
                              cparams["min_strength"], sl_m, cparams["trail"], hold_cap_bars,
                              use_4h=cparams["frame4h"])
            agg = aggregate(trades, pip, spread)
            results[name]["per_pair"][pair] = agg
            results[name]["net_total"] += agg["net_pips"]
            results[name]["trades"] += agg["trades"]
            results[name]["gross_total"] += agg["gross_pips"]
            results[name]["spread_total"] += agg["spread_cost_pips"]

    print(f"\n{'Variante':46}{'Trd':>6}{'WR':>7}{'PF':>7}{'net[pps]':>10}{'gross':>9}{'spread':>9}")
    for name, _ in configs:
        r = results[name]
        # Gesamt-WR/PF (gewichtet = gleich wie je Paar summiert, hier grob)
        print(f"{name:46}{r['trades']:>6}{'':>7}{'':>7}{r['net_total']:>10}{r['gross_total']:>9}{r['spread_total']:>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
