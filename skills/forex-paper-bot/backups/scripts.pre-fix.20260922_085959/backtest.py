"""
backtest.py — Walk-Forward-Optimierung für den Forex-Paper-Bot.

Nutzung:
  python3 backtest.py --dry-run       # optimiert alle Paare, schreibt Param-Snapshots (keine Trades)
  python3 backtest.py --pair EURUSD=X # nur ein Paar

Walk-Forward-Logik:
  - Lookback: letzte N Wochen (config: walk_forward.lookback_weeks, Default 8)
  - Optimiert die Signal-Parameter (ema_fast, ema_slow, momentum_lookback, min_trend_strength,
    sl_atr_mult, tp_atr_mult) durch Grid-Search über das Lookback-Fenster
  - Bewertung nach kombiniertem Score: Profit-Faktor (Haupt) + Win-Rate + Sharpe
  - Beste Paramgruppe pro Paar wird als Param-Snapshot gespeichert (für trade.py)
"""
import argparse
import itertools
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair, _scalar
from forex_signal import ema

import pandas as pd
import numpy as np


# Grid der zu optimierenden Parameter (SF: numpy-Vektorisierung, Laufzeit ~ok)
FAST_GRID = [10, 20, 30]
SLOW_GRID = [30, 50, 80]
MOM_GRID = [5, 8, 12]
SL_GRID = [1.2, 2.0]
TP_GRID = [2.5, 3.5]


def _sharpe(rets):
    rets = np.array(rets, dtype=float)
    if len(rets) == 0 or rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(252 * 4))


def atr_series(df, n=14):
    """Vektorisierte ATR-Berechnung. Liefert pd.Series."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def ema_np(arr, span):
    """EWMA als numpy-Array."""
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def simulate(df, fast, slow, mom_lb, min_strength, sl_mult, tp_mult):
    """Simuliert Trendfolge auf 15m-Daten. Liefert Trade-Liste (dicts) und Metriken.
    Intern numpy-Arrays für Geschwindigkeit."""
    close = df["Close"].astype(float).to_numpy()
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    atr = atr_series(df, 14).to_numpy()
    fe = ema_np(close, fast)   # EMA fast
    sl = ema_np(close, slow)   # EMA slow
    # Kreuz = fast_EMA über/unter slow_EMA (konsistent mit forex_signal.py)

    trades = []
    pos = None
    n = len(df)
    start = max(fast, slow) + mom_lb
    for i in range(start, n):
        if pos is None:
            cross_now = fe[i] > sl[i]
            cross_prev = fe[i - 1] > sl[i - 1]
            prev = close[i - mom_lb] if i - mom_lb >= 0 else 0.0
            cur = close[i]
            mom = (cur / prev - 1.0) if prev else 0.0
            a = atr[i] if not (np.isnan(atr[i])) else 0.0

            if cross_now and not cross_prev and mom > min_strength:
                pos = {"dir": "LONG", "entry": close[i],
                       "sl": close[i] - sl_mult * a, "tp": close[i] + tp_mult * a}
            elif not cross_now and cross_prev and mom < -min_strength:
                pos = {"dir": "SHORT", "entry": close[i],
                       "sl": close[i] + sl_mult * a, "tp": close[i] - tp_mult * a}
        else:
            hi = high[i]
            lo = low[i]
            if pos["dir"] == "LONG":
                if lo <= pos["sl"]:
                    trades.append({"entry": pos["entry"], "exit": pos["sl"], "dir": "LONG", "reason": "SL"})
                    pos = None
                elif hi >= pos["tp"]:
                    trades.append({"entry": pos["entry"], "exit": pos["tp"], "dir": "LONG", "reason": "TP"})
                    pos = None
            else:
                if hi >= pos["sl"]:
                    trades.append({"entry": pos["entry"], "exit": pos["sl"], "dir": "SHORT", "reason": "SL"})
                    pos = None
                elif lo <= pos["tp"]:
                    trades.append({"entry": pos["entry"], "exit": pos["tp"], "dir": "SHORT", "reason": "TP"})
                    pos = None
    return trades


def _npf(v):
    """Robust zu Python-float: numpy-Skalare → float."""
    if hasattr(v, "item"):
        return float(v.item())
    return float(v)


def score_trades(trades):
    """Bewertung: kombinierter Score aus Profit-Faktor + Win-Rate + Sharpe."""
    if not trades:
        return 0.0, {"trades": 0, "pf": 0.0, "wr": 0.0, "sharpe": 0.0, "net": 0.0}
    wins = [abs(_npf(t["exit"]) - _npf(t["entry"])) for t in trades if
            (t["dir"] == "LONG" and t["exit"] > t["entry"]) or (t["dir"] == "SHORT" and t["exit"] < t["entry"])]
    losses = [abs(_npf(t["exit"]) - _npf(t["entry"])) for t in trades if
              (t["dir"] == "LONG" and t["exit"] <= t["entry"]) or (t["dir"] == "SHORT" and t["exit"] >= t["entry"])]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0)
    wr = len(wins) / len(trades)
    rets = [(_npf(t["exit"]) - _npf(t["entry"])) * (1 if t["dir"] == "LONG" else -1) for t in trades]
    sharpe = _sharpe(rets)
    net = sum(rets)
    # Score: PF dominiert, bestraft zu wenig Trades
    score = _npf(pf) * 0.5 + wr * 0.2 + max(0.0, sharpe) * 0.3
    if len(trades) < 5:
        score *= 0.5  # zu wenige Trades = geringe Konfidenz
    return score, {"trades": len(trades), "pf": round(_npf(pf), 3), "wr": round(wr, 3),
                   "sharpe": round(sharpe, 2), "net": round(net, 5)}


def optimize_pair(pair, lookback_days):
    """Grid-Search über Lookback-Fenster, liefert beste Paramgruppe + Metriken."""
    df = fetch_pair(pair, lookback_days, "15m")
    if df is None or len(df) < 200:
        return None

    best = None
    best_score = -1.0
    for fast, slow, mom_lb, sl_m, tp_m in itertools.product(FAST_GRID, SLOW_GRID, MOM_GRID, SL_GRID, TP_GRID):
        if slow <= fast:
            continue
        trades = simulate(df, fast, slow, mom_lb, 0.0002, sl_m, tp_m)
        score, metrics = score_trades(trades)
        if score > best_score:
            best_score = score
            best = {"ema_fast": fast, "ema_slow": slow, "momentum_lookback": mom_lb,
                    "min_trend_strength": 0.0002, "sl_atr_mult": sl_m, "tp_atr_mult": tp_m}
            best_metrics = metrics
    return {"params": best, "score": round(best_score, 4), "metrics": best_metrics}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pair")
    args = ap.parse_args()

    c = cfg.CONFIG
    wf = c["walk_forward"]
    lookback_days = wf["lookback_weeks"] * 7

    pairs = [args.pair] if args.pair else list(c["pairs"].keys())
    con = cfg.db_connect()
    cfg.init_db(con)

    print(f"=== Walk-Forward-Optimierung ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    print(f"Lookback: {lookback_days} Tage, Grid: {len(FAST_GRID)*len(SLOW_GRID)*len(MOM_GRID)*len(SL_GRID)*len(TP_GRID)} Kombis\n")

    for pair in pairs:
        res = optimize_pair(pair, lookback_days)
        if res is None:
            print(f"  ❌ {pair}: keine Daten")
            continue
        # Param-Snapshot speichern
        con.execute(
            "INSERT INTO params_snapshots (created_at, pair, params_json, lookback_weeks, metric_name, metric_value, note) "
            "VALUES (?, ?, ?, ?, 'combined_score', ?, ?)",
            (datetime.now().isoformat(), pair, json.dumps(res["params"]), wf["lookback_weeks"],
             res["score"], f"PF={res['metrics']['pf']}, WR={res['metrics']['wr']}, Sharpe={res['metrics']['sharpe']}, Trades={res['metrics']['trades']}")
        )
        print(f"  ✅ {pair:10} score={res['score']:.3f} | {res['metrics']}")
        print(f"       params={res['params']}")
    con.commit()
    con.close()
    print("\n✅ Walk-Forward abgeschlossen. Param-Snapshots gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
