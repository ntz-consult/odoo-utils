"""Regression tests for the refresh row-count check and the filestore opt-in.

Run: python3 -m unittest scripts/test_odoo_sh_refresh.py
"""

import datetime as dt
import types
import unittest
from unittest.mock import patch

import tempfile
from pathlib import Path

from scripts.odoo_sh_refresh import SAST, Failed, Refresh, check_config


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


class FilestoreTest(unittest.TestCase):
    def make_refresh(self, with_filestore=False, opt_in=False, days=("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"),
                     last=None):
        refresh = Refresh.__new__(Refresh)
        refresh.args = types.SimpleNamespace(with_filestore=with_filestore)
        refresh.filestore_opt_in = opt_in
        refresh.days = list(days)
        refresh.filestore_max_age = dt.timedelta(days=7)
        refresh.filestore_remote = "/remote/filestore"
        refresh.ssh_target = "user@host"
        refresh.db = "db"
        refresh.status = {"filestore_copied": last} if last else {}
        refresh.step = lambda name: None
        refresh.calls = []
        refresh.rsync = lambda *a, **k: refresh.calls.append(a)
        return refresh

    @patch("scripts.odoo_sh_refresh.log")
    def test_default_skips_even_on_its_day_and_when_stale(self, _log):
        refresh = self.make_refresh()  # every day listed, never copied before
        refresh.filestore()
        self.assertEqual(refresh.calls, [])
        self.assertNotIn("filestore_copied", refresh.status)

    @patch("scripts.odoo_sh_refresh.log")
    def test_cli_opt_in_copies(self, _log):
        with tempfile.TemporaryDirectory() as tmp:
            refresh = self.make_refresh(with_filestore=True, days=())
            refresh.data_dir = Path(tmp)
            refresh.filestore()
        self.assertEqual(len(refresh.calls), 1)
        self.assertIn("filestore_copied", refresh.status)

    @patch("scripts.odoo_sh_refresh.log")
    def test_config_opt_in_uses_schedule(self, _log):
        with tempfile.TemporaryDirectory() as tmp:
            refresh = self.make_refresh(opt_in=True)
            refresh.data_dir = Path(tmp)
            refresh.filestore()
        self.assertEqual(len(refresh.calls), 1)

    @patch("scripts.odoo_sh_refresh.log")
    def test_config_opt_in_off_day_recent_copy_keeps(self, _log):
        today = dt.datetime.now(SAST).date().isoformat()
        refresh = self.make_refresh(opt_in=True, days=(), last=today)
        refresh.filestore()
        self.assertEqual(refresh.calls, [])

    def test_filestore_keys_optional_in_config(self):
        config = {
            "source": {"ssh": 1, "key": 1, "dump": 1},
            "target": {k: 1 for k in ("database", "checkout", "conf", "report_url", "data_dir", "session",
                                      "lock", "state_dir", "data_source")},
            "run": {k: 1 for k in ("fresh", "min_free_gb", "min_backup_age_min", "max_backup_age_hours",
                                   "allowed_restore_errors", "min_ratio", "count_tables", "neutralize_sql")},
        }
        try:
            check_config(config)
        except Failed as exc:
            self.assertNotIn("filestore", str(exc))


if __name__ == "__main__":
    unittest.main()
