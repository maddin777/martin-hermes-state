"""
Backtest-Engine mit OHLC-Pfad-Simulation + Walk-Forward Optimierung.
"""
import sqlite3, json, os, math, yfinance as yf, pandas_ta as ta
from datetime import datetime, timedelta
from statistics import median
from config import DB_PATH, BACKTEST_REPORT_PATH


def load_config():
    if os.path.exists(STRATEGY_CONFIG_PATH):
        with open(STRATEGY_CONFIG_PATH) as f:
            return json.load(f)
    return {}

def simulate_trade_with_path(entry_price, direction, sl, tp, ticker, entry_date, atr, max_days=30, sl_multiplier=1.5):
    """Simuliert einen Trade mit echten OHLC-Daten. Returns: (exit_price, exit_date, exit_reason, pnl_pct)"""
    try:
        df = yf.download(ticker, start=entry_date, period=f"{max_days+5}d",
                         interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 2:
            return entry_price, entry_date, "NO_DATA", 0.0
        current_sl = sl
        highest = entry_price
        lowest = entry_price
        for i, (date, row) in enumerate(df.iterrows()):
            if i == 0:
                continue
            hv = float(row["High"].iloc[0]) if hasattr(row["High"], "iloc") else float(row["High"])
            lv = float(row["Low"].iloc[0]) if hasattr(row["Low"], "iloc") else float(row["Low"])
            cv = float(row["Close"].iloc[0]) if hasattr(row["Close"], "iloc") else float(row["Close"])
            if direction == "LONG":
                if lv <= current_sl:
                    pnl = (current_sl - entry_price) / entry_price * 100
                    return current_sl, str(date)[:10], "SL_HIT", pnl
                if hv >= tp:
                    pnl = (tp - entry_price) / entry_price * 100
                    return tp, str(date)[:10], "TARGET_HIT", pnl
                if hv > highest:
                    highest = hv
                    new_sl = highest - (sl_multiplier * atr)
                    if new_sl > current_sl:
                        current_sl = new_sl
            elif direction == "SHORT":
                if hv >= current_sl:
                    pnl = (entry_price - current_sl) / entry_price * 100
                    return current_sl, str(date)[:10], "SL_HIT", pnl
                if lv <= tp:
                    pnl = (entry_price - tp) / entry_price * 100
                    return tp, str(date)[:10], "TARGET_HIT", pnl
                if lv < lowest:
                    lowest = lv
                    new_sl = lowest + (sl_multiplier * atr)
                    if new_sl < current_sl:
                        current_sl = new_sl
        final = float(df["Close"].iloc[-1])
        pnl = ((final - entry_price) / entry_price * 100) if direction == "LONG" \
              else ((entry_price - final) / entry_price * 100)
        return final, str(df.index[-1])[:10], "MAX_HOLD", pnl
    except:
        return entry_price, entry_date, "ERROR", 0.0

def calculate_metrics(trades):
    if not trades:
        return None
    pnls = [t.get("pnl_pct", 0) or 0 for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / len(pnls) if pnls else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.001
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
    if len(pnls) > 1:
        m = sum(pnls) / len(pnls)
        var = sum((p - m)**2 for p in pnls) / len(pnls)
        std = math.sqrt(var) if var > 0 else 0.001
        sharpe = (m / std) * math.sqrt(252) if std > 0 else 0
        downside = [p for p in pnls if p < 0]
        if downside:
            dstd = math.sqrt(sum(p**2 for p in downside) / len(pnls))
            sortino = (m / dstd) * math.sqrt(252) if dstd > 0 else 0
        else:
            sortino = 0
    else:
        sharpe = sortino = 0
    equity, peak, max_dd = 10000.0, 10000.0, 0
    for p in pnls:
        equity *= (1 + p / 100)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
    total_ret = (equity - 10000) / 10000 * 100
    calmar = total_ret / max_dd if max_dd > 0 else 0
    pf_score = min(pf, 5) / 5
    dd_score = max(0, 1 - max_dd / 50)
    composite = wr * 0.30 + pf_score * 0.30 + min(max(sharpe, 0), 3) / 3 * 0.25 + dd_score * 0.15
    return {
        "total_trades": len(trades), "win_rate": round(wr * 100, 1),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "profit_factor": round(pf, 2), "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2), "calmar": round(calmar, 2),
        "max_drawdown": round(max_dd, 2), "total_pnl_pct": round(total_ret, 2),
        "composite": round(composite, 4),
    }

def backtest_params(trades, sl_mult, tp_mult, min_conf):
    sim = []
    for t in trades:
        conf = t.get("confidence") or 0
        if conf < min_conf:
            continue
        atr = t.get("atr_at_entry")
        entry = t.get("entry_price")
        if not atr or not entry or atr == 0:
            sim.append({"pnl_pct": t.get("pnl_pct") or 0})
            continue
        direction = t.get("direction", "LONG")
        sl = (entry - sl_mult * atr) if direction == "LONG" else (entry + sl_mult * atr)
        tp = (entry + tp_mult * atr) if direction == "LONG" else (entry - tp_mult * atr)
        result = simulate_trade_with_path(entry, direction, sl, tp, t["ticker"], t["entry_date"], atr)
        sim.append({"pnl_pct": result[3]})
    return sim

def run_grid_search(trades):
    best_score, best_params, results = -1, None, []
    for sl in [1.0, 1.25, 1.5, 1.75, 2.0, 2.5]:
        for tp in [2.0, 2.5, 3.0, 3.5, 4.0]:
            for conf in [0.55, 0.60, 0.65, 0.70, 0.75]:
                if tp / sl < 1.5:
                    continue
                sim = backtest_params(trades, sl, tp, conf)
                if len(sim) < 3:
                    continue
                m = calculate_metrics(sim)
                if not m:
                    continue
                results.append({"sl": sl, "tp": tp, "con": conf, "composite": m["composite"],
                                "win_rate": m["win_rate"], "p": m["profit_factor"],
                                "sharpe": m["sharpe"], "trades": len(sim)})
                if m["composite"] > best_score:
                    best_score = m["composite"]
                    best_params = {"atr_sl_multiplier": sl, "atr_tp_multiplier": tp,
                                   "min_confidence": conf}
    results.sort(key=lambda x: x["composite"], reverse=True)
    return best_params, results[:5]

def walk_forward_optimize(trades, n_folds=4):
    if len(trades) < n_folds * 5:
        return None
    fold_size = len(trades) // n_folds
    oos = []
    for i in range(1, n_folds):
        train = trades[:i * fold_size]
        test = trades[i * fold_size:(i + 1) * fold_size]
        if len(train) < 10 or len(test) < 3:
            continue
        bp, _ = run_grid_search(train)
        if not bp:
            continue
        test_sim = backtest_params(test, bp["atr_sl_multiplier"], bp["atr_tp_multiplier"], bp["min_confidence"])
        tm = calculate_metrics(test_sim)
        oos.append({"fold": i, "train_size": len(train), "test_size": len(test),
                     "params": bp, "oos_metrics": tm})
        print(f"  Fold {i}: WR={tm['win_rate']}% PF={tm['profit_factor']} C={tm['composite']:.4f}", flush=True)
    prof = [r for r in oos if r["oos_metrics"] and r["oos_metrics"]["total_pnl_pct"] > 0]
    if len(prof) >= len(oos) * 0.6:
        return {
            "atr_sl_multiplier": median([r["params"]["atr_sl_multiplier"] for r in prof]),
            "atr_tp_multiplier": median([r["params"]["atr_tp_multiplier"] for r in prof]),
            "min_confidence": median([r["params"]["min_confidence"] for r in prof]),
        }
    return None

def main():
    print("🔬 Backtester gestartet", flush=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    trades = [dict(t) for t in con.execute(
        "SELECT * FROM positions WHERE status='closed' ORDER BY entry_date ASC"
    ).fetchall()]
    con.close()
    print(f"  Trades: {len(trades)}", flush=True)
    if len(trades) < 10:
        print("  ⚠ Zu wenige Trades (min. 10)")
        return

    current = calculate_metrics(trades)
    print(f"  Aktuell: WR={current['win_rate']}% PF={current['profit_factor']} C={current['composite']:.4f}", flush=True)

    if len(trades) >= 30:
        print("  Walk-Forward Optimierung (4 Folds)...", flush=True)
        new_params = walk_forward_optimize(trades, n_folds=4)
        if new_params:
            print(f"  ✅ WF-Parameter: SL={new_params['atr_sl_multiplier']}x TP={new_params['atr_tp_multiplier']}x Conf={new_params['min_confidence']:.0%}", flush=True)
        else:
            print("  ⚠ WF nicht robust – Grid Search Fallback", flush=True)
            bp, top5 = run_grid_search(trades)
            new_params = bp
    else:
        print(f"  Grid Search ({len(trades)} Trades)...", flush=True)
        bp, top5 = run_grid_search(trades)
        new_params = bp

    report = {
        "run_date": datetime.now().isoformat(),
        "total_trades": len(trades),
        "current_metrics": current,
        "optimized_params": new_params,
    }
    with open(BACKTEST_REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  Report → {BACKTEST_REPORT_PATH}", flush=True)
    print("✅ Backtester abgeschlossen", flush=True)

if __name__ == "__main__":
    main()
