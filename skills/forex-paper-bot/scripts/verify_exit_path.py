#!/usr/bin/env python3
"""Echter Exit-Pfad des Forex Paper Bots auf 15 Jahren Tageskerzen — 23.09.2026.

Frage 1: Ist die EMA-Trendfolge mit dem ECHTEN Exit-Pfad (SL 1,0 ATR, TP 2,5 ATR, taeglich nachgezogener
         Trailing-Stop 0,5 ATR, Holding-Cap 20 Tage, Spread auf Entry und Exit) netto profitabel?
         Die frueheren -0,07 % je Trade stammten aus einem festen 5-Tage-Horizont, nicht aus diesem Pfad.
Frage 2: Bringt Jev als Gate (stimmt der Jev-5-Tage-Richtung dem Signal zu?) mit dem echten Pfad etwas?
         (gleiche vorab festgelegte Regel G2 wie im Jev-Probe: n_zustimmend >= 150, untere 98-%-einseitige
         Bootstrap-Grenze der Differenz > 0, Mittel zustimmend > 0.)

Die Simulation ist eine getreue Kopie von backtest.simulate() (dort fehlen Entry-/Exit-Daten) und wird gegen
das Original auf Gleichheit geprueft. Zusaetzlich optional der Cooldown nach Stop-Loss aus trade.py
(cooldown_days_after_loss). NICHT modelliert: Korrelations-Cap (max_correlated_positions), Positionsgroesse,
Drawdown-Stopp. Der Korrelations-Cap kann nur Trades streichen.

Nur lesend. Keine Schreibzugriffe auf forex.db.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import backtest as bt  # noqa: E402

CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
CANDLES = os.path.join(HERE, "reports", "jev_probe", "candles.csv")
JEV = os.path.join(HERE, "reports", "jev_probe", "jev_results.jsonl")
EVAL_FROM = pd.Timestamp("2011-01-01")
JEV_FROM = pd.Timestamp("2016-01-01")
BOOT = 4000
ALPHA = 0.02


def load():
    df = pd.read_csv(CANDLES, parse_dates=["Date"])
    return {p: g.set_index("Date").drop(columns="pair") for p, g in df.groupby("pair")}


def bias_from_daily(df, h1_ema):
    """Trendfilter wie live: Close des laufenden Tages gegen Weekly-EMA. Wegen
    close - (a*close + (1-a)*E_prev) = (1-a)*(close - E_prev) hat der Vergleich dasselbe Vorzeichen wie
    close gegen die EMA der letzten abgeschlossenen Woche (ffill)."""
    c = df["Close"].astype(float)
    wk = c.resample("W-FRI").last().dropna()
    e = wk.ewm(span=h1_ema, adjust=False).mean().reindex(c.index, method="ffill")
    return np.where(c > e, 1, np.where(c < e, -1, 0)).astype(float)


def simulate_dated(df, bias, fast, slow, mom_lb, min_strength, sl_mult, tp_mult, hold_cap_days,
                   trailing_mult=0.0, cooldown_days=0):
    close = df["Close"].astype(float).to_numpy()
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    atr = bt.atr_series(df, 14).to_numpy()
    fe = bt.ema_np(close, fast)
    se = bt.ema_np(close, slow)
    idx = df.index
    trades, pos, last_sl = [], None, None
    start = max(fast, slow) + mom_lb
    for i in range(start, len(df)):
        if pos is None:
            cross_now = fe[i] > se[i]
            cross_prev = fe[i - 1] > se[i - 1]
            prev = close[i - mom_lb] if i - mom_lb >= 0 else 0.0
            mom = (close[i] / prev - 1.0) if prev else 0.0
            a = atr[i] if not np.isnan(atr[i]) else 0.0
            if a <= 0:
                continue
            b = bias[i]
            long_ok = b > 0 and cross_now and (mom > min_strength or not cross_prev)
            short_ok = b < 0 and not cross_now and (mom < -min_strength or cross_prev)
            if cooldown_days and last_sl is not None and (idx[i] - last_sl).days < cooldown_days:
                continue
            if long_ok:
                pos = {"dir": "LONG", "entry": close[i], "entry_i": i, "sl": close[i] - sl_mult * a,
                       "tp": close[i] + tp_mult * a, "risk": sl_mult * a}
            elif short_ok:
                pos = {"dir": "SHORT", "entry": close[i], "entry_i": i, "sl": close[i] + sl_mult * a,
                       "tp": close[i] - tp_mult * a, "risk": sl_mult * a}
        else:
            hi, lo = high[i], low[i]
            held = (idx[i] - idx[pos["entry_i"]]).days if hold_cap_days else 0
            reason = exit_px = None
            if pos["dir"] == "LONG":
                if lo <= pos["sl"]:
                    reason, exit_px = "SL", pos["sl"]
                elif hi >= pos["tp"]:
                    reason, exit_px = "TP", pos["tp"]
                elif hold_cap_days and held >= hold_cap_days:
                    reason, exit_px = "CAP", close[i]
            else:
                if hi >= pos["sl"]:
                    reason, exit_px = "SL", pos["sl"]
                elif lo <= pos["tp"]:
                    reason, exit_px = "TP", pos["tp"]
                elif hold_cap_days and held >= hold_cap_days:
                    reason, exit_px = "CAP", close[i]
            if reason:
                trades.append({"entry": pos["entry"], "exit": exit_px, "dir": pos["dir"], "reason": reason,
                               "entry_date": idx[pos["entry_i"]], "exit_date": idx[i], "risk": pos["risk"]})
                if reason == "SL":
                    last_sl = idx[i]
                pos = None
            elif trailing_mult:
                a = atr[i] if not np.isnan(atr[i]) else 0.0
                if a > 0:
                    dist = trailing_mult * a
                    if pos["dir"] == "LONG":
                        if close[i] - dist > pos["sl"]:
                            pos["sl"] = close[i] - dist
                    else:
                        if close[i] + dist < pos["sl"]:
                            pos["sl"] = close[i] + dist
    return trades


def to_frame(trades, pair):
    pc = CFG["pairs"][pair]
    rows = []
    for t in trades:
        sgn = 1 if t["dir"] == "LONG" else -1
        gross = sgn * (t["exit"] - t["entry"]) / pc["pip_size"]
        net = gross - 2 * pc["spread_pips"]
        rows.append({"pair": pair, "dir": t["dir"], "reason": t["reason"], "entry_date": t["entry_date"],
                     "exit_date": t["exit_date"], "gross": gross, "net": net,
                     "r": net / (t["risk"] / pc["pip_size"])})
    return pd.DataFrame(rows)


def stats(d):
    if d.empty:
        return "keine Trades"
    w, l = d.net[d.net > 0].sum(), -d.net[d.net <= 0].sum()
    eq = d.sort_values("exit_date").net.cumsum()
    dd = (eq.cummax() - eq).max()
    return "n=%4d | Treffer %4.1f %% | PF %.2f | netto %+8.1f Pips | je Trade %+6.2f Pips (%+.3f R) | max. DD %6.1f Pips" % (
        len(d), 100 * (d.net > 0).mean(), w / l if l > 0 else float("inf"), d.net.sum(), d.net.mean(), d.r.mean(), dd)


def boot_mean_ci(x, seed=3):
    rnd = np.random.default_rng(seed)
    x = np.asarray(x, float)
    m = rnd.choice(x, size=(BOOT, len(x))).mean(1)
    return np.quantile(m, 0.025), np.quantile(m, 0.975)


def month_ids(dates):
    keys = sorted({(d.year, d.month) for d in dates})
    k = {a: i for i, a in enumerate(keys)}
    return np.array([k[(d.year, d.month)] for d in dates]), len(keys)


def run_all(candles, cooldown):
    sc = CFG["signal"]
    sl = CFG["sl_tp"]
    cap = CFG["walk_forward"]["holding_days_cap"]
    frames = []
    for p, df in candles.items():
        bias = bias_from_daily(df, sc["h1_ema"])
        tr = simulate_dated(df, bias, sc["ema_fast"], sc["ema_slow"], sc["momentum_lookback"],
                            sc["min_trend_strength"], sl["sl_atr_mult"], sl["tp_atr_mult"], cap,
                            sl["trailing_atr_mult"], cooldown)
        if cooldown == 0:
            ref = bt.simulate(df, bias, sc["ema_fast"], sc["ema_slow"], sc["momentum_lookback"],
                              sc["min_trend_strength"], sl["sl_atr_mult"], sl["tp_atr_mult"], cap,
                              sl["trailing_atr_mult"])
            same = len(ref) == len(tr) and all(
                a["dir"] == b["dir"] and a["reason"] == b["reason"] and abs(a["entry"] - b["entry"]) < 1e-12
                and abs(a["exit"] - b["exit"]) < 1e-12 for a, b in zip(ref, tr))
            print("  Paritaet mit backtest.simulate() %-9s: %s (%d Trades)" % (p, "IDENTISCH" if same else "ABWEICHUNG!", len(tr)))
            if not same:
                sys.exit(1)
        frames.append(to_frame(tr, p))
    return pd.concat(frames, ignore_index=True)


def report(D, title):
    print("\n=== %s ===" % title)
    D = D[D.entry_date >= EVAL_FROM]
    print("Alle Paare, 2011-2026 : " + stats(D))
    print("Nur 2016-2026         : " + stats(D[D.entry_date >= JEV_FROM]))
    mid = D.entry_date.sort_values().iloc[len(D) // 2]
    print("Erste Haelfte (bis %s): %s" % (mid.date(), stats(D[D.entry_date < mid])))
    print("Zweite Haelfte        : " + stats(D[D.entry_date >= mid]))
    lo, hi = boot_mean_ci(D.net)
    print("Mittel je Trade %+.2f Pips, Bootstrap-95%%-KI [%+.2f, %+.2f]" % (D.net.mean(), lo, hi))
    print("Exit-Gruende: " + ", ".join("%s %d (%.0f %%)" % (k, v, 100 * v / len(D)) for k, v in D.reason.value_counts().items()))
    print("Je Paar:")
    for p, g in D.groupby("pair"):
        print("  %-9s %s" % (p, stats(g)))
    print("Je Jahr (netto Pips, Trades):")
    by = D.groupby(D.entry_date.dt.year).agg(n=("net", "size"), pips=("net", "sum"))
    print("  " + " | ".join("%d: %+.0f (%d)" % (y, r.pips, r.n) for y, r in by.iterrows()))
    print("Positive Jahre: %d von %d" % ((by.pips > 0).sum(), len(by)))


def jev_gate(D):
    print("\n=== JEV ALS GATE mit echtem Exit-Pfad (nur Einstiege ab 2016, Regel G2 unveraendert) ===")
    rows = [json.loads(x) for x in open(JEV, encoding="utf-8")]
    ans = {}
    for r in rows:
        if r.get("ok") and not r.get("rep"):
            ans[(r["pair"], r["date"], r["arm"])] = r["ans"]["h5"]["label"]
    Dj = D[D.entry_date >= JEV_FROM]
    print("Trades ab 2016: %d | netto gesamt %+.1f Pips" % (len(Dj), Dj.net.sum()))
    for arm in ("NUM", "TXT"):
        lab = [ans.get((r.pair, str(r.entry_date.date()), arm)) for r in Dj.itertuples()]
        d = Dj.assign(lab=lab).dropna(subset=["lab"])
        agree = ((d.dir == "LONG") == (d.lab == "up")).to_numpy()
        net = d.net.to_numpy()
        blk, m = month_ids(list(d.entry_date))
        ag = agree.astype(float)
        dis = 1 - ag

        def agg(x):
            return np.bincount(blk, weights=x, minlength=m)
        na, da, nd, dd_ = agg(net * ag), agg(ag), agg(net * dis), agg(dis)
        rnd = np.random.default_rng(5)
        ix = rnd.integers(0, m, size=(BOOT, m))
        with np.errstate(divide="ignore", invalid="ignore"):
            v = na[ix].sum(1) / da[ix].sum(1) - nd[ix].sum(1) / dd_[ix].sum(1)
        v = v[np.isfinite(v)]
        pt = net[agree].mean() - net[~agree].mean() if (~agree).any() else float("nan")
        lo = np.quantile(v, ALPHA)
        g2 = agree.sum() >= 150 and lo > 0 and net[agree].mean() > 0
        print("  %s: Trades mit Jev-Antwort %d | zustimmend %d (netto %+.2f Pips/Trade) | widersprechend %d (%+.2f)"
              % (arm, len(d), agree.sum(), net[agree].mean(), (~agree).sum(),
                 net[~agree].mean() if (~agree).any() else float("nan")))
        print("     Differenz %+.2f Pips [untere Grenze %+.2f] | gefilterte Trades: %d, entgangene Netto-Pips %+.1f -> G2 %s"
              % (pt, lo, (~agree).sum(), net[~agree].sum(), "BESTANDEN" if g2 else "verfehlt"))


def main():
    candles = load()
    print("Konfiguration: EMA %d/%d, Momentum %d, min_strength %.4f, SL %.1f ATR, TP %.1f ATR, Trailing %.1f ATR, Cap %d Tage, Weekly-EMA %d"
          % (CFG["signal"]["ema_fast"], CFG["signal"]["ema_slow"], CFG["signal"]["momentum_lookback"],
             CFG["signal"]["min_trend_strength"], CFG["sl_tp"]["sl_atr_mult"], CFG["sl_tp"]["tp_atr_mult"],
             CFG["sl_tp"]["trailing_atr_mult"], CFG["walk_forward"]["holding_days_cap"], CFG["signal"]["h1_ema"]))
    print("Spread je Paar (Pips, Entry+Exit doppelt): " + ", ".join("%s %.1f" % (p, c["spread_pips"]) for p, c in CFG["pairs"].items()))
    D0 = run_all(candles, 0)
    report(D0, "A) Echter Exit-Pfad, wie backtest.simulate() (ohne Cooldown)")
    D3 = run_all(candles, CFG.get("cooldown_days_after_loss", 0))
    report(D3, "B) mit Cooldown nach Stop-Loss (%d Tage, wie trade.py)" % CFG.get("cooldown_days_after_loss", 0))
    jev_gate(D3)


if __name__ == "__main__":
    main()
