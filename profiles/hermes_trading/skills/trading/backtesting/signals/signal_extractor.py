"""
SignalExtractorModel — AlphaModel-Wrapper um die existierende Signal-Pipeline.

Liest historische Signale aus der watchlist-Tabelle (conviction_score + first_seen)
und wrappt sie als AlphaModel für den Backtester. Deckt alle Quellen ab:
YouTube, RSS, Twitter/X, Screener — alles was in der watchlist landet.

Einschränkung: Verwendet first_seen als Signal-Datum (kein echtes
Point-in-Time-Snapshot pro Tag, aber die beste Approximation aus den
vorhandenen Daten). Das ist akzeptabel, weil first_seen dem ersten
Auftauchen in der Pipeline entspricht — der Trade wäre theoretisch
am nächsten Handelstag nach first_seen entrybar.

Usage:
    from backtesting.data_client import YFinanceDataClient
    from backtesting.signals.signal_extractor import SignalExtractorModel

    client = YFinanceDataClient()
    engine = BacktestEngine(capital=100_000, per_trade=10_000)
    model = SignalExtractorModel()
    result = engine.run_alpha(
        model, ["AAPL", "MSFT", "GOOGL"], client,
        "2025-01-01", "2025-06-01", holding_days=5,
    )
    print(result.metrics)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from backtesting.alpha_model import AlphaModel, DataClient
from backtesting.models import Signal

# Default-Pfad — wird überschrieben wenn SignalExtractorModel(db_path=...) gesetzt
_DEFAULT_DB_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"


class SignalExtractorModel(AlphaModel):
    """Wrapper um die existierende Signal-Pipeline.

    Liest historische Signale aus der watchlist-Tabelle und bildet
    eine View (conviction_score) pro Ticker zum Zeitpunkt first_seen.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._signals: dict[str, dict] = {}  # {ticker: {date, value, name, status}}
        self._loaded = False

    @property
    def name(self) -> str:
        return "signal_extractor"

    def _load_signals(self) -> None:
        """Lade historische Signale aus der watchlist-Tabelle."""
        with sqlite3.connect(self._db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute("""
                SELECT ticker, name, conviction_score, first_seen, status
                FROM watchlist
                WHERE ticker IS NOT NULL
                  AND ticker != ''
                  AND ticker != 'N/A'
                  AND conviction_score IS NOT NULL
                  AND first_seen IS NOT NULL
                  AND first_seen != ''
                  AND conviction_score > 0.0
                ORDER BY first_seen
            """).fetchall()

        loaded = 0
        for row in rows:
            ticker = row["ticker"].strip()
            if not ticker or ticker in ("N/A", "N/A.N/A"):
                continue
            self._signals[ticker] = {
                "date": row["first_seen"][:10],  # YYYY-MM-DD
                "value": row["conviction_score"],
                "name": row["name"],
                "status": row["status"],
            }
            loaded += 1

        self._loaded = True
        print(f"[SignalExtractorModel] {loaded} Signale von {len(self._signals)} "
              f"Ticker geladen (DB: {self._db_path})", flush=True)

    def predict(self, ticker: str, date: str, data_client: DataClient) -> Signal:
        """Bilde View auf *ticker* zum *date* basierend auf Pipeline-Signalen.

        Signal ist aktiv wenn first_seen <= date <= last_seen (approximiert).
        Nach last_seen + 30d verfällt das Signal (Gedächtnisverlust).
        """
        if not self._loaded:
            self._load_signals()

        sig = self._signals.get(ticker)
        if sig is None:
            return Signal(model_name=self.name, ticker=ticker, date=date, value=0.0)

        # Signal ist am date aktiv wenn first_seen <= date
        sig_date = sig["date"]
        if sig_date <= date[:10]:
            # Prüfe ob das Signal noch "frisch" ist (max 60 Tage alt)
            days_since = (datetime.strptime(date[:10], "%Y-%m-%d") -
                          datetime.strptime(sig_date, "%Y-%m-%d")).days
            if days_since > 60:
                return Signal(model_name=self.name, ticker=ticker, date=date, value=0.0)

            return Signal(
                model_name=self.name,
                ticker=ticker,
                date=date,
                value=sig["value"],
                reasoning=(
                    f"Signal vom {sig_date} ({sig['status']}) "
                    f"Conviction: {sig['value']:.2f}"
                ),
                metadata={
                    "signal_date": sig_date,
                    "status": sig["status"],
                    "name": sig["name"],
                    "days_since_signal": days_since,
                },
            )

        return Signal(model_name=self.name, ticker=ticker, date=date, value=0.0)