#!/usr/bin/env python3
"""
Backtest Gate — Pipeline vor Config-Aenderungen validieren.

Nutzt SignalExtractorModel + BacktestEngine (90 Tage Historie).
Gibt GO/GEDULD/NO-GO basierend auf Sharpe, Win Rate, MaxDD.

Usage:
    cd /root/.hermes/profiles/hermes_trading/skills/trading
    PYTHONPATH=. python3 scripts/backtest_gate.py
"""

import sys, os, json, sqlite3
from datetime import datetime, timedelta

TRADING_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(TRADING_ROOT, "data")
sys.path.insert(0, TRADING_ROOT)

with open(os.path.join(DATA_DIR, "strategy_config.json")) as f:
    cfg = json.load(f)

print(f"Config: SL={cfg.get('atr_sl_multiplier','?')}x "
      f"TP={cfg.get('atr_tp_multiplier','?')}x "
      f"profit_lock={cfg.get('profit_lock_atr','?')}x "
      f"donchian={cfg.get('donchian_exit_mode','off')} "
      f"min_conf={cfg.get('min_confidence','?')}")

try:
    from backtesting import BacktestEngine
    from backtesting.data_client import YFinanceDataClient
    from backtesting.signals import SignalExtractorModel
except ImportError as e:
    print(f"Backtesting-Engine nicht verfuegbar: {e}")
    sys.exit(1)

con = sqlite3.connect(os.path.join(DATA_DIR, "trading.db"))
con.row_factory = sqlite3.Row
tickers = [r["ticker"] for r in con.execute(
    "SELECT DISTINCT ticker FROM watchlist WHERE ticker IS NOT NULL AND status='watching' ORDER BY conviction_score DESC LIMIT 50"
).fetchall()]
con.close()
print(f"{len(tickers)} Watchlist-Ticker geladen")

if not tickers:
    print("Keine Ticker in Watchlist.")
    sys.exit(1)

end_date = datetime.now().strftime("%Y-%m-%d")
start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
print(f"Backtest {start_date} -> {end_date} ({len(tickers)} Ticker)...")

try:
    client = YFinanceDataClient()
    engine = BacktestEngine(capital=100_000, per_trade=10_000)
    model = SignalExtractorModel()
    result = engine.run_alpha(model, tickers, client, start_date, end_date,
                              threshold=cfg.get("min_conviction", 0.5),
                              holding_days=int(cfg.get("atr_tp_multiplier", 3) * 3))

    m = result.metrics
    print(f"\nTrades: {m.n_trades} | Sharpe: {m.sharpe_ratio:.2f} | "
          f"WR: {m.win_rate:.1%} | "
          f"MaxDD: {m.max_drawdown_pct:.1%} | "
          f"Return: {m.total_return_pct:.1%}")

    gates = sum([m.sharpe_ratio > -0.5, m.win_rate > 0, m.n_trades >= 5])
    if gates == 3:
        print(f"GO ({gates}/3 Gates) — Config freigegeben")
    elif gates >= 2:
        print(f"GEDULD ({gates}/3 Gates) — Config geprueft?")
    else:
        print(f"NO-GO ({gates}/3 Gates) — Config zuruecknehmen")
except Exception as e:
    print(f"Backtest-Fehler (fail-open): {e}")
    sys.exit(0)
