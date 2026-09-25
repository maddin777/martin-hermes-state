import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import dukascopy_data as dd  # noqa: E402

UTC = dt.timezone.utc


def h1_frame(start, hours, price=1.10, spread=0.00008, volume=100.0):
    idx = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    p = price + np.arange(hours) * 0.0001
    df = pd.DataFrame({"bid_open": p, "bid_high": p + 0.0003, "bid_low": p - 0.0003, "bid_close": p + 0.0001,
                       "ask_open": p + spread, "ask_close": p + 0.0001 + spread, "spread": spread, "volume": volume}, index=idx)
    df.index.name = "time"
    return df


def test_trading_day_mapping_puts_weekend_stubs_on_monday():
    idx = pd.DatetimeIndex(["2024-03-01 20:00", "2024-03-01 21:00", "2024-03-03 21:00", "2024-03-03 22:00", "2024-03-04 10:00"], tz="UTC")
    days = trading_days = dd.trading_day(idx)
    assert [d.strftime("%a %H") for d in days[:2]] == ["Fri 00", "Fri 00"] or days[0].dayofweek == 4
    assert days[0].dayofweek == 4 and days[1].dayofweek in (4, 0)            # Fr-Schluss bleibt Freitag (oder Montag bei 21 Uhr im Winter)
    assert days[2].dayofweek == 0 and days[3].dayofweek == 0 and days[4].dayofweek == 0     # Sonntag-Oeffnung -> Montag


def test_daily_from_h1_uses_mid_prices_and_drops_short_old_days():
    df = h1_frame("2024-03-04 22:00", 24 * 3)
    now = dt.datetime(2024, 3, 8, 12, 0, tzinfo=UTC)
    d = dd.daily_from_h1(df, now=now)
    assert len(d) == 3
    first = df.iloc[:24]
    assert abs(d["Close"].iloc[0] - (first["bid_close"].iloc[-1] + first["spread"].iloc[-1] / 2)) < 1e-12
    assert d["High"].iloc[0] == (first["bid_high"] + first["spread"] / 2).max()
    stub = h1_frame("2024-02-05 10:00", 3)
    both = pd.concat([stub, df]).sort_index()
    assert len(dd.daily_from_h1(both, now=now)) == 3                          # kurzer alter Tag faellt weg


def test_running_day_is_kept_even_when_short():
    now = dt.datetime(2024, 3, 6, 9, 0, tzinfo=UTC)
    df = h1_frame("2024-03-04 22:00", 24 + 10)                              # zweiter Tag erst 10 Stunden alt
    d = dd.daily_from_h1(df, now=now)
    assert len(d) == 2 and d.index[-1] == pd.Timestamp("2024-03-06")
    assert len(dd.daily_from_h1(df, keep_running_day=False, now=now)) == 1


def test_weekly_bars_are_labelled_with_friday():
    idx = pd.date_range("2024-03-04", periods=10, freq="B")
    daily = pd.DataFrame({"Open": 1.0, "High": np.arange(10) + 2.0, "Low": 0.5, "Close": np.arange(10) + 1.0}, index=idx)
    w = dd.weekly_from_daily(daily)
    assert list(w.index.dayofweek) == [4, 4] and w["High"].iloc[0] == 6.0 and w["Close"].iloc[0] == 5.0


def test_h1_removes_placeholder_bars_and_serves_fresh_cache_without_network(tmp_path, monkeypatch):
    now = dt.datetime(2024, 3, 6, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(dd, "_now", lambda: now)
    monkeypatch.setattr(dd, "CACHE_DIR", str(tmp_path))
    df = h1_frame("2024-03-05 00:00", 36)
    df.iloc[5, df.columns.get_loc("volume")] = 0
    df.iloc[5, [df.columns.get_loc(c) for c in ("bid_open", "bid_high", "bid_low", "bid_close")]] = 1.10
    df.to_csv(os.path.join(str(tmp_path), "EURUSD_H1.csv"))
    monkeypatch.setattr(dd, "_fetch_h1", lambda *a, **k: pytest.fail("kein Abruf erwartet"))
    out = dd.h1("EURUSD=X")
    assert len(out) == 35


def test_stale_cache_without_network_is_refused_and_fetch_pair_returns_none(tmp_path, monkeypatch):
    now = dt.datetime(2024, 3, 20, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(dd, "_now", lambda: now)
    monkeypatch.setattr(dd, "CACHE_DIR", str(tmp_path))
    h1_frame("2024-03-05 00:00", 36).to_csv(os.path.join(str(tmp_path), "EURUSD_H1.csv"))

    def down(*a, **k):
        raise dd.DataUnavailable("offline")
    monkeypatch.setattr(dd, "_fetch_h1", down)
    with pytest.raises(dd.DataUnavailable):
        dd.h1("EURUSD=X")
    assert dd.fetch_pair("EURUSD=X", 100, "1d") is None
    assert dd.fetch_trend_timeframe("EURUSD=X", 400, "1wk") is None


def test_symbol_mapping():
    assert dd.symbol_of("EURUSD=X") == "EUR/USD" and dd.symbol_of("USDJPY=X") == "USD/JPY"


def test_running_day_close_is_replaced_by_latest_price_and_falls_back_if_quotes_missing(tmp_path, monkeypatch):
    now = dt.datetime(2024, 3, 6, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(dd, "_now", lambda: now)
    monkeypatch.setattr(dd, "CACHE_DIR", str(tmp_path))
    h1_frame("2024-03-04 22:00", 24 + 14).to_csv(os.path.join(str(tmp_path), "EURUSD_H1.csv"))
    r = pd.DataFrame({"mid_close": [1.2345], "mid_high": [1.30], "mid_low": [1.05]}, index=pd.DatetimeIndex(["2024-03-06 12:29"], tz="UTC"))
    monkeypatch.setattr(dd, "_recent_mid", lambda pair, minutes=180: r)
    d = dd.daily("EURUSD=X")
    assert d["Close"].iloc[-1] == 1.2345 and d["High"].iloc[-1] == 1.30 and d["Low"].iloc[-1] == 1.05

    def no_quote(pair, minutes=180):
        raise dd.DataUnavailable("keine Minutenkerzen")
    monkeypatch.setattr(dd, "_recent_mid", no_quote)
    d2 = dd.daily("EURUSD=X")
    assert len(d2) == len(d) - 1                                          # laufender Tag entfaellt statt veraltetem Wert
