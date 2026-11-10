# Backtesting engine and Backtest-Gate

Engine lives at `skills/trading/backtesting/`, adapted from virattt/ai-hedge-fund v2
(MIT). It validates signals historically before they run in paper trading.

| Modul | Zweck |
|-------|-------|
| `backtesting/__init__.py` | Public API: `BacktestEngine`, `BacktestResult`, `PerformanceMetrics`, `Trade` |
| `backtesting/engine.py` | `BacktestEngine` — Trade-Simulation, Equity-Kurve, Sharpe/MaxDD/WinRate |
| `backtesting/models.py` | Pydantic: `Signal`, `Trade`, `PerformanceMetrics`, `BacktestResult` |
| `backtesting/alpha_model.py` | `AlphaModel` (ABC), `QuantModel` (Base), `DataClient` (Protocol) |
| `backtesting/data_client.py` | `YFinanceDataClient` (inkl. Datums-Monkey-Patch) |
| `backtesting/signals/pead.py` | `PEADModel` — Post-Earnings-Announcement Drift |
| `backtesting/signals/signal_extractor.py` | `SignalExtractorModel` — Wrapper um Pipeline-Signale |

## Usage

```python
from backtesting import BacktestEngine
from backtesting.data_client import YFinanceDataClient
from backtesting.signals import SignalExtractorModel

client = YFinanceDataClient()
engine = BacktestEngine(capital=100_000, per_trade=10_000)
model = SignalExtractorModel()
result = engine.run_alpha(
    model, ["AAPL", "MSFT", "GOOGL"], client,
    "2026-04-01", "2026-07-01",
    threshold=0.5, holding_days=5,
)
print(f"Sharpe: {result.metrics.sharpe_ratio:.2f}")
```

## SignalExtractorModel — caveats

- Reads `conviction_score + first_seen` from `watchlist`; signals expire after 60 days.
- Approximates point-in-time by using `first_seen` as entry date.
- Equal-dollar sizing (10.000 €/trade) on purpose: tests the signal, not portfolio
  construction.

## Backtest-Gate

`scripts/backtest_gate.py` is the standard gate BEFORE any config change. It loads the
Top-50 watchlist tickers, backtests 90 days with `SignalExtractorModel`, and returns
GO / GEDULD / NO-GO based on Sharpe, win rate and trade count. Fail-open on engine
errors.

```bash
cd <trading> && PYTHONPATH=. python3 scripts/backtest_gate.py
```

Gotcha: metric fields are `total_return_pct` and `max_drawdown_pct` (not `total_return` /
`max_drawdown`) — check the schema first. Results from `backtest_variants.py` are only
valid against the current `get_exit_config` matrix + partial-TP; naive 1R/3R simulations
produce artefacts (see `backtest-variants-selection-vs-exit.md`).
