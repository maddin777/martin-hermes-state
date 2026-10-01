"""M7: Benchmark-Alpha im gleichen Zeitfenster (ab Depotstart, nicht ab 1. Januar)."""
import sqlite3
from datetime import datetime

import pandas as pd

from scripts import fundamental_data as fd


def make_db(start="2026-04-25 20:00"):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, total_value REAL)")
    con.execute("INSERT INTO portfolio VALUES (1, 9000.0)")
    con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, entry_date TEXT)")
    con.execute("INSERT INTO positions (entry_date) VALUES (?)", (start,))
    con.execute("INSERT INTO positions (entry_date) VALUES ('2026-06-01 10:00')")
    con.commit()
    return con


def test_portfolio_start_date_is_the_first_entry():
    assert fd.portfolio_start_date(make_db()) == "2026-04-25"
    assert fd.portfolio_start_date(sqlite3.connect(":memory:")) is None


def _df(values):
    return pd.DataFrame({"Close": values}, index=pd.date_range("2026-04-27", periods=len(values), freq="D"))


def test_alpha_uses_the_benchmark_level_at_portfolio_start(monkeypatch):
    calls = []

    def fake_download(symbol, **kw):
        calls.append((symbol, kw))
        if kw.get("period") == "5d":                       # aktueller Stand
            return _df([200.0, 210.0]) if symbol == "SPY" else _df([20000.0, 21000.0])
        if kw.get("start", "").startswith("2026-04"):      # Kurs am Depotstart
            return _df([150.0]) if symbol == "SPY" else _df([19000.0])
        return _df([100.0]) if symbol == "SPY" else _df([18000.0])       # Jahresanfang (alt)

    monkeypatch.setattr(fd.yf, "download", fake_download, raising=False)
    import yfinance
    monkeypatch.setattr(yfinance, "download", fake_download)
    con = make_db()
    fd.update_benchmark(con)
    row = con.execute("SELECT * FROM benchmark ORDER BY date DESC LIMIT 1").fetchone()
    # SPY seit Depotstart: 210/150 - 1 = +40 %  (alt, ab Jahresanfang: +110 %)
    assert abs(row["spy_return_ytd"] - 40.0) < 0.01
    assert abs(row["dax_return_ytd"] - round((21000 / 19000 - 1) * 100, 2)) < 0.01
    assert abs(row["alpha_spy"] - (row["portfolio_return_ytd"] - row["spy_return_ytd"])) < 0.01
    assert any(kw.get("start") == "2026-04-25" for _s, kw in calls)
