"""N12: Entry-Kommission und Teil-TP-Kosten werden verbucht.

Befund der Code-Pruefung (30.09.2026): Die Entry-Kommission senkt beim Kauf nur die Stueckzahl, wurde aber
nirgends abgezogen (der Rueckfluss kam mit vollem position_size zurueck); der Teil-TP lief ohne
Slippage und Kommission. Je Trade rund 1 EUR bzw. 1 EUR plus Slippage.
Gilt ab Deploy, geschlossene Trades werden nicht rueckwirkend korrigiert.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from scripts import signal_manager as sm
from tests.test_k3_teil_tp import Ticks, _cfg, _make_db, _open_long, _tick, START_CASH


class CostTests(unittest.TestCase):
    def test_full_exit_without_partial_deducts_exit_and_entry_commission(self):
        con, ticks, cfg = _make_db(), Ticks(), _cfg()
        _open_long(con)
        _tick(con, cfg, ticks, 95.0)                       # SL 96 getroffen
        row = con.execute("SELECT * FROM positions").fetchone()
        pnl, _ = sm.realized_pnl_from_effective_entry(100.0, 95.0, 1000.0, "LONG")   # enthaelt Exit-Kommission
        self.assertAlmostEqual(row["pnl_eur"], pnl - sm.COMMISSION_EUR, delta=0.01)
        cash = con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()["cash"]
        self.assertAlmostEqual(cash - (START_CASH + 1000.0), row["pnl_eur"], delta=0.02)

    def test_partial_tp_carries_slippage_and_commission(self):
        con, ticks, cfg = _make_db(), Ticks(), _cfg()
        _open_long(con)
        _tick(con, cfg, ticks, 104.0)
        row = con.execute("SELECT * FROM positions").fetchone()
        raw = (104.0 - 100.0) / 100.0 * 500.0             # bisher: 20 EUR ohne Kosten
        self.assertLess(row["partial_pnl_eur"], raw - sm.COMMISSION_EUR + 0.001)
        expected, _ = sm.realized_pnl_from_effective_entry(100.0, 104.0, 500.0, "LONG")
        self.assertAlmostEqual(row["partial_pnl_eur"], expected, delta=0.01)
        cash = con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()["cash"]
        self.assertAlmostEqual(cash, START_CASH + 500.0 + expected, delta=0.02)

    def test_three_sides_of_commission_with_partial(self):
        """Entry + Teil-TP + Rest-Exit = 3 Kommissionen; Cash-Aenderung == Ledger."""
        con, ticks, cfg = _make_db(), Ticks(), _cfg()
        _open_long(con)
        _tick(con, cfg, ticks, 104.0)
        _tick(con, cfg, ticks, 99.0)
        row = con.execute("SELECT * FROM positions").fetchone()
        gross_partial = sm.realized_pnl_from_effective_entry(100.0, 104.0, 500.0, "LONG")[0] + sm.COMMISSION_EUR
        gross_rest = sm.realized_pnl_from_effective_entry(100.0, 99.0, 500.0, "LONG")[0] + sm.COMMISSION_EUR
        self.assertAlmostEqual(row["pnl_eur"], gross_partial + gross_rest - 3 * sm.COMMISSION_EUR, delta=0.02)
        cash = con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()["cash"]
        self.assertAlmostEqual(cash - (START_CASH + 1000.0), row["pnl_eur"], delta=0.03)


if __name__ == "__main__":
    unittest.main()
