"""Tests for scripts/worktree_remove.sh (odoo-worktree-remove) with fake dropdb/pgrep.

Run: python3 -m unittest scripts/test_worktree_remove.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import ports  # noqa: E402

SCRIPT = SCRIPTS / "worktree_remove.sh"


class WorktreeRemoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.log = self.base / "calls.log"
        fake = self.base / "bin"
        fake.mkdir()
        (fake / "dropdb").write_text('#!/bin/sh\necho "dropdb $* pw=${PGPASSWORD:+set}" >> "$FAKE_LOG"\n')
        (fake / "pgrep").write_text(
            '#!/bin/sh\nif [ -f "$FAKE_PIDFILE" ]; then cat "$FAKE_PIDFILE"; rm -f "$FAKE_PIDFILE"; exit 0; fi\nexit 1\n')
        for tool in fake.iterdir():
            tool.chmod(0o755)
        self.register = self.base / "ports.toml"
        self.register.write_text(
            'version = 1\nwork_root = "%s"\n\n[projects.demo]\nmain = 8100\nworktrees = [8300, 8349]\n'
            'worktree_tests = [24000, 25999]\ntest_block = 40\nremove_hook = "echo hook-ran $ODOO_REMOVED_DB >> $FAKE_LOG"\n'
            % self.base)
        self.env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", FAKE_LOG=str(self.log),
                        FAKE_PIDFILE=str(self.base / "pids"), ODOO_PORTS_REGISTER=str(self.register),
                        GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        self.env.pop("ODOO_WORKTREE_REMOVE_HOOK", None)
        self.main = self.base / "demo"
        self.git("init", "-q", "-b", "main", str(self.main))
        self.write_config(self.main, "demo", 8100)
        (self.main / ".gitignore").write_text("/.odoo/worktree.toml\n/.odoo/secrets.env\n/.odoo/data/\n/.odoo/odoo.conf\n")
        self.git("-C", str(self.main), "add", ".")
        self.git("-C", str(self.main), "commit", "-qm", "init")
        self.wt = self.base / "demo-feature"
        self.git("-C", str(self.main), "worktree", "add", "-q", "-b", "feature", str(self.wt))
        (self.wt / ".odoo" / "worktree.toml").write_text(
            '[database]\nname = "demo_feature"\nhost = "localhost"\n\n[ports]\nhttp = 8300\n'
            'test_range_start = 24000\ntest_range_end = 24039\n')
        (self.wt / ".odoo" / "secrets.env").write_text("DB_PASSWORD=not-printed\n")
        (self.wt / ".odoo" / "data" / "filestore" / "demo_feature").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], check=True, env=self.env, capture_output=True)

    def write_config(self, root, project, http):
        (root / ".odoo").mkdir(parents=True, exist_ok=True)
        (root / ".odoo" / "config.toml").write_text(
            f'version = 1\n\n[project]\nname = "{project}"\n\n[database]\nname = "{project}"\n\n'
            f'[ports]\nhttp = {http}\n')

    def remove(self, *args):
        return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                              env=self.env, stdin=subprocess.DEVNULL)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_dry_run_changes_nothing(self):
        done = self.remove("--dry-run", str(self.wt))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("demo_feature (dropped)", done.stdout)
        self.assertTrue(self.wt.exists())
        self.assertEqual(self.calls(), "")

    def test_removes_folder_database_branch_and_runs_hook(self):
        (self.base / "pids").write_text("999999\n")
        done = self.remove("--yes", str(self.wt))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.wt.exists())
        calls = self.calls()
        self.assertIn("dropdb --host localhost --if-exists --force demo_feature pw=set", calls)
        self.assertIn("hook-ran demo_feature", calls)
        self.assertNotIn("not-printed", done.stdout + done.stderr)
        listing = subprocess.run(["git", "-C", str(self.main), "worktree", "list"], capture_output=True,
                                 text=True, env=self.env).stdout
        self.assertNotIn("demo-feature", listing)
        branches = subprocess.run(["git", "-C", str(self.main), "branch"], capture_output=True,
                                  text=True, env=self.env).stdout
        self.assertNotIn("feature", branches)

    def test_ports_are_free_once_the_folder_is_gone(self):
        register = ports.load_register(self.register, required=True)
        before = ports.allocate(register, "demo", owners=ports.claims(register),
                                is_listening=lambda port: False)
        self.assertEqual(before["http"], 8301)
        self.assertEqual(self.remove("--yes", str(self.wt)).returncode, 0)
        after = ports.allocate(register, "demo", owners=ports.claims(register),
                               is_listening=lambda port: False)
        self.assertEqual(after["http"], 8300)

    def test_refuses_uncommitted_work(self):
        (self.wt / "new.py").write_text("x = 1\n")
        done = self.remove("--yes", str(self.wt))
        self.assertEqual(done.returncode, 1)
        self.assertIn("uncommitted", done.stdout)
        self.assertTrue(self.wt.exists())
        self.assertEqual(self.calls(), "")

    def test_refuses_unpushed_commits_unless_forced(self):
        (self.wt / "work.py").write_text("x = 1\n")
        self.git("-C", str(self.wt), "add", "work.py")
        self.git("-C", str(self.wt), "commit", "-qm", "work")
        done = self.remove("--yes", str(self.wt))
        self.assertEqual(done.returncode, 1)
        self.assertIn("not in any other branch", done.stdout)
        self.assertTrue(self.wt.exists())
        forced = self.remove("--yes", "--force", str(self.wt))
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertFalse(self.wt.exists())

    def test_merged_commits_are_not_at_risk(self):
        (self.wt / "work.py").write_text("x = 1\n")
        self.git("-C", str(self.wt), "add", "work.py")
        self.git("-C", str(self.wt), "commit", "-qm", "work")
        self.git("-C", str(self.main), "merge", "-q", "--ff-only", "feature")
        done = self.remove("--yes", str(self.wt))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_refuses_primary_checkout(self):
        done = self.remove("--yes", str(self.main))
        self.assertEqual(done.returncode, 1)
        self.assertIn("primary checkout", done.stderr)

    def test_refuses_primary_database(self):
        (self.wt / ".odoo" / "worktree.toml").write_text('[ports]\nhttp = 8300\n')
        done = self.remove("--yes", str(self.wt))
        self.assertEqual(done.returncode, 1)
        self.assertIn("primary checkout's database", done.stderr)
        self.assertTrue(self.wt.exists())

    def test_needs_yes_without_terminal(self):
        done = self.remove(str(self.wt))
        self.assertEqual(done.returncode, 1)
        self.assertIn("--yes", done.stderr)
        self.assertTrue(self.wt.exists())

    def test_explicit_hook_wins(self):
        done = self.remove("--yes", "--hook", "echo explicit >> $FAKE_LOG", str(self.wt))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("explicit", self.calls())
        self.assertNotIn("hook-ran", self.calls())


if __name__ == "__main__":
    unittest.main()
