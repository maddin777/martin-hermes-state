"""yfinance-basierter DataClient für den Backtester.

Erlaubt den BacktestEngine mit yfinance als Datenquelle zu nutzen.
Unterstützt:
- get_prices(): OHLCV-Daten via yfinance
- get_earnings_history(): Earnings-Historie (yfinance liefert eingeschränkte Daten)

Hinweis: yfinance hat keine strukturierten EPS-Surprise-Daten wie die
Financial Datasets API. get_earnings_history() liefert Rohdaten aus
yfinance earnings-dates; für PEAD ist eine externe Quelle nötig.
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from backtesting.alpha_model import DataClient

# ── Monkey-Patch: fix "unconverted data remains" in yfinance/pandas ──
# yfinance wirft ValueError bei Datums-Strings mit Zeitzonen-Suffix.
# Selber Fix wie in fundamental_data.py.
import _strptime as _st
from dateutil import parser as _dp

_orig_st_strptime = _st._strptime

def _safe_strptime(data_string, format="%a %b %d %H:%M:%S %Y"):
    try:
        return _orig_st_strptime(data_string, format)
    except ValueError as e:
        if "unconverted data remains" in str(e):
            try:
                parsed = _dp.parse(data_string)
                tt_base = tuple(parsed.timetuple())
                tzname = parsed.tzname()
                gmtoff = int(parsed.utcoffset().total_seconds()) if parsed.tzinfo else None
                return tt_base + (tzname, gmtoff), parsed.microsecond, 0
            except Exception:
                pass
        raise

_st._strptime = _safe_strptime
# ──────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


class YFinanceDataClient(DataClient):
    """yfinance-basierter Daten-Provider für den Backtester.

    Implementiert das DataClient-Interface mit yfinance als Backend.
    Ideal für Preis-basierte Backtests (Technicals, Momentum, Screener).
    """

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """OHLCV-Preise via yfinance.

        Returns:
            Liste von Dictionaries: {time, open, high, low, close, volume}
        """
        try:
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if df.empty:
                return []

            # yfinance returns multi-index columns in newer versions
            if isinstance(df.columns, pd.MultiIndex):
                df = df.droplevel(1, axis=1)

            prices = []
            for idx, row in df.iterrows():
                prices.append({
                    "time": idx.strftime("%Y-%m-%d"),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                })
            return prices
        except Exception as e:
            logger.warning("yfinance get_prices fehlgeschlagen für %s: %s", ticker, e)
            return []

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 8,
    ) -> list[dict]:
        """Earnings-Historie via yfinance.

        Berechnet BEAT/MISS selbst aus EPS Estimate vs Reported EPS.
        Keine Paid-API nötig — yfinance liefert die Rohdaten.

        Returns:
            Liste von dicts: {filing_date, report_period, source_type,
                              quarterly: {eps_surprise, eps_actual, eps_estimate}}
        """
        try:
            ticker_obj = yf.Ticker(ticker)
            earnings = ticker_obj.earnings_dates
            if earnings is None or earnings.empty:
                return []

            # yfinance liefert: 'EPS Estimate', 'Reported EPS', 'Surprise(%)'
            # Spaltennamen können variieren — finde die richtigen
            col_map = {}
            for col in earnings.columns:
                cl = col.lower()
                if 'estimate' in cl:
                    col_map['estimate'] = col
                elif 'reported' in cl or 'actual' in cl:
                    col_map['actual'] = col

            records = []
            for idx, row in earnings.head(limit).iterrows():
                eps_estimate = row.get(col_map.get('estimate'))
                eps_actual = row.get(col_map.get('actual'))
                surprise = None
                if eps_estimate is not None and eps_actual is not None:
                    try:
                        est = float(eps_estimate)
                        act = float(eps_actual)
                        if pd.notna(est) and pd.notna(act):
                            diff = act - est
                            surprise = "BEAT" if diff > 0 else "MISS" if diff < 0 else "NEUTRAL"
                    except (ValueError, TypeError):
                        pass

                filing_date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]

                records.append({
                    "filing_date": filing_date,
                    "report_period": filing_date,
                    "source_type": "10-Q",
                    "quarterly": {
                        "eps_surprise": surprise,
                        "eps_actual": float(eps_actual) if eps_actual is not None and pd.notna(eps_actual) else None,
                        "eps_estimate": float(eps_estimate) if eps_estimate is not None and pd.notna(eps_estimate) else None,
                    },
                })
            return records
        except Exception as e:
            logger.warning("yfinance get_earnings_history fehlgeschlagen für %s: %s", ticker, e)
            return []