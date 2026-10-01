"""M20: factor_ranker ist NaN-sicher, verwirft schlechte Laeufe und rechnet nur Faktoren mit Gewicht."""
import json
import math
import sqlite3

import numpy as np
import pandas as pd
import pytest

from thematic import factor_ranker as fr


def series(n=200, start=100.0, drift=0.001, nan_tail=0):
    vals = [start * (1 + drift) ** i for i in range(n)]
    s = pd.Series(vals, index=pd.date_range("2026-01-01", periods=n, freq="D"))
    if nan_tail:
        s.iloc[-nan_tail:] = float("nan")
    return s


def test_momentum_of_a_nan_series_is_none_not_nan():
    assert fr._compute_momentum_score(pd.Series([float("nan")] * 200)) is None


def test_momentum_ignores_a_trailing_nan_candle():
    with_nan = fr._compute_momentum_score(series(nan_tail=1))
    without_last = fr._compute_momentum_score(series(200)[:-1])
    assert with_nan == pytest.approx(without_last)


def test_momentum_still_needs_enough_history():
    assert fr._compute_momentum_score(series(100)) is None
    assert fr._compute_momentum_score(series(200)) is not None


def test_percentile_treats_nan_like_a_missing_value():
    assert fr._percentile([1.0, float("nan"), 3.0]) == [0.5, 0.5, 1.0]
    assert fr._percentile([float("nan")] * 4) == [0.5] * 4
    assert fr._percentile([None, 2.0, 1.0]) == [0.5, 1.0, 0.5]


# ── Lauf ──────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def run(monkeypatch, tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE factor_scores (date DATE NOT NULL, ticker TEXT NOT NULL, momentum_score REAL,
        quality_score REAL, value_score REAL, revision_score REAL, lowvol_score REAL, composite_score REAL,
        rank_in_universe INTEGER, PRIMARY KEY (date, ticker))""")
    con.commit()
    con.close()
    uni = tmp_path / "universe.json"
    tickers = [f"T{i}" for i in range(10)]
    uni.write_text(json.dumps(tickers))
    monkeypatch.setattr(fr, "DB_PATH", str(db))
    monkeypatch.setattr(fr, "UNIVERSE_PATH", str(uni))
    monkeypatch.setattr(fr, "US_UNIVERSE_PATH", str(tmp_path / "none.csv"))
    monkeypatch.setattr(fr, "_load_config", lambda: {"factor_weights": {"momentum": 0.6, "quality": 0, "value": 0,
                                                                        "revision": 0.15, "lowvol": 0.25}})
    calls = {"quality": 0, "value": 0}

    def q(t):
        calls["quality"] += 1
        return 1.0

    def v(t):
        calls["value"] += 1
        return 1.0

    monkeypatch.setattr(fr, "_compute_quality_score", q)
    monkeypatch.setattr(fr, "_compute_value_score", v)
    monkeypatch.setattr(fr, "_compute_revision_score", lambda t: 0.1)

    def go(price_fn):
        monkeypatch.setattr(fr, "_fetch_price_data", price_fn)
        fr.main()
        con = sqlite3.connect(db)
        rows = con.execute("SELECT ticker, momentum_score FROM factor_scores").fetchall()
        con.close()
        return rows, calls

    return go


def _data(i, nan=False):
    s = series(200, drift=0.0005 * (i + 1), nan_tail=200 if nan else 0)
    return {"close": s, "high": s, "low": s, "volume": s}


def test_normal_run_saves_all_tickers_and_skips_zero_weight_factors(run):
    rows, calls = run(lambda t: _data(int(t[1:])))
    assert len(rows) == 10 and len({m for _, m in rows}) > 1
    assert calls == {"quality": 0, "value": 0}


def test_run_with_all_nan_prices_is_discarded_and_saves_nothing(run):
    rows, _ = run(lambda t: _data(int(t[1:]), nan=True))
    assert rows == []


def test_run_with_too_many_failed_tickers_is_discarded(run):
    rows, _ = run(lambda t: _data(int(t[1:])) if int(t[1:]) < 7 else None)      # 7 von 10 = 70 %
    assert rows == []


def test_run_without_momentum_spread_is_discarded(run):
    same = series(200)
    rows, _ = run(lambda t: {"close": same, "high": same, "low": same, "volume": same})
    assert rows == []
