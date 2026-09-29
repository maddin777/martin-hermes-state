"""
Backtest-Engine mit OHLC-Pfad-Simulation + Walk-Forward Optimierung.
"""
import sqlite3, json, os, math, yfinance as yf, pandas_ta as ta
from datetime import datetime, timedelta
from statistics import median
from collections import Counter
from config import (DB_PATH, BACKTEST_REPORT_PATH, STRATEGY_CONFIG_PATH, db_connect,
                    get_exit_config, EXIT_PROFILES)
from exit_rules import replay_exit_path
from trade_paths import attach_paths


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
    except Exception:
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
    # Asymmetrie-Kennzahlen (Turtle): Payoff-Ratio × Trefferquote = Erwartungswert.
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else float('inf')
    expectancy   = wr * avg_win - (1 - wr) * avg_loss  # % pro Trade
    # Composite konsistent mit strategy_optimizer.calculate_metrics – bewusst
    # OHNE eigenständigen Win-Rate-Term (Trendfolge-Profil nicht bestrafen):
    #   Expectancy 35% | Payoff 20% | Profit Factor 20% | Sharpe 15% | -MaxDD 10%
    pf_score     = min(pf, 5) / 5
    dd_score     = max(0, 1 - max_dd / 50)
    exp_score    = max(0.0, min(expectancy / 2.0, 1.0))
    payoff_score = 1.0 if payoff_ratio == float('inf') \
                   else max(0.0, min(payoff_ratio / 4.0, 1.0))
    composite = (exp_score * 0.35 + payoff_score * 0.20 + pf_score * 0.20
                 + min(max(sharpe, 0), 3) / 3 * 0.15 + dd_score * 0.10)
    return {
        "total_trades": len(trades), "win_rate": round(wr * 100, 1),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "payoff_ratio": round(payoff_ratio, 2) if payoff_ratio != float('inf') else None,
        "expectancy": round(expectancy, 3),
        "profit_factor": round(pf, 2), "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2), "calmar": round(calmar, 2),
        "max_drawdown": round(max_dd, 2), "total_pnl_pct": round(total_ret, 2),
        "composite": round(composite, 4),
    }

def backtest_params(trades, profile, time_stop_bars, min_conf=None):
    """Pfadgenaue Simulation ueber den gemeinsamen Replay aus exit_rules.

    FIX 18.09.2026, drei Fehler auf einmal:
    1. `min_conf` war ein Pflichtargument, run_grid_search rief aber nur mit
       drei Argumenten auf -> TypeError. Der komplette Walk-Forward-Pfad ist
       deshalb bei jedem Lauf in den except-Zweig von strategy_optimizer
       gefallen ("Walk-Forward Fehler ... Grid Search Fallback"). Default None.
    2. Die alte simulate_trade_with_path lud pro Trade UND pro Grid-Kombination
       neu bei yfinance und benutzte einen festen 1.5x-ATR-Trail statt der
       Exit-Matrix. Jetzt: Bars einmal ueber trade_paths cachen, Exit-Logik aus
       exit_rules — dieselbe Quelle, die auch der Live-Pfad benutzt.
    3. Gesucht wurde ueber atr_sl_multiplier — ein Wert ohne Live-Wirkung.
       Jetzt ueber exit_profile, das den Stop auf der Exit-Matrix skaliert.
    """
    scale = EXIT_PROFILES.get(profile, EXIT_PROFILES["current"])["sl_scale"]
    cfg = load_config()
    donchian_primary = (bool(cfg.get("donchian_exit_enabled"))
                        and cfg.get("donchian_exit_mode") == "primary")
    partial_pct = (cfg.get("partial_tp_pct", 0.5)
                   if cfg.get("partial_tp_enabled", True) else 0.0)
    sim = []
    for t in trades:
        if min_conf is not None and (t.get("confidence") or 0) < min_conf:
            continue
        bars, idx, atr = t.get("_bars"), t.get("_entry_idx"), t.get("_atr")
        entry = t.get("entry_price")
        if not bars or idx is None or not atr or not entry:
            continue          # ohne Pfad keine Aussage
        ex = get_exit_config(asset_type=t.get("asset_type") or "STANDARD",
                             regime="sideways")
        sl_mult = round(ex["sl"] * scale, 2)
        res = replay_exit_path(
            bars, idx, entry, t.get("direction", "LONG"), atr,
            sl_mult=sl_mult,
            partial_atr=ex["partial_atr"],
            partial_pct=partial_pct,
            profit_lock_atr=ex["profit_lock_atr"],
            chandelier_mult=ex["chandelier_mult"],
            donchian_primary=donchian_primary,
            donchian_period=cfg.get("donchian_exit_period", 10),
            time_stop_bars=time_stop_bars,
            tp_mult=None,
        )
        if res["r_multiple"] is None:
            continue
        sim.append({"pnl_pct": res["r_multiple"] * (sl_mult * atr / entry * 100)})
    return sim


def run_grid_search(trades):
    # min_confidence (08.09.2026), atr_tp_multiplier und atr_sl_multiplier
    # (beide 18.09.2026) wurden entfernt: keiner der drei Keys wird vom
    # Live-Pfad gelesen. Gesucht wird ueber exit_profile (skaliert den Stop auf
    # der Exit-Matrix) und time_stop_trading_days.
    best_score, best_params, results = -1, None, []
    for prof in EXIT_PROFILES:
        for ts in [5, 7, 10, 15]:
            sim = backtest_params(trades, prof, ts)
            if len(sim) < 3:
                continue
            m = calculate_metrics(sim)
            if not m:
                continue
            results.append({"profile": prof, "time_stop": ts,
                            "composite": m["composite"], "win_rate": m["win_rate"],
                            "p": m["profit_factor"], "sharpe": m["sharpe"],
                            "trades": len(sim)})
            if m["composite"] > best_score:
                best_score = m["composite"]
                best_params = {"exit_profile": prof, "time_stop_trading_days": ts}
    results.sort(key=lambda x: x["composite"], reverse=True)
    return best_params, results[:5]


def walk_forward_optimize(trades, n_folds=4):
    if len(trades) < n_folds * 5:
        return None
    # Bars EINMAL beschaffen — sonst laedt jede Fold-Kombination neu.
    stats = attach_paths(trades)
    if stats["coverage"] < 0.70:
        print(f"  ⚠ Walk-Forward abgebrochen: Pfad-Abdeckung nur "
              f"{stats['coverage']:.0%} (<70%)", flush=True)
        return None
    trades = [t for t in trades if t.get("_bars")]
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
        test_sim = backtest_params(test, bp["exit_profile"], bp["time_stop_trading_days"])
        tm = calculate_metrics(test_sim)
        oos.append({"fold": i, "train_size": len(train), "test_size": len(test),
                     "params": bp, "oos_metrics": tm})
        print(f"  Fold {i}: WR={tm['win_rate']}% PF={tm['profit_factor']} C={tm['composite']:.4f}", flush=True)
    prof = [r for r in oos if r["oos_metrics"] and r["oos_metrics"]["total_pnl_pct"] > 0]
    if len(prof) >= len(oos) * 0.6:
        return {
            # Profile sind ordinal, nicht metrisch -> Modus statt Median.
            # Bei Gleichstand gewinnt das ENGERE Profil (konservativer).
            "exit_profile": min(
                Counter(r["params"]["exit_profile"] for r in prof).most_common(),
                key=lambda kv: (-kv[1], EXIT_PROFILES[kv[0]]["sl_scale"]))[0],
            "time_stop_trading_days": int(median([r["params"]["time_stop_trading_days"]
                                                  for r in prof])),
        }
    return None

def main():
    print("🔬 Backtester gestartet", flush=True)
    con = db_connect()
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
            print(f"  ✅ WF-Parameter: Profil={new_params['exit_profile']} "
                  f"TimeStop={new_params['time_stop_trading_days']}d", flush=True)
        else:
            print("  ⚠ WF nicht robust – Grid Search Fallback", flush=True)
            attach_paths(trades)
            bp, top5 = run_grid_search([t for t in trades if t.get("_bars")])
            new_params = bp
    else:
        print(f"  Grid Search ({len(trades)} Trades)...", flush=True)
        attach_paths(trades)
        bp, top5 = run_grid_search([t for t in trades if t.get("_bars")])
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
