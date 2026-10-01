"""M9: Quellen-Gewichte und Kalibrierung greifen auch fuer RSS- und Mixed-Case-Quellen.

Befund der Code-Pruefung (30.09.2026): get_channel_weights/get_channel_calibration lieferten Schluessel in der
Originalschreibweise (display_name), die Mentions tragen aber lower()/strip() und bei RSS das Praefix 'rss:'.
16 % der Mentions der letzten 14 Tage liefen dadurch ohne Gewicht (Fallback 1.0).
"""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from scripts import watchlist_manager as wm


def make_db(rows):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE source_registry (id INTEGER PRIMARY KEY, display_name TEXT, weight REAL, status TEXT, "
                "enabled INTEGER, avg_pnl_per_trade REAL)")
    for name, weight, status, pnl in rows:
        con.execute("INSERT INTO source_registry (display_name, weight, status, enabled, avg_pnl_per_trade) "
                    "VALUES (?,?,?,1,?)", (name, weight, status, pnl))
    return con


class WeightTests(unittest.TestCase):
    def test_mixed_case_name_is_found_under_its_normalized_channel(self):
        w = wm.get_channel_weights(make_db([("Aktien mit Kopf", 0.5, "probation", None)]))
        self.assertEqual(w["aktien mit kopf"], 0.5)
        self.assertEqual(w["Aktien mit Kopf"], 0.5)

    def test_rss_prefix_variant_is_found(self):
        w = wm.get_channel_weights(make_db([("The Motley Fool UK", 0.5, "probation", None)]))
        self.assertEqual(w["rss:the motley fool uk"], 0.5)

    def test_exact_name_wins_over_derived_variant(self):
        w = wm.get_channel_weights(make_db([("PensionCraft", 0.5, "probation", None),
                                            ("pensioncraft", 1.4, "active", None)]))
        self.assertEqual(w["pensioncraft"], 1.4)
        self.assertEqual(w["PensionCraft"], 0.5)

    def test_unknown_channel_still_has_no_entry(self):
        w = wm.get_channel_weights(make_db([("Real Vision", 2.45, "active", None)]))
        self.assertNotIn("techaktien", w)
        self.assertEqual(w.get("techaktien", 1.0), 1.0)

    def test_calibration_uses_the_same_variants(self):
        cal = wm.get_channel_calibration(make_db([("The Motley Fool UK", 0.5, "probation", -30.0),
                                                  ("Aktien mit Kopf", 0.5, "probation", 60.0)]))
        self.assertEqual(cal["rss:the motley fool uk"], 0.3)
        self.assertEqual(cal["aktien mit kopf"], 1.5)

    def test_share_of_recent_mentions_without_weight_is_small_on_the_snapshot(self):
        try:
            from config import DB_PATH
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT lower(trim(channel)) c FROM watchlist_mentions "
                               "WHERE mention_date >= date('now','-14 day')").fetchall()
            w = wm.get_channel_weights(con)
        except Exception as e:
            self.skipTest(f"kein Snapshot: {e}")
        if len(rows) < 50:
            self.skipTest("zu wenige Mentions im Snapshot")
        missing = sum(1 for r in rows if r["c"] not in w) / len(rows)
        self.assertLess(missing, 0.08, f"{missing:.1%} der Mentions ohne Gewicht")


if __name__ == "__main__":
    unittest.main()
