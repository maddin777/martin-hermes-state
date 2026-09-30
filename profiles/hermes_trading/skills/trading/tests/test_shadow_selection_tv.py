import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import shadow_selection as ss  # noqa: E402
import screener_source  # noqa: E402


def row(name, close=50.0, vol=100_000, hi=52.0, lo=30.0, perf=10.0):
    return {"name": name, "close": close, "average_volume_30d_calc": vol,
            "price_52_week_high": hi, "price_52_week_low": lo, "Perf.3M": perf}


def test_registered_as_hypothesis():
    assert "h_tv_screener" in ss.HYPOTHESES


def test_symbol_mapping_to_yfinance():
    assert ss.tv_to_yf("BRK.B") == "BRK-B"
    assert ss.tv_to_yf(" msft ") == "MSFT"
    assert ss.tv_to_yf("BF/B") == "BF-B"


def test_stage1_splits_long_and_short_pools():
    rows = [row("NEARHIGH", close=50, hi=52, lo=30, perf=10),      # long
            row("NEARLOW", close=33, hi=60, lo=30, perf=-20),      # short (10 % ueber Tief)
            row("MIDDLE", close=40, hi=60, lo=30, perf=0)]         # weder noch
    longs, shorts = ss.tv_stage1(rows, bench_ret=3.0)
    assert longs == ["NEARHIGH"]
    assert shorts == ["NEARLOW"]


def test_stage1_drops_illiquid_cheap_nan_and_weak_longs():
    rows = [row("ILLIQ", vol=1_000),                                # Umsatz 50k $
            row("CHEAP", close=1.5, hi=1.6, lo=1.0, vol=10_000_000),
            row("NANPERF", perf=float("nan")),
            row("BROKEN", close=None),
            row("WEAK", perf=-10.0)]                                # rel -13 < -Slack
    assert ss.tv_stage1(rows, bench_ret=3.0) == ([], [])


def test_stage1_sorts_by_turnover_and_caps(monkeypatch):
    monkeypatch.setattr(ss, "TV_MAX_LONG_POOL", 2)
    rows = [row("A", vol=100_000), row("B", vol=300_000), row("C", vol=200_000)]
    longs, _ = ss.tv_stage1(rows, bench_ret=0.0)
    assert longs == ["B", "C"]


def test_picks_fail_open_when_scanner_down(monkeypatch, capsys):
    def boom():
        raise ConnectionError("403")
    monkeypatch.setattr(ss, "tv_fetch_universe", boom)
    assert ss.tv_screener_picks() == []
    assert "nicht erreichbar" in capsys.readouterr().out


def test_picks_use_screener_stage2_and_top_n(monkeypatch):
    monkeypatch.setattr(ss, "tv_fetch_universe", lambda: [row(f"T{i}") for i in range(8)])
    monkeypatch.setattr(ss, "prefetch_prices", lambda tickers: None)
    monkeypatch.setattr(screener_source, "_current_regime", lambda: ("bull", 15.0, None))
    monkeypatch.setattr(screener_source, "_benchmark_return", lambda lookback: 0.0)
    seen = {}

    def fake_stage2(stage2, channels, p, bench_ret):
        seen["stage2"] = stage2
        longs = [{"ticker": t, "direction": "long", "composite": float(i), "reason": "r",
                  "info": {"shortName": t + " Inc", "sector": "Technology"}}
                 for i, t in enumerate(stage2)]
        return longs, []
    monkeypatch.setattr(screener_source, "screen_stage2", fake_stage2)
    picks = ss.tv_screener_picks(verbose=False)
    assert seen["stage2"] == [f"T{i}" for i in range(8)]
    assert len(picks) == ss.TOP_N
    assert [p["ticker"] for p in picks] == ["T7", "T6", "T5", "T4", "T3"]
    assert picks[0]["direction"] == "LONG" and picks[0]["sector"] == "Technology"
    assert picks[0]["rationale"].startswith("tv: ")


def test_source_health_young_track_alive_stale_track_dead():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE shadow_selection (hypothesis TEXT, select_date TEXT)")
    assert ss._source_health(c, "h_tv_screener")[0] is True
    old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    c.execute("INSERT INTO shadow_selection VALUES ('h_tv_screener', ?)", (old,))
    alive, why = ss._source_health(c, "h_tv_screener")
    assert alive is False and old in why


def test_screener_source_exposes_stage2():
    assert callable(screener_source.screen_stage2)
