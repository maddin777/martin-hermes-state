"""AlphaModel-Interface — die Basis für alle Signal-Quellen im Backtester.

Ein AlphaModel (Rishi Narang, "Inside the Black Box") ist alles was eine
Prognose / View auf ein Asset produziert. Das ist der "Edge"-Teil eines
Quant-Funds.

In unserer Pipeline implementieren sowohl Quant-Signale (PEAD, Screener)
als auch LLM-basierte Signale (Signal Extractor) dieses Interface.

Kern-Prinzip: Das AlphaModel bildet NUR eine View. Es entscheidet NICHT
über Timing, Sizing oder Holding-Period — das ist Aufgabe des BacktestEngine
und später des Portfolio-Konstruktions-Layers.

Adaptiert aus virattt/ai-hedge-fund v2 (MIT License).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

from backtesting.models import Signal


class DataClient(ABC):
    """Daten-Provider für den Backtester.

    Jede Datenquelle (yfinance, Financial Datasets API, etc.) implementiert
    dieses Interface. Der Backtester ist dadurch unabängig von der konkreten
    Datenquelle.
    """

    @abstractmethod
    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """OHLCV-Preise für einen Ticker im Zeitraum."""
        ...

    @abstractmethod
    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 8,
    ) -> list[dict]:
        """Earnings-Historie für PEAD und andere Earnings-Signale.

        Jeder Eintrag: {filing_date, report_period, source_type, quarterly: {eps_surprise}}
        """
        ...


class AlphaModel(ABC):
    """Abstract Base für alle Alpha-Modelle (Quant + LLM)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Modell-Identifikator (z.B. 'pead', 'screener', 'signal_extractor')."""
        ...

    @abstractmethod
    def predict(
        self,
        ticker: str,
        date: str,
        data_client: DataClient,
    ) -> Signal:
        """Bilde eine Point-in-Time View auf *ticker* zum *date*.

        MUSS point-in-time sein: nur Daten mit date <= *date* verwenden
        (kein Lookahead). Rückgabe: Signal mit conviction in [-1, +1].
        0.0 = "keine View" (Enthaltung).
        """
        ...


class QuantModel(AlphaModel):
    """Base für reine Math-Alpha-Modelle (kein LLM).

    Stellt gemeinsame numerische Helfer bereit.
    """

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            f = float(value)
            return default if (np.isnan(f) or np.isinf(f)) else f
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _percentile_rank(value: float, values: list[float]) -> float:
        if not values:
            return 50.0
        below = sum(1 for v in values if v < value)
        return (below / len(values)) * 100.0

    @staticmethod
    def _normalize_to_signal(raw: float, low: float = -1.0, high: float = 1.0) -> float:
        return max(low, min(high, raw))

    @staticmethod
    def _sigmoid(x: float, scale: float = 5.0) -> float:
        return float(np.tanh(x * scale))

    @staticmethod
    def _compute_rsi(prices: pd.Series, period: int = 14) -> float:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        latest = rsi.iloc[-1]
        if pd.isna(latest):
            return 50.0
        return float(latest)