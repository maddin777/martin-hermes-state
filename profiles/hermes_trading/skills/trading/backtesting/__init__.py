"""Backtesting engine — simulate trading signals over historical data.

Ermöglicht historische Validierung von Alpha-Modellen (Signalen) bevor sie
im Paper-Trading eingesetzt werden. Extrahiert und adaptiert aus
virattt/ai-hedge-fund v2 (MIT License).

Usage:
    from backtesting import BacktestEngine, BacktestResult
    from backtesting.data_client import YFinanceDataClient
    from backtesting.signals import PEADModel

    client = YFinanceDataClient()
    engine = BacktestEngine(capital=100_000, per_trade=10_000)
    model = PEADModel()
    result = engine.run_alpha(
        model, ["AAPL", "MSFT"], client,
        "2024-01-01", "2024-06-01", holding_days=5,
    )
    print(result.metrics)
"""

from backtesting.engine import BacktestEngine
from backtesting.models import BacktestResult, PerformanceMetrics, Trade

__all__ = ["BacktestEngine", "BacktestResult", "PerformanceMetrics", "Trade"]