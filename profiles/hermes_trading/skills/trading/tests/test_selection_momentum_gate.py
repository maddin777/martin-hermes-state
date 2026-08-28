import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import signal_manager
import utils
import watchlist_manager


class SelectionMomentumGateTests(unittest.TestCase):
    def test_long_requires_bullish_weekly_trend_even_with_high_sentiment(self):
        candidate = {"weekly_trend": "neutral", "tech_direction": "LONG"}
        self.assertEqual(
            signal_manager.entry_gate_reason(
                candidate, "LONG", "AAPL", technical={"weekly_trend": "neutral", "direction": "LONG"},
                liquidity_passed=True, canonical_ticker="AAPL"
            ),
            "momentum-gate",
        )

    def test_short_requires_bearish_weekly_trend_and_short_direction(self):
        for weekly_trend, tech_direction in (("neutral", "SHORT"), ("bullish", "SHORT"), ("bearish", "LONG")):
            with self.subTest(weekly_trend=weekly_trend, tech_direction=tech_direction):
                candidate = {"weekly_trend": weekly_trend, "tech_direction": tech_direction}
                self.assertEqual(
                    signal_manager.entry_gate_reason(
                        candidate, "SHORT", "AAPL",
                        technical={"weekly_trend": weekly_trend, "direction": tech_direction},
                        liquidity_passed=True, canonical_ticker="AAPL"
                    ),
                    "momentum-gate",
                )

    def test_bullish_liquid_long_passes_gate(self):
        candidate = {"weekly_trend": "bullish", "tech_direction": "LONG"}
        self.assertIsNone(
            signal_manager.entry_gate_reason(
                candidate, "LONG", "AAPL", technical={"weekly_trend": "bullish", "direction": "LONG"},
                liquidity_passed=True, canonical_ticker="AAPL"
            )
        )

    def test_unmapped_exotic_or_failed_liquidity_is_blocked(self):
        candidate = {"weekly_trend": "bullish", "tech_direction": "LONG"}
        for ticker, canonical, liquidity in (("ABC.F", "ABC.F", True), ("ABC.MU", "ABC.MU", True),
                                              ("ABC.SG", "ABC.SG", True), ("AAPL", "AAPL", False)):
            with self.subTest(ticker=ticker):
                self.assertEqual(
                    signal_manager.entry_gate_reason(
                        candidate, "LONG", ticker,
                        technical={"weekly_trend": "bullish", "direction": "LONG"},
                        liquidity_passed=liquidity, canonical_ticker=canonical
                    ),
                    "liquidity-gate",
                )

    def test_whitelisted_exotic_mapping_can_pass(self):
        candidate = {"weekly_trend": "bullish", "tech_direction": "LONG"}
        self.assertIsNone(
            signal_manager.entry_gate_reason(
                candidate, "LONG", "YDX.MU",
                technical={"weekly_trend": "bullish", "direction": "LONG"},
                liquidity_passed=True, canonical_ticker="NBIS"
            )
        )

    def test_technical_score_requires_200_bars_and_500k_eur_turnover(self):
        dates_199 = pd.date_range("2025-01-01", periods=199, freq="D")
        short_history = pd.DataFrame({"Close": [100.0] * 199, "Volume": [10_000.0] * 199}, index=dates_199)
        with patch.object(utils, "get_price_data_cached", return_value=(None, None, short_history)):
            self.assertIsNone(utils.get_technical_score("AAPL"))

        dates_200 = pd.date_range("2025-01-01", periods=200, freq="D")
        low_turnover = pd.DataFrame({"Close": [10.0] * 200, "Volume": [1_000.0] * 200}, index=dates_200)
        with patch.object(utils, "get_price_data_cached", return_value=(None, None, low_turnover)), \
                patch.object(utils, "turnover_to_eur", return_value=499_999.0):
            self.assertIsNone(utils.get_technical_score("AAPL"))

    def test_block_reasons_are_persisted_in_blocked_entries(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("""CREATE TABLE blocked_entries (
            ticker TEXT, name TEXT, direction TEXT, gate TEXT,
            blocked_at TEXT, block_date TEXT, price_at_block REAL,
            would_entry REAL, would_sl REAL, would_tp REAL, atr_at_block REAL,
            asset_type TEXT, conviction REAL, tech_score REAL,
            crabel_state TEXT, breakout_level REAL,
            UNIQUE(ticker, direction, block_date, gate)
        )""")
        candidate = {"name": "Fake", "tech_score": 0.99}
        with patch.object(signal_manager, "apply_slippage", return_value=100.0), \
                patch.object(signal_manager, "get_asset_type", return_value="STANDARD"), \
                patch.object(signal_manager, "get_current_regime", return_value=("bull", 0.0)), \
                patch.object(signal_manager, "compute_sl_tp", return_value=(95.0, 110.0)):
            for gate in ("momentum-gate", "liquidity-gate"):
                signal_manager.log_blocked_entry(
                    con, candidate, f"{gate}.TEST", "LONG", gate,
                    100.0, 2.0, "Other", 0.99, None, None,
                )
        self.assertEqual(
            [row[0] for row in con.execute("SELECT gate FROM blocked_entries ORDER BY gate")],
            ["liquidity-gate", "momentum-gate"],
        )

    def test_top_watchlist_contains_only_confirmed_long_momentum(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("""CREATE TABLE watchlist (
            name TEXT, ticker TEXT, status TEXT, conviction_score REAL,
            weekly_trend TEXT, tech_direction TEXT
        )""")
        con.executemany("INSERT INTO watchlist VALUES (?,?,?,?,?,?)", [
            ("Neutral High", "N", "watching", 0.99, "neutral", "LONG"),
            ("Bearish High", "B", "watching", 0.98, "bearish", "SHORT"),
            ("Bullish Lower", "L", "watching", 0.80, "bullish", "LONG"),
        ])
        rows = watchlist_manager.get_top_long_signals(con, limit=10)
        self.assertEqual([row["ticker"] for row in rows], ["L"])


if __name__ == "__main__":
    unittest.main()
