#!/usr/bin/env python3
"""Tests for named odoo-direct targets and operation policies."""

import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).with_name("direct.py")
SPEC = importlib.util.spec_from_file_location("odoo_direct_cli", SCRIPT)
CLI = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = CLI
SPEC.loader.exec_module(CLI)


def config():
    return {
        "version": 1,
        "tags": {
            "production": {"read": "allow", "create": "ask", "write": "ask", "unlink": "ask", "exec": "ask"},
            "develop": {"read": "allow", "create": "allow", "write": "allow", "unlink": "ask", "exec": "ask"},
            "locked": {"read": "allow", "create": "deny", "write": "deny", "unlink": "deny", "exec": "deny"},
        },
        "targets": {
            "production": {"odoo_version": 19, "url": "https://example.odoo.com", "database": "live", "tags": ["production"]},
            "upgrade-19": {"odoo_version": 19, "url": "http://127.0.0.1:8096", "database": "upgrade", "tags": ["develop"]},
        },
    }


class DirectCliTests(unittest.TestCase):
    def test_derived_secret_name(self):
        with patch.dict(os.environ, {"ODOO_DIRECT_UPGRADE_19_API_KEY": "key"}, clear=True):
            client, target, label = CLI.target_client(config(), "upgrade-19")
        self.assertEqual(client.database, "upgrade")
        self.assertEqual(target["url"], "http://127.0.0.1:8096")
        self.assertEqual(label, "upgrade-19")

    def test_strictest_tag_wins(self):
        value = config()
        value["targets"]["upgrade-19"]["tags"] = ["develop", "locked"]
        self.assertEqual(CLI.resolve_policy(value, "upgrade-19", "write"), "deny")

    def test_missing_operation_policy_fails(self):
        value = config()
        del value["tags"]["develop"]["exec"]
        with self.assertRaisesRegex(CLI.TargetError, "missing policies: exec"):
            CLI.resolve_policy(value, "upgrade-19", "write")

    def test_production_cannot_allow_write(self):
        value = config()
        value["tags"]["production"]["write"] = "allow"
        with self.assertRaisesRegex(CLI.TargetError, "production"):
            CLI.resolve_policy(value, "production", "write")

    def test_ask_previews_without_write(self):
        client = MagicMock()
        client.read.return_value = [{"id": 4, "name": "Before"}]
        args = CLI.build_parser().parse_args(["production", "write", "res.partner", "[4]", "{'name': 'After'}"])
        self.assertEqual(CLI.execute_command(client, args, "ask")["status"], "preview")
        client.write.assert_not_called()

    def test_allow_writes_and_reads_back(self):
        client = MagicMock()
        client.read.side_effect = [[{"id": 4, "name": "Before"}], [{"id": 4, "name": "After"}]]
        client.write.return_value = True
        args = CLI.build_parser().parse_args(["upgrade-19", "write", "res.partner", "[4]", "{'name': 'After'}"])
        result = CLI.execute_command(client, args, "allow")
        self.assertEqual(result["readback"][0]["name"], "After")

    def test_deny_never_calls_target(self):
        client = MagicMock()
        args = CLI.build_parser().parse_args(["upgrade-19", "create", "res.partner", "{'name': 'No'}"])
        with self.assertRaisesRegex(CLI.TargetError, "denies create"):
            CLI.execute_command(client, args, "deny")
        client.create.assert_not_called()

    def test_target_listing_hides_secret(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"ODOO_DIRECT_PRODUCTION_API_KEY": "hidden"}, clear=True), redirect_stdout(output):
            CLI.print_targets(config(), True)
        self.assertIn('"credentials": "configured"', output.getvalue())
        self.assertNotIn("hidden", output.getvalue())


if __name__ == "__main__":
    unittest.main()
