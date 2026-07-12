"""Pydantic models for backtesting results.

Adaptiert aus virattt/ai-hedge-fund v2 (MIT License).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """Eine View eines AlphaModels — Conviction auf einen Ticker zu einem Zeitpunkt.

    Das ist der Output jedes AlphaModels (Quant oder LLM). Der Generator
    ist das AlphaModel; das generierte Objekt ist ein Signal.

    Attributes:
        model_name: Welches AlphaModel, z.B. 'pead', 'screener'
        ticker: Ticker-Symbol
        date: Stichtag der View (YYYY-MM-DD)
        value: Conviction von -1.0 (bearish) bis +1.0 (bullish)
        reasoning: Menschlich lesbare Begründung
        metadata: Zusätzlicher Kontext (z.B. EPS-Surprise)
    """

    model_name: str
    ticker: str
    date: str
    value: float
    reasoning: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Trade(BaseModel):
    """Ein einzelner abgeschlossener Trade — Entry und Exit.

    Attributes:
        ticker: Ticker-Symbol
        direction: "long" oder "short"
        entry_date: Entry-Datum (YYYY-MM-DD)
        exit_date: Exit-Datum (YYYY-MM-DD)
        entry_price: Einstiegskurs
        exit_price: Ausstiegskurs
        shares: Anzahl Aktien
        pnl: Dollar-Gewinn/Verlust
        return_pct: Prozentuale Rendite (signed)
        holding_days: Haltedauer in Handelstagen
        reasoning: Warum der Trade geöffnet wurde
        metadata: Zusätzlicher Kontext (z.B. EPS-Surprise)
    """

    ticker: str
    direction: str  # "long" or "short"
    entry_date: str  # YYYY-MM-DD
    exit_date: str  # YYYY-MM-DD
    entry_price: float
    exit_price: float
    shares: float
    pnl: float
    return_pct: float
    holding_days: int
    reasoning: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PerformanceMetrics(BaseModel):
    """Performance-Kennzahlen eines Backtest-Laufs."""

    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    n_trades: int = 0
    n_long: int = 0
    n_short: int = 0
    avg_return_pct: float = 0.0
    avg_holding_days: float = 0.0


class BacktestResult(BaseModel):
    """Top-Level Ergebnis eines Backtest-Engine-Laufs."""

    trades: list[Trade] = Field(default_factory=list)
    metrics: PerformanceMetrics | None = None
    equity_curve: list[float] = Field(default_factory=list)