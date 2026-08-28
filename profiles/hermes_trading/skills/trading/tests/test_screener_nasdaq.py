import csv
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import screener_source
import signal_manager
import weekly_strategy_review


class NasdaqScreenerTests(unittest.TestCase):
    def _bars(self, price, volume, count=30):
        index = pd.date_range("2026-01-01", periods=count, freq="D")
        return pd.DataFrame({"Close": [price] * count, "Volume": [volume] * count}, index=index)

    def test_static_universe_is_broad_valid_and_contains_nasdaq_growth(self):
        with (ROOT / "data" / "us_universe.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        tickers = [row["ticker"] for row in rows]
        self.assertGreaterEqual(len(tickers), 550)
        self.assertLessEqual(len(tickers), 650)
        self.assertEqual(len(tickers), len(set(tickers)))
        self.assertTrue({"AAPL", "NVDA", "PLTR", "CRWD"}.issubset(tickers))
        self.assertFalse(any("." in ticker or not ticker for ticker in tickers))

    def test_stage1_fake_5000_is_capped_at_400_without_info_calls(self):
        universe = [f"T{i:04d}" for i in range(5000)]
        bars = self._bars(10.0, 100_000.0)
        with patch.object(screener_source, "prefetch_prices"), \
                patch.object(screener_source, "get_price_data_cached", return_value=(10.0, 1.0, bars)), \
                patch.object(screener_source, "turnover_to_eur", return_value=1_000_000.0), \
                patch.object(screener_source, "_fetch_info") as info:
            survivors = screener_source.stage1_prefilter(universe, limit=400)
        self.assertEqual(len(survivors), 400)
        info.assert_not_called()

    def test_stage1_rejects_low_price_low_turnover_and_missing_data(self):
        frames = {
            "GOOD": (10.0, 1.0, self._bars(10.0, 100_000.0)),
            "PENNY": (1.99, 1.0, self._bars(1.99, 1_000_000.0)),
            "THIN": (10.0, 1.0, self._bars(10.0, 1_000.0)),
            "DEAD": (None, None, None),
        }
        with patch.object(screener_source, "prefetch_prices"), \
                patch.object(screener_source, "get_price_data_cached", side_effect=lambda t: frames[t]), \
                patch.object(screener_source, "turnover_to_eur", side_effect=lambda p, v, t: p * v):
            self.assertEqual(screener_source.stage1_prefilter(list(frames), limit=400), ["GOOD"])

    def test_nasdaq_source_registration_and_mention_channel(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE source_registry (source_type TEXT, source_key TEXT, display_name TEXT, language TEXT, region TEXT, category TEXT, status TEXT, weight REAL, enabled INTEGER, added_by TEXT, discovery_reason TEXT, UNIQUE(source_type, source_key))")
        con.execute("CREATE TABLE watchlist_mentions (name TEXT, channel TEXT, video_id TEXT UNIQUE, video_title TEXT, sentiment TEXT, strength TEXT, reason TEXT, mention_date TEXT)")
        screener_source._register_sources(con)
        source = con.execute("SELECT source_type, display_name FROM source_registry WHERE source_key='screener_nasdaq'").fetchone()
        self.assertEqual(tuple(source), ("screener_nasdaq", "screener_nasdaq"))
        candidate = {"ticker": "PLTR", "channel": "screener_nasdaq", "direction": "long", "strength": "strong", "reason": "test"}
        screener_source._write_mention(con, candidate, "Palantir", "2026-08-27")
        self.assertEqual(con.execute("SELECT channel FROM watchlist_mentions").fetchone()[0], "screener_nasdaq")

    def test_regime_cap_is_shared_across_sources(self):
        candidates = [
            {"ticker": f"A{i}", "direction": "long", "composite": 10 - i, "channel": "screener"}
            for i in range(5)
        ] + [
            {"ticker": f"N{i}", "direction": "long", "composite": 20 - i, "channel": "screener_nasdaq"}
            for i in range(5)
        ]
        selected = screener_source.select_candidates(candidates, {"max_long": 3, "max_short": 2})
        self.assertEqual(len(selected), 3)
        self.assertEqual([c["ticker"] for c in selected], ["N0", "N1", "N2"])

    def test_signal_source_and_weekly_breakdown_keep_nasdaq_separate(self):
        self.assertEqual(signal_manager._derive_signal_source(["screener_nasdaq"]), "screener_nasdaq")
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE positions (signal_source TEXT, pnl_eur REAL, exit_date TEXT)")
        con.executemany("INSERT INTO positions VALUES (?,?,?)", [
            ("screener_nasdaq", 10.0, "2026-08-27"),
            ("screener_nasdaq", -5.0, "2026-08-28"),
            ("screener", 2.0, "2026-08-28"),
        ])
        rows = weekly_strategy_review.compute_source_stats(con)
        self.assertEqual(rows[0]["source"], "screener_nasdaq")
        self.assertEqual(rows[0]["trades"], 2)


if __name__ == "__main__":
    unittest.main()
