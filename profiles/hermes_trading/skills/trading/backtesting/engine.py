"""Backtesting engine — simuliert Trading von Alpha-Modell-Signalen über Zeit.

Der Engine fragt ein AlphaModel über ein Datumsraster ab, verwandelt seine
Convictions in Trades und berechnet Performance (Return, Sharpe, Drawdown).

WICHTIG — Separation of Concerns:
  - Das AlphaModel bildet *Views* (Conviction in [-1, +1])
  - Dieser Engine owned *Mechanik* (Entry-Timing, Holding-Period, Sizing)
  - Die Mechanik ist bewusst einfach (Threshold + fixed Holding + Equal-Dollar)

Adaptiert aus virattt/ai-hedge-fund v2 (MIT License).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np

from backtesting.alpha_model import AlphaModel, DataClient
from backtesting.models import BacktestResult, PerformanceMetrics, Signal, Trade

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Simuliert Trading eines Alpha-Modells mit Equal-Dollar-Sizing.

    Args:
        capital: Startkapital (Default: 100.000)
        per_trade: Dollar pro Trade (Default: 10.000)
    """

    def __init__(
        self,
        *,
        capital: float = 100_000.0,
        per_trade: float = 10_000.0,
    ) -> None:
        self._capital = capital
        self._per_trade = per_trade

    def run_alpha(
        self,
        model: AlphaModel,
        tickers: list[str],
        data_client: DataClient,
        start_date: str,
        end_date: str,
        *,
        threshold: float = 0.0,
        holding_days: int = 5,
    ) -> BacktestResult:
        """Backteste ein AlphaModel über [start_date, end_date].

        Args:
            model: AlphaModel zum Backtesten (z.B. PEADModel).
            tickers: Universum zum Traden.
            data_client: Daten-Provider.
            start_date: Erstes Auswertungsdatum (YYYY-MM-DD).
            end_date: Letztes Auswertungsdatum (YYYY-MM-DD).
            threshold: Minimale |Conviction| zum Handeln (0.0 = jede View).
            holding_days: Haltedauer in Handelstagen.

        Returns:
            BacktestResult mit Trades, Metriken und Equity-Kurve.
        """
        trades: list[Trade] = []
        for ticker in tickers:
            trades.extend(self._trade_ticker(
                model, ticker, data_client, start_date, end_date,
                threshold=threshold, holding_days=holding_days,
            ))

        if not trades:
            return BacktestResult()

        trades.sort(key=lambda t: t.entry_date)
        equity_curve = self._build_equity_curve(trades)
        metrics = self._compute_metrics(trades, equity_curve)
        return BacktestResult(trades=trades, metrics=metrics, equity_curve=equity_curve)

    # ------------------------------------------------------------------
    # Per-Ticker-Simulation
    # ------------------------------------------------------------------

    def _trade_ticker(
        self,
        model: AlphaModel,
        ticker: str,
        data_client: DataClient,
        start_date: str,
        end_date: str,
        *,
        threshold: float,
        holding_days: int,
    ) -> list[Trade]:
        """Walke einen Ticker durch das Datumsraster und öffne/schließe Positionen."""
        # Preise holen (am Ende gepadded, damit Exits jenseits von end_date
        # noch einen Schlusskurs haben)
        end_padded = (_parse_date(end_date) + timedelta(days=holding_days * 2 + 10)).isoformat()
        today = datetime.now().strftime("%Y-%m-%d")
        if end_padded > today:
            end_padded = today

        prices = data_client.get_prices(ticker, start_date, end_padded)
        if not prices:
            return []

        price_map = {p["time"][:10]: p["close"] for p in prices}
        all_days = sorted(price_map)
        grid = [d for d in all_days if start_date <= d <= end_date]

        trades: list[Trade] = []
        armed = True
        i = 0
        while i < len(grid):
            d = grid[i]
            signal = model.predict(ticker, d, data_client)

            if armed and abs(signal.value) > threshold:
                direction = "long" if signal.value > 0 else "short"
                entry_idx = all_days.index(d)
                exit_idx = entry_idx + holding_days
                if exit_idx >= len(all_days):
                    break
                trade = self._build_trade(
                    ticker, direction, d, all_days[exit_idx],
                    price_map, holding_days, signal.reasoning, dict(signal.metadata),
                )
                if trade is not None:
                    trades.append(trade)
                armed = False
                i = grid.index(all_days[exit_idx]) if all_days[exit_idx] in grid else len(grid)
                continue

            if abs(signal.value) <= threshold:
                armed = True
            i += 1

        return trades

    # ------------------------------------------------------------------
    # Signal -> Trade
    # ------------------------------------------------------------------

    def _build_trade(
        self,
        ticker: str,
        direction: str,
        entry_date: str,
        exit_date: str,
        price_map: dict[str, float],
        holding_days: int,
        reasoning: str | None,
        metadata: dict,
    ) -> Trade | None:
        entry_price = price_map.get(entry_date)
        exit_price = price_map.get(exit_date)
        if entry_price is None or exit_price is None or entry_price <= 0:
            return None

        shares = self._per_trade / entry_price

        if direction == "long":
            pnl = shares * (exit_price - entry_price)
            return_pct = (exit_price - entry_price) / entry_price
        else:
            pnl = shares * (entry_price - exit_price)
            return_pct = (entry_price - exit_price) / entry_price

        return Trade(
            ticker=ticker,
            direction=direction,
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=entry_price,
            exit_price=exit_price,
            shares=round(shares, 4),
            pnl=round(pnl, 2),
            return_pct=round(return_pct, 6),
            holding_days=holding_days,
            reasoning=reasoning,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Equity-Kurve
    # ------------------------------------------------------------------

    def _build_equity_curve(self, trades: list[Trade]) -> list[float]:
        """Portfolio-Wert nach jedem Trade in chronologischer Reihenfolge."""
        equity = self._capital
        curve = [equity]
        for t in trades:
            equity += t.pnl
            curve.append(round(equity, 2))
        return curve

    # ------------------------------------------------------------------
    # Performance-Metriken
    # ------------------------------------------------------------------

    def _compute_metrics(
        self,
        trades: list[Trade],
        equity_curve: list[float],
    ) -> PerformanceMetrics:
        """Berechne Performance-Kennzahlen.

        - Total/Annualized Return: Hat die Strategie Geld verdient?
        - Sharpe Ratio: Ist die Rendite das Risiko wert? (>1.0 = solide)
        - Max Drawdown: Wie schlimm war die grösste Verlustphase?
        - Win Rate: Anteil profitabler Trades
        """
        returns = [t.return_pct for t in trades]
        n = len(returns)

        final_equity = equity_curve[-1]
        total_return_pct = (final_equity - self._capital) / self._capital

        first_entry = _parse_date(trades[0].entry_date)
        last_exit = _parse_date(trades[-1].exit_date)
        calendar_days = (last_exit - first_entry).days
        years = max(calendar_days / 365.25, 0.01)
        annualized = (1 + total_return_pct) ** (1 / years) - 1

        arr = np.array(returns)
        avg = float(arr.mean())
        std = float(arr.std(ddof=1)) if n > 1 else 1.0
        trades_per_year = n / years if years > 0 else n
        sharpe = (avg / std) * np.sqrt(trades_per_year) if std > 0 else 0.0

        peak = equity_curve[0]
        max_dd = 0.0
        for val in equity_curve:
            if val > peak:
                peak = val
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd

        wins = sum(1 for r in returns if r > 0)

        return PerformanceMetrics(
            total_return_pct=round(total_return_pct, 6),
            annualized_return_pct=round(annualized, 6),
            sharpe_ratio=round(sharpe, 4),
            max_drawdown_pct=round(max_dd, 6),
            win_rate=round(wins / n, 4) if n > 0 else 0.0,
            n_trades=n,
            n_long=sum(1 for t in trades if t.direction == "long"),
            n_short=sum(1 for t in trades if t.direction == "short"),
            avg_return_pct=round(avg, 6),
            avg_holding_days=round(sum(t.holding_days for t in trades) / n, 1),
        )


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s[:10], "%Y-%m-%d")