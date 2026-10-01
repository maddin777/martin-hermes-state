"""K1b: Wiedereinstieg nach der Notbremse mit neuem Referenzwert (Entscheidung Martin, 30.09.2026).

Nach close_all besteht das Depot nur aus Cash; der Drawdown vom alten ATH bleibt >= 25 % und der
Agent wuerde nie wieder handeln. Nach Ablauf des Cooldowns wird das ATH auf den aktuellen Depotwert gesetzt.
"""
import os
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from scripts import signal_manager as sm

OLD_ATH = 11207.85


def _make_db(cash=7863.0):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE watchlist (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT, conviction_score REAL)")
    sm.init_db(con)
    con.execute("DELETE FROM portfolio")
    con.execute("INSERT INTO portfolio (id, cash, total_value, ath_value) VALUES (1, ?, ?, ?)",
                (cash, cash, OLD_ATH))
    con.commit()
    return con


def _cfg(days_ago):
    d = None if days_ago is None else (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {"drawdown_close_all_date": d, "drawdown_cooldown_days": 7}


def _ath(con):
    return con.execute("SELECT ath_value, total_value FROM portfolio WHERE id=1").fetchone()


class ResetReferenceTests(unittest.TestCase):
    def _run(self, con, cfg):
        with mock.patch.object(sm, "save_config") as save, mock.patch.object(sm, "send_telegram") as tg:
            result = sm._maybe_reset_drawdown_reference(con, cfg)
        return result, save, tg

    def test_without_date_the_cooldown_starts(self):
        con, cfg = _make_db(), _cfg(None)
        result, save, tg = self._run(con, cfg)
        self.assertFalse(result)
        self.assertIsNotNone(cfg["drawdown_close_all_date"])
        save.assert_called_once()
        tg.assert_not_called()
        self.assertEqual(_ath(con)["ath_value"], OLD_ATH)

    def test_running_cooldown_changes_nothing(self):
        con, cfg = _make_db(), _cfg(3)
        result, save, tg = self._run(con, cfg)
        self.assertFalse(result)
        save.assert_not_called()
        tg.assert_not_called()
        self.assertEqual(_ath(con)["ath_value"], OLD_ATH)

    def test_expired_cooldown_resets_reference_to_current_value(self):
        con, cfg = _make_db(cash=7863.0), _cfg(8)
        result, save, tg = self._run(con, cfg)
        self.assertTrue(result)
        row = _ath(con)
        self.assertAlmostEqual(row["ath_value"], 7863.0, places=2)
        self.assertAlmostEqual(row["total_value"], 7863.0, places=2)
        self.assertIsNone(cfg["drawdown_close_all_date"])
        self.assertEqual(cfg["drawdown_ath_before_reset"], OLD_ATH)
        self.assertIn("drawdown_reference_reset_date", cfg)
        save.assert_called_once()
        tg.assert_called_once()
        dd, action, _ = sm.check_drawdown(con)
        self.assertEqual(action, "ok")
        self.assertAlmostEqual(dd, 0.0, places=4)


class EntryLoopReentryTests(unittest.TestCase):
    CLOSE_ALL = (0.30, "close_all", {"size_factor": 0.0, "min_confidence": 1.0, "max_positions": 0})
    OK = (0.0, "ok", {"size_factor": 1.0, "min_confidence": 0.70, "max_positions": 8})

    def _run(self, cfg, side_effect):
        con = _make_db()
        with mock.patch.object(sm, "check_drawdown", side_effect=side_effect) as cd, \
             mock.patch.object(sm, "_emergency_close_all") as close_all, \
             mock.patch.object(sm, "save_config"), mock.patch.object(sm, "send_telegram"), \
             mock.patch.object(sm, "get_macro_signal", side_effect=RuntimeError("weiter")) as macro:
            try:
                sm.open_new_positions(con, cfg)
                continued = False
            except RuntimeError:
                continued = True
        return continued, cd, close_all, macro

    def test_after_expired_cooldown_the_entry_loop_continues_normally(self):
        continued, cd, close_all, macro = self._run(_cfg(8), [self.CLOSE_ALL, self.OK])
        self.assertTrue(continued)
        self.assertEqual(cd.call_count, 2)
        close_all.assert_not_called()

    def test_during_cooldown_the_entry_loop_stops_before_entries(self):
        continued, cd, close_all, macro = self._run(_cfg(2), [self.CLOSE_ALL])
        self.assertFalse(continued)
        macro.assert_not_called()
        close_all.assert_not_called()


if __name__ == "__main__":
    unittest.main()
