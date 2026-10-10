"""Tests for scripts/ports.py and its wiring into odoo-run, odoo-test and odoo-init-env.

Run: python3 -m unittest scripts/test_ports.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import ports  # noqa: E402

REGISTER = """\
version = 1
gevent_offset = 500
public_offset = 10000
work_root = "{work}"

[projects.alpha]
main = 8096
main_test = [9096, 9197]
worktrees = [8201, 8249]
worktree_tests = [10000, 14899]
test_block = 100

[projects.beta]
main = 8097
main_test = [9198, 9299]
worktrees = [8250, 8299]
worktree_tests = [19000, 23999]
test_block = 100

[projects.gamma]
worktrees = [8300, 8349]
worktree_tests = [24000, 25999]
test_block = 40
"""


def write_checkout(root: Path, project: str, http: int | None, *, worktree: dict | None = None,
                   tests: tuple[int, int] | None = None, odoo_root: Path | None = None) -> Path:
    (root / ".odoo").mkdir(parents=True, exist_ok=True)
    lines = ["version = 1", "", "[project]", f'name = "{project}"', ""]
    if odoo_root is not None:
        lines += ["[odoo]", f'root = "{odoo_root}"', f'data_dir = "{root}/.odoo/data"', ""]
    lines += ["[database]", f'name = "{project}"', ""]
    if http is not None:
        lines += ["[ports]", f"http = {http}"]
        if tests:
            lines += [f"test_http = {tests[0]}", f"test_gevent = {tests[0] + 1}",
                      f"test_range_start = {tests[0]}", f"test_range_end = {tests[1]}"]
    (root / ".odoo" / "config.toml").write_text("\n".join(lines) + "\n")
    if worktree:
        body = "[ports]\n" + "".join(f"{key} = {value}\n" for key, value in worktree.items())
        (root / ".odoo" / "worktree.toml").write_text(body)
    return root


class PortsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.work = self.base / "Work"
        self.work.mkdir()
        self.register_path = self.base / "ports.toml"
        self.register_path.write_text(REGISTER.format(work=self.work))
        self.register = ports.load_register(self.register_path, required=True)

    def tearDown(self):
        self.tmp.cleanup()


class RegisterTests(PortsBase):
    def test_loads_pools(self):
        self.assertEqual(set(self.register.pools), {"alpha", "beta", "gamma"})
        self.assertIsNone(self.register.pools["gamma"].main)
        self.assertEqual(self.register.pools["beta"].worktrees, (8250, 8299))

    def test_overlapping_pools_are_refused(self):
        self.register_path.write_text(REGISTER.format(work=self.work).replace(
            "worktrees = [8250, 8299]", "worktrees = [8240, 8299]"))
        with self.assertRaisesRegex(ports.PortError, "overlap"):
            ports.load_register(self.register_path, required=True)

    def test_gevent_or_public_overlap_is_refused(self):
        # alpha's gevent ports 8701-8749 would land in this pool.
        text = REGISTER.format(work=self.work) + textwrap.dedent("""
            [projects.delta]
            worktrees = [8700, 8710]
            worktree_tests = [26000, 26999]
        """)
        self.register_path.write_text(text)
        with self.assertRaisesRegex(ports.PortError, "overlap"):
            ports.load_register(self.register_path, required=True)

    def test_default_register_missing_means_no_enforcement(self):
        env = {"HOME": str(self.base)}
        self.assertIsNone(ports.load_register(environ=env))

    def test_explicit_register_missing_is_an_error(self):
        env = {"ODOO_PORTS_REGISTER": str(self.base / "missing.toml")}
        with self.assertRaisesRegex(ports.PortError, "not found"):
            ports.load_register(environ=env)

    def test_bad_span(self):
        self.register_path.write_text(REGISTER.format(work=self.work).replace(
            "worktrees = [8300, 8349]", "worktrees = [8349, 8300]"))
        with self.assertRaisesRegex(ports.PortError, "first, last"):
            ports.load_register(self.register_path, required=True)

    def test_slot_math(self):
        self.assertEqual(ports.slot_for_http(self.register, "alpha", 8201),
                         {"http": 8201, "gevent": 8701, "test_start": 10000, "test_end": 10099})
        self.assertEqual(ports.slot_for_http(self.register, "gamma", 8301),
                         {"http": 8301, "gevent": 8801, "test_start": 24040, "test_end": 24079})
        with self.assertRaisesRegex(ports.PortError, "outside alpha"):
            ports.slot_for_http(self.register, "alpha", 8250)


class AllocateTests(PortsBase):
    def test_first_free_slot(self):
        got = ports.allocate(self.register, "beta", owners={}, is_listening=lambda port: False)
        self.assertEqual(got, {"http": 8250, "gevent": 8750, "test_start": 19000, "test_end": 19099})

    def test_skips_ports_claimed_by_any_checkout(self):
        write_checkout(self.work / "beta-one", "beta", 8250)
        write_checkout(self.work / "other", "alpha", 8096, worktree={"http": 8251})
        owners = ports.claims(self.register)
        got = ports.allocate(self.register, "beta", owners=owners, is_listening=lambda port: False)
        self.assertEqual(got["http"], 8252)

    def test_skips_test_block_claims(self):
        write_checkout(self.work / "x", "alpha", 8096, tests=(19000, 19010))
        got = ports.allocate(self.register, "beta", owners=ports.claims(self.register),
                             is_listening=lambda port: False)
        self.assertEqual(got["http"], 8251)

    def test_skips_listening_ports(self):
        got = ports.allocate(self.register, "alpha", owners={},
                             is_listening=lambda port: port in {8201, 10150})
        self.assertEqual(got["http"], 8203)

    def test_own_claims_do_not_block(self):
        me = write_checkout(self.work / "me", "alpha", 8096, worktree={"http": 8201})
        got = ports.allocate(self.register, "alpha", me, owners=ports.claims(self.register),
                             is_listening=lambda port: False)
        self.assertEqual(got["http"], 8201)

    def test_pool_exhausted(self):
        with self.assertRaisesRegex(ports.PortError, "no free worktree slot"):
            ports.allocate(self.register, "gamma", owners={}, is_listening=lambda port: True)

    def test_unknown_project(self):
        with self.assertRaisesRegex(ports.PortError, "no port pool"):
            ports.allocate(self.register, "nope", owners={}, is_listening=lambda port: False)


class CheckTests(PortsBase):
    def test_main_and_worktree_ports_pass(self):
        main = write_checkout(self.work / "alpha", "alpha", 8096, tests=(9096, 9197))
        self.assertEqual(ports.check(self.register, "alpha", main, 8096, 8596, (9096, 9097)), [])
        wt = write_checkout(self.work / "alpha-wt", "alpha", 8096, worktree={"http": 8201})
        self.assertEqual(ports.check(self.register, "alpha", wt, 8201, 8701, (10000, 10001)), [])

    def test_port_outside_pool_is_refused(self):
        root = write_checkout(self.work / "beta", "beta", 8201)
        problems = ports.check(self.register, "beta", root, 8201)
        self.assertTrue(any("outside beta's pool" in p for p in problems), problems)

    def test_wrong_gevent_is_refused(self):
        root = write_checkout(self.work / "beta", "beta", 8097)
        problems = ports.check(self.register, "beta", root, 8097, 8072)
        self.assertTrue(any("gevent port 8072" in p for p in problems), problems)

    def test_test_ports_outside_pool_are_refused(self):
        root = write_checkout(self.work / "beta", "beta", 8097)
        problems = ports.check(self.register, "beta", root, 8097, None, (10000, 10001))
        self.assertTrue(any("test pool" in p for p in problems), problems)

    def test_port_shared_with_another_checkout_is_refused(self):
        write_checkout(self.work / "alpha", "alpha", 8096)
        copy = write_checkout(self.work / "alpha-copy", "alpha", 8096)
        problems = ports.check(self.register, "alpha", copy, 8096)
        self.assertTrue(any("also assigned" in p for p in problems), problems)

    def test_stale_out_of_pool_claim_does_not_block_owner(self):
        write_checkout(self.work / "gamma", "gamma", 8097)  # stale config inside beta's pool
        beta = write_checkout(self.work / "beta", "beta", 8097)
        self.assertEqual(ports.check(self.register, "beta", beta, 8097), [])
        gamma_problems = ports.check(self.register, "gamma", self.work / "gamma", 8097)
        self.assertTrue(gamma_problems)

    def test_cli_exit_codes(self):
        root = write_checkout(self.work / "beta", "beta", 8097)
        base = [sys.executable, str(SCRIPTS / "ports.py"), "--register", str(self.register_path)]
        ok = subprocess.run(base + ["check", "beta", "--root", str(root), "--http", "8097"],
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = subprocess.run(base + ["check", "beta", "--root", str(root), "--http", "8201"],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("outside beta's pool", bad.stderr)

    def test_cli_without_register_does_not_enforce(self):
        env = dict(os.environ, HOME=str(self.base))
        env.pop("ODOO_PORTS_REGISTER", None)
        done = subprocess.run([sys.executable, str(SCRIPTS / "ports.py"), "check", "x", "--root",
                               str(self.base), "--http", "1"], capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        done = subprocess.run([sys.executable, str(SCRIPTS / "ports.py"), "active"],
                              capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 3)


class WiringTests(PortsBase):
    """odoo-run / odoo-init-env against a fake odoo-bin; nothing real is started."""

    def setUp(self):
        super().setUp()
        self.odoo = self.base / "fake-odoo"
        (self.odoo / "odoo").mkdir(parents=True)
        bin_path = self.odoo / "odoo" / "odoo-bin"
        bin_path.write_text("#!/bin/sh\necho FAKE-ODOO-STARTED \"$@\"\n")
        bin_path.chmod(0o755)
        self.env = dict(os.environ, ODOO_PORTS_REGISTER=str(self.register_path),
                        GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        for key in ("HTTP_PORT", "GEVENT_PORT", "PROJECT_NAME", "DB_NAME"):
            self.env.pop(key, None)

    def git_checkout(self, name, project, http):
        root = self.work / name
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True, env=self.env)
        write_checkout(root, project, http, odoo_root=self.odoo, tests=None)
        return root

    def run_cmd(self, root, script, *args):
        return subprocess.run(["bash", str(SCRIPTS / script), *args], cwd=root,
                              capture_output=True, text=True, env=self.env)

    def test_run_inside_pool_starts(self):
        root = self.git_checkout("beta", "beta", 8097)
        done = self.run_cmd(root, "run.sh")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("FAKE-ODOO-STARTED", done.stdout)
        conf = (root / ".odoo" / "odoo.conf").read_text()
        self.assertIn("http_port = 8097", conf)
        self.assertIn("gevent_port = 8597", conf)

    def test_run_outside_pool_is_refused(self):
        root = self.git_checkout("beta", "beta", 8201)
        done = self.run_cmd(root, "run.sh")
        self.assertEqual(done.returncode, 1)
        self.assertNotIn("FAKE-ODOO-STARTED", done.stdout)
        self.assertIn("outside beta's pool", done.stderr)
        self.assertIn("Refusing to start", done.stderr)

    def test_run_command_line_port_is_checked(self):
        root = self.git_checkout("beta", "beta", 8097)
        for args in (["--", "--http-port", "8201"], ["--", "--http-port=8201"], ["-p", "8201"]):
            done = self.run_cmd(root, "run.sh", *args)
            self.assertEqual(done.returncode, 1, args)
            self.assertNotIn("FAKE-ODOO-STARTED", done.stdout)

    def test_unregistered_project_is_refused(self):
        root = self.git_checkout("zeta", "zeta", 8097)
        done = self.run_cmd(root, "run.sh")
        self.assertEqual(done.returncode, 1)
        self.assertIn("no port pool", done.stderr)

    def test_init_env_worktree_allocates_from_pool(self):
        self.git_checkout("beta", "beta", 8097)
        wt = self.git_checkout("beta-wt", "beta", 8097)
        done = self.run_cmd(wt, "init_env.sh", "--worktree", "--db", "beta_wt")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = (wt / ".odoo" / "worktree.toml").read_text()
        for line in ("http = 8250", "gevent = 8750", "test_range_start = 19000",
                     "test_range_end = 19099", 'database = "beta_wt"'):
            self.assertIn(line, text)

    def test_init_env_worktree_refuses_foreign_port(self):
        wt = self.git_checkout("beta-wt", "beta", 8097)
        done = self.run_cmd(wt, "init_env.sh", "--worktree", "--db", "x", "--http-port", "8201")
        self.assertEqual(done.returncode, 1)
        self.assertFalse((wt / ".odoo" / "worktree.toml").exists())


if __name__ == "__main__":
    unittest.main()
