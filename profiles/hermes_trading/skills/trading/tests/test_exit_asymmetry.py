import ast
import json
import os
import sys
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from config import DEFAULT_EXIT_CONFIG, _EXIT_CONFIG_MATRIX, get_exit_config
from exit_rules import peak_chandelier_stop, protected_time_stop_price, time_stop_due
from scripts.signal_manager import DEFAULT_CONFIG, compute_sl_tp
from scripts.crabel_shadow_eval import simulate_forward


class ExitAsymmetryTests(unittest.TestCase):
    def test_every_matrix_entry_has_minimum_three_to_one_payoff(self):
        for key, cfg in _EXIT_CONFIG_MATRIX.items():
            with self.subTest(key=key):
                self.assertGreaterEqual(cfg["tp"] / cfg["sl"], 3.0)
        sl, tp = compute_sl_tp(100.0, 2.0, "STANDARD", "LONG", "bull")
        self.assertGreaterEqual((tp - 100.0) / (100.0 - sl), 3.0)

    def test_time_stop_after_seven_weekdays_and_never_beyond_initial_stop(self):
        self.assertFalse(time_stop_due("2026-08-17", 7, date(2026, 8, 25)))
        self.assertTrue(time_stop_due("2026-08-17", 7, date(2026, 8, 26)))
        self.assertEqual(protected_time_stop_price(96.0, 97.0, "LONG"), 97.0)
        self.assertEqual(protected_time_stop_price(104.0, 103.0, "SHORT"), 103.0)

    def test_peak_chandelier_arms_at_one_atr_and_only_ratchets(self):
        unchanged = peak_chandelier_stop(97.0, 100.9, 100.0, 100.0, 1.0,
                                          "LONG", 1.0, 2.0)
        self.assertEqual(unchanged, (97.0, 100.9, False))
        armed = peak_chandelier_stop(97.0, 103.0, 100.9, 100.0, 1.0,
                                      "LONG", 1.0, 2.0)
        self.assertEqual(armed, (101.0, 103.0, True))
        pulled_back = peak_chandelier_stop(101.0, 102.0, 103.0, 100.0, 1.0,
                                            "LONG", 1.0, 2.0)
        self.assertEqual(pulled_back, (101.0, 103.0, True))

    def test_shadow_path_uses_time_stop_not_hard_target(self):
        import pandas as pd
        bars = pd.DataFrame({
            "High": [100.5, 100.7, 100.6, 100.7, 100.8, 100.7, 100.8],
            "Low": [99.5, 99.8, 99.9, 99.8, 99.9, 99.8, 99.9],
            "Close": [100.2, 100.4, 100.3, 100.4, 100.5, 100.4, 100.5],
        })
        outcome, price, days = simulate_forward(
            bars, 100.0, 97.0, 103.0, 1.0, "LONG", "STANDARD", {}, "bull"
        )
        self.assertNotEqual(outcome, "TP_HIT")
        self.assertEqual((outcome, days), ("TIME_STOP", 7))

    def test_profit_lock_single_source(self):
        with open(os.path.join(ROOT, "data", "strategy_config.json")) as f:
            strategy = json.load(f)
        self.assertEqual(strategy["profit_lock_atr"], 1.0)
        self.assertEqual(DEFAULT_CONFIG["profit_lock_atr"], 1.0)
        self.assertEqual(DEFAULT_EXIT_CONFIG["profit_lock_atr"], 1.0)
        self.assertTrue(all(c["profit_lock_atr"] == 1.0
                            for c in _EXIT_CONFIG_MATRIX.values()))

    def test_all_three_paths_import_get_exit_config(self):
        for filename in ("signal_manager.py", "active_exit_check.py", "crabel_shadow_eval.py"):
            with open(os.path.join(ROOT, "scripts", filename)) as f:
                tree = ast.parse(f.read())
            names = {alias.name for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.module == "config"
                     for alias in node.names}
            self.assertIn("get_exit_config", names, filename)


if __name__ == "__main__":
    unittest.main()
