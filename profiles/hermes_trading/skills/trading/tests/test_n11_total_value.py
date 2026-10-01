"""N11: portfolio.total_value bedeutet ueberall Cash + Marktwert der offenen Positionen.

Befund der Code-Pruefung (30.09.2026): Exit- und Entry-Pfade schrieben cash + Summe(position_size)
(Buchwert), check_drawdown() den Marktwert. Der Wert hing vom letzten Schreiber ab.
"""
import os
import re
import sqlite3
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from scripts import signal_manager as sm

PRICES = {"AAA": 110.0, "BBB": 55.0}


def _make_db(cash=1000.0, total=1000.0):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE watchlist (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT, conviction_score REAL)")
    sm.init_db(con)
    con.execute("DELETE FROM portfolio")
    con.execute("INSERT INTO portfolio (id, cash, total_value, ath_value) VALUES (1, ?, ?, ?)",
                (cash, total, 11207.85))
    con.commit()
    return con


def _add(con, ticker, direction, entry, size):
    con.execute(
        "INSERT INTO positions (ticker, name, direction, entry_price, entry_date, position_size, status) "
        "VALUES (?, ?, ?, ?, '2026-09-20', ?, 'open')", (ticker, ticker, direction, entry, size))
    con.commit()


def _price(ticker):
    return PRICES.get(ticker), 1.0, None


class ComputeTotalValueTests(unittest.TestCase):
    def test_cash_plus_market_value_long_and_short(self):
        con = _make_db()
        _add(con, "AAA", "LONG", 100.0, 500.0)    # Kurs +10 %  -> 550
        _add(con, "BBB", "SHORT", 50.0, 300.0)    # Kurs +10 %  -> 270
        with mock.patch("utils.get_price_data_cached", side_effect=_price):
            self.assertAlmostEqual(sm.compute_total_value(con, 1000.0), 1000.0 + 550.0 + 270.0, places=2)

    def test_book_value_is_not_used(self):
        con = _make_db()
        _add(con, "AAA", "LONG", 100.0, 500.0)
        with mock.patch("utils.get_price_data_cached", side_effect=_price):
            self.assertNotAlmostEqual(sm.compute_total_value(con, 1000.0), 1000.0 + 500.0, places=2)

    def test_missing_price_falls_back_to_cost_basis(self):
        con = _make_db()
        _add(con, "ZZZ", "LONG", 100.0, 500.0)
        with mock.patch("utils.get_price_data_cached", side_effect=_price):
            self.assertAlmostEqual(sm.compute_total_value(con, 1000.0), 1500.0, places=2)

    def test_no_positions(self):
        con = _make_db()
        self.assertAlmostEqual(sm.compute_total_value(con, 1234.567), 1234.57, places=2)

    def test_same_definition_as_check_drawdown(self):
        con = _make_db(cash=1000.0, total=999.0)
        _add(con, "AAA", "LONG", 100.0, 500.0)
        _add(con, "BBB", "SHORT", 50.0, 300.0)
        with mock.patch("utils.get_price_data_cached", side_effect=_price), \
             mock.patch.object(sm, "prefetch_prices"):
            expected = sm.compute_total_value(con, 1000.0)
            sm.check_drawdown(con)
        stored = con.execute("SELECT total_value FROM portfolio WHERE id=1").fetchone()[0]
        self.assertAlmostEqual(stored, expected, places=2)


class NoBookValueWritersLeftTests(unittest.TestCase):
    def test_no_writer_sums_position_size_into_total_value(self):
        src = open(os.path.join(ROOT, "scripts", "signal_manager.py"), encoding="utf-8").read()
        pattern = re.compile(r'cash \+ sum\(\s*r\["position_size"\] for r in con\.execute\(')
        self.assertEqual(pattern.findall(src), [],
                         "ein Schreiber rechnet total_value noch als Buchwert (cash + Summe position_size)")


if __name__ == "__main__":
    unittest.main()
