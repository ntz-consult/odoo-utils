"""Regression tests for the refresh row-count check.

Run: python3 -m unittest scripts/test_odoo_sh_refresh.py
"""

import unittest
from unittest.mock import patch

from scripts.odoo_sh_refresh import Failed, Refresh


class CountsTest(unittest.TestCase):
    def make_refresh(self, baseline, counts):
        refresh = Refresh.__new__(Refresh)
        refresh.status = {"row_counts": baseline}
        refresh.min_ratio = 0.9
        refresh.warnings = []
        refresh.step = lambda name: None
        refresh.counts = lambda: counts
        return refresh

    @patch("scripts.odoo_sh_refresh.log")
    def test_legacy_pair_uses_last_good_count(self, _log):
        refresh = self.make_refresh({"account_move": [58024, 58167]}, {"account_move": 58167})

        refresh.sanity()

        self.assertEqual(refresh.status["row_counts"], {"account_move": 58167})

    @patch("scripts.odoo_sh_refresh.log")
    def test_legacy_pair_still_detects_drop(self, _log):
        refresh = self.make_refresh({"account_move": [100, 200]}, {"account_move": 150})

        with self.assertRaisesRegex(Failed, "account_move 150 \\(was 200\\)"):
            refresh.sanity()

        self.assertEqual(refresh.status["row_counts"], {"account_move": [100, 200]})


if __name__ == "__main__":
    unittest.main()
