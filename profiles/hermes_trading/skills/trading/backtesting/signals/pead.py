"""PEAD alpha model — Post-Earnings Announcement Drift.

Bildet eine View basierend auf Earnings Surprises: bullish nach BEAT,
bearish nach MISS. Theorie: der Markt unterreagiert und die Aktie driftet
tagelang in die Überraschungsrichtung.

Dies ist das Quant-Pendant zu einem LLM-Investor-Agent — gleiches
AlphaModel-Interface, reines Python-Math. Es bildet NUR eine View
(Conviction); der BacktestEngine / Portfolio-Konstruktion entscheidet
über Timing und Sizing.

Datenquelle: yfinance earnings_dates (EPS Estimate vs Reported EPS).
KEINE Paid-API nötig — BEAT/MISS wird selbst berechnet.

Adaptiert aus virattt/ai-hedge-fund v2 (MIT License).
"""

from __future__ import annotations

from datetime import datetime

from backtesting.alpha_model import DataClient, QuantModel
from backtesting.models import Signal

_RETROSPECTIVE_CUTOFF_DAYS = 45
_SOURCE_PRIORITY = {"8-K": 0, "10-Q": 1, "10-K": 2, "20-F": 3}


class PEADModel(QuantModel):
    """Long nach EPS BEAT, short nach MISS.

    predict(ticker, date) gibt ±1.0 zurück wenn ein qualifizierender
    Earnings-Surprise innerhalb von signal_window_days vor date liegt,
    sonst 0.0 (keine View).
    """

    def __init__(
        self,
        *,
        earnings_limit: int = 8,
        signal_window_days: int = 4,
    ) -> None:
        self._earnings_limit = earnings_limit
        self._signal_window_days = signal_window_days
        self._cache: dict[str, list[dict]] = {}

    @property
    def name(self) -> str:
        return "pead"

    def predict(self, ticker: str, date: str, data_client: DataClient) -> Signal:
        as_of = _parse_date(date)
        events = self._qualifying_events(ticker, data_client)

        past = [e for e in events if _parse_date(e["filing_date"]) <= as_of]
        if not past:
            return self._neutral(ticker, date)

        event = max(past, key=lambda e: e["filing_date"])
        filed = _parse_date(event["filing_date"])

        if (as_of - filed).days > self._signal_window_days:
            return self._neutral(ticker, date)

        surprise = event["surprise"]
        value = 1.0 if surprise == "BEAT" else -1.0
        return Signal(
            model_name=self.name,
            ticker=ticker,
            date=date,
            value=value,
            reasoning=(
                f"{surprise} on {event['report_period']} earnings "
                f"(filed {event['filing_date']}, {event['source_type']})"
            ),
            metadata={
                "eps_surprise": surprise,
                "source_type": event["source_type"],
                "report_period": event["report_period"],
                "filing_date": event["filing_date"],
            },
        )

    def _neutral(self, ticker: str, date: str) -> Signal:
        return Signal(model_name=self.name, ticker=ticker, date=date, value=0.0)

    def _qualifying_events(self, ticker: str, data_client: DataClient) -> list[dict]:
        if ticker in self._cache:
            return self._cache[ticker]

        records = data_client.get_earnings_history(ticker, limit=self._earnings_limit)
        if not records:
            self._cache[ticker] = []
            return []

        best: dict[str, tuple[int, dict]] = {}
        for r in records:
            filing_date = r.get("filing_date")
            quarterly = r.get("quarterly", {})
            if not filing_date or not quarterly:
                continue
            surprise = quarterly.get("eps_surprise")
            if surprise not in ("BEAT", "MISS"):
                continue

            lag = (_parse_date(filing_date) - _parse_date(r["report_period"])).days
            if lag >= _RETROSPECTIVE_CUTOFF_DAYS:
                continue

            priority = _SOURCE_PRIORITY.get(r.get("source_type", ""), 99)
            if r["report_period"] not in best or priority < best[r["report_period"]][0]:
                best[r["report_period"]] = (priority, r)

        result = [
            {
                "filing_date": r["filing_date"],
                "report_period": r["report_period"],
                "source_type": r.get("source_type", "10-Q"),
                "surprise": r["quarterly"]["eps_surprise"],
            }
            for _, r in best.values()
        ]
        self._cache[ticker] = result
        return result


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s[:10], "%Y-%m-%d")