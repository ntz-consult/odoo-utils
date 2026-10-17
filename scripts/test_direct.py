#!/usr/bin/env python3
"""Tests for named odoo-direct targets and operation policies."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).with_name("direct.py")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "direct"))
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
            "production-17": {"odoo_version": 17, "url": "https://legacy.example.com", "database": "live17", "username": "agent@example.com", "tags": ["production"]},
            "production": {"odoo_version": 19, "url": "https://example.odoo.com", "database": "live", "tags": ["production"]},
            "upgrade-19": {"odoo_version": 19, "url": "http://127.0.0.1:8096", "database": "upgrade", "tags": ["develop"]},
        },
    }


class DirectCliTests(unittest.TestCase):
    def test_shared_local_database_uses_its_own_key(self):
        value = config()
        value['targets']['local'] = {'odoo_version': 19, 'url': 'http://localhost:8096',
                                     'database': 'ibcorr_ticket_17', 'tags': ['develop']}
        with patch.dict(os.environ, {'ODOO_SHARED_DATABASE': '1',
                                    'ODOO_DIRECT_LOCAL_API_KEY': 'wrong-primary-key',
                                    'ODOO_DIRECT_LOCAL_IBCORR_TICKET_17_API_KEY': 'worktree-key'}, clear=True):
            client, target, _ = CLI.target_client(value, 'local')
        self.assertEqual(target['api_key'], 'worktree-key')

    def test_shared_local_database_does_not_fall_back_to_primary_key(self):
        value = config()
        value['targets']['local'] = {'odoo_version': 19, 'url': 'http://localhost:8096',
                                     'database': 'ibcorr_ticket_17', 'tags': ['develop']}
        with patch.dict(os.environ, {'ODOO_SHARED_DATABASE': '1',
                                    'ODOO_DIRECT_LOCAL_API_KEY': 'wrong-primary-key'}, clear=True):
            with self.assertRaisesRegex(CLI.TargetError, 'LOCAL_IBCORR_TICKET_17_API_KEY'):
                CLI.target_client(value, 'local')

    def test_derived_secret_name(self):
        with patch.dict(os.environ, {"ODOO_DIRECT_UPGRADE_19_API_KEY": "key"}, clear=True):
            client, target, label = CLI.target_client(config(), "upgrade-19")
        self.assertEqual(client.database, "upgrade")
        self.assertEqual(target["url"], "http://127.0.0.1:8096")
        self.assertEqual(label, "upgrade-19")

    def test_odoo_17_selects_xml_rpc(self):
        with patch.dict(os.environ, {"ODOO_DIRECT_PRODUCTION_17_API_KEY": "key"}, clear=True):
            client, target, label = CLI.target_client(config(), "production-17")
        self.assertEqual(client.transport, "xml-rpc")
        self.assertEqual(client.username, "agent@example.com")
        self.assertEqual(target["odoo_version"], 17)
        self.assertEqual(label, "production-17")

    def test_xml_rpc_requires_username(self):
        value = config()
        del value["targets"]["production-17"]["username"]
        with patch.dict(os.environ, {"ODOO_DIRECT_PRODUCTION_17_API_KEY": "key"}, clear=True):
            with self.assertRaisesRegex(CLI.TargetError, "username"):
                CLI.target_client(value, "production-17")

    def test_saas_version_string_selects_json2(self):
        value = config()
        value["targets"]["production"]["odoo_version"] = "saas~19.3.1.3"
        with patch.dict(os.environ, {"ODOO_DIRECT_PRODUCTION_API_KEY": "key"}, clear=True):
            client, target, label = CLI.target_client(value, "production")
        self.assertEqual(client.transport, "json-2")
        self.assertEqual(client.odoo_version, 19)
        self.assertEqual(target["odoo_version"], 19)
        self.assertEqual(label, "production")

    def test_dotted_version_selects_json2(self):
        value = config()
        value["targets"]["production"]["odoo_version"] = "19.3.1.3"
        with patch.dict(os.environ, {"ODOO_DIRECT_PRODUCTION_API_KEY": "key"}, clear=True):
            client, _target, _label = CLI.target_client(value, "production")
        self.assertEqual(client.odoo_version, 19)

    def test_versions_before_17_are_rejected(self):
        value = config()
        value["targets"]["production-17"]["odoo_version"] = 16
        with self.assertRaisesRegex(CLI.TargetError, "minimum is 17"):
            CLI.target_client(value, "production-17")

    def test_connection_test_rejects_version_mismatch(self):
        client = MagicMock(odoo_version=17, transport="xml-rpc")
        client.server_major_version.return_value = 18
        args = CLI.build_parser().parse_args(["production-17", "test"])
        with self.assertRaisesRegex(CLI.TargetError, "server reports Odoo 18"):
            CLI.execute_command(client, args, "allow")
        client.context_get.assert_not_called()

    def test_connection_test_accepts_matching_saas_major(self):
        client = MagicMock(odoo_version=19, transport="json-2")
        client.server_major_version.return_value = 19
        client.context_get.return_value = {"uid": 2}
        client.search_count.return_value = 4
        args = CLI.build_parser().parse_args(["production", "test"])
        result = CLI.execute_command(client, args, "allow")
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["odoo version"], 19)

    def test_strictest_tag_wins(self):
        value = config()
        value["targets"]["upgrade-19"]["tags"] = ["develop", "locked"]
        self.assertEqual(CLI.resolve_policy(value, "upgrade-19", "write"), "deny")

    def test_missing_operation_policy_fails(self):
        value = config()
        del value["tags"]["develop"]["exec"]
        with self.assertRaisesRegex(CLI.TargetError, "missing policies: exec"):
            CLI.resolve_policy(value, "upgrade-19", "write")

    def test_config_allows_production_write(self):
        value = config()
        value["tags"]["production"]["write"] = "allow"
        self.assertEqual(CLI.resolve_policy(value, "production", "write"), "allow")

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


def scoped():
    value = config()
    value["tags"]["production"]["models"] = {
        "helpdesk.ticket": {
            "create": "allow",
            "write": "allow",
            "fields": {"stage_id": "ask"},
            "methods": {"message_post": "allow"},
        },
        "res.partner": {"write": "deny"},
    }
    return value


class ModelRuleTests(unittest.TestCase):
    def test_legacy_config_unchanged(self):
        value = config()
        self.assertEqual(CLI.resolve_policy(value, "production", "write", model="res.partner"), "ask")
        self.assertEqual(CLI.resolve_policy(value, "upgrade-19", "write", model="res.partner"), "allow")
        self.assertEqual(CLI.resolve_rule(value, "production", "read")[1], "tags.production.read")

    def test_model_rule_overrides_tag(self):
        policy, source = CLI.resolve_rule(scoped(), "production", "write", model="helpdesk.ticket")
        self.assertEqual(policy, "allow")
        self.assertEqual(source, 'tags.production.models."helpdesk.ticket".write')
        self.assertEqual(CLI.resolve_policy(scoped(), "production", "create", model="helpdesk.ticket"), "allow")

    def test_other_models_keep_tag_policy(self):
        self.assertEqual(CLI.resolve_policy(scoped(), "production", "write", model="sale.order"), "ask")
        self.assertEqual(CLI.resolve_policy(scoped(), "production", "create", model="sale.order"), "ask")

    def test_unlink_and_exec_not_widened(self):
        value = scoped()
        self.assertEqual(CLI.resolve_policy(value, "production", "unlink", model="helpdesk.ticket"), "ask")
        self.assertEqual(
            CLI.resolve_policy(value, "production", "exec", model="helpdesk.ticket", method="action_x"), "ask"
        )

    def test_field_rule_strictest_touched_field(self):
        value = scoped()
        self.assertEqual(
            CLI.resolve_policy(value, "production", "write", model="helpdesk.ticket", fields=["name"]), "allow"
        )
        policy, source = CLI.resolve_rule(
            value, "production", "write", model="helpdesk.ticket", fields=["name", "stage_id"]
        )
        self.assertEqual(policy, "ask")
        self.assertEqual(source, 'tags.production.models."helpdesk.ticket".fields.stage_id')

    def test_method_rule(self):
        self.assertEqual(
            CLI.resolve_policy(scoped(), "production", "exec", model="helpdesk.ticket", method="message_post"),
            "allow",
        )

    def test_exec_alias_cannot_bypass_unlink(self):
        value = scoped()
        value["tags"]["production"]["models"]["helpdesk.ticket"]["exec"] = "allow"
        value["tags"]["production"]["models"]["helpdesk.ticket"]["methods"]["unlink"] = "allow"
        policy, source = CLI.resolve_rule(value, "production", "exec", model="helpdesk.ticket", method="unlink")
        self.assertEqual(policy, "ask")
        self.assertIn("via exec unlink", source)
        self.assertEqual(
            CLI.resolve_policy(value, "production", "exec", model="helpdesk.ticket", method="write"), "allow"
        )
        self.assertEqual(
            CLI.resolve_policy(value, "production", "exec", model="sale.order", method="write"), "ask"
        )

    def test_model_rule_can_tighten(self):
        self.assertEqual(CLI.resolve_policy(scoped(), "production", "write", model="res.partner"), "deny")

    def test_strictest_tag_still_wins(self):
        value = scoped()
        value["targets"]["production"]["tags"] = ["production", "locked"]
        self.assertEqual(CLI.resolve_policy(value, "production", "write", model="helpdesk.ticket"), "deny")

    def test_invalid_rules_rejected(self):
        value = config()
        value["tags"]["production"]["models"] = {"helpdesk.ticket": {"wirte": "allow"}}
        with self.assertRaisesRegex(CLI.TargetError, "unknown keys: wirte"):
            CLI.resolve_policy(value, "production", "write", model="sale.order")
        value["tags"]["production"]["models"] = {"helpdesk.ticket": {"write": "yes"}}
        with self.assertRaisesRegex(CLI.TargetError, "invalid policy"):
            CLI.resolve_policy(value, "production", "write", model="helpdesk.ticket")
        value["tags"]["production"]["models"] = {"helpdesk.ticket": {"methods": {"message_post": "always"}}}
        with self.assertRaisesRegex(CLI.TargetError, "invalid policy"):
            CLI.resolve_policy(value, "production", "read")

    def test_relational_commands_detected(self):
        self.assertTrue(CLI.has_relational_commands({"tag_ids": [(4, 1)]}))
        self.assertTrue(CLI.has_relational_commands({"line_ids": [[2, 5]]}))
        self.assertFalse(CLI.has_relational_commands({"tag_ids": [1, 2], "name": "x"}))


class MainPolicyTests(unittest.TestCase):
    def run_main(self, value, argv):
        client = MagicMock()
        client.read.return_value = [{"id": 4, "name": "Before"}]
        client.write.return_value = True
        client.create.return_value = 9
        target = {"url": "https://example.odoo.com", "database": "live", "api_key": "k", "odoo_version": 19}
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / ".odoo").mkdir()
            env = {"ODOO_DIRECT_PROJECT_ROOT": root}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(CLI, "load_project_config", return_value=value), \
                    patch.object(CLI, "target_client", return_value=(client, target, "production")), \
                    redirect_stdout(io.StringIO()) as output:
                CLI.main(["--json", *argv])
            log = Path(root) / ".odoo" / CLI.AUDIT_LOG
            lines = log.read_text().splitlines() if log.exists() else []
        return client, json.loads(output.getvalue()), lines

    def test_rule_allowed_write_runs_and_is_audited(self):
        client, out, lines = self.run_main(
            scoped(), ["production", "write", "helpdesk.ticket", "[4]", "{'name': 'Secret text'}"]
        )
        client.write.assert_called_once_with("helpdesk.ticket", [4], {"name": "Secret text"})
        self.assertEqual(out["policy"], "allow")
        self.assertEqual(out["rule"], 'tags.production.models."helpdesk.ticket".write')
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["fields"], ["name"])
        self.assertFalse(entry["confirmed"])
        self.assertNotIn("Secret text", lines[0])

    def test_rule_allowed_create_records_new_id(self):
        _client, _out, lines = self.run_main(scoped(), ["production", "create", "helpdesk.ticket", "{'name': 'T'}"])
        self.assertEqual(json.loads(lines[0])["result_id"], 9)

    def test_other_model_previews_without_audit(self):
        client, out, lines = self.run_main(
            scoped(), ["production", "write", "sale.order", "[4]", "{'name': 'After'}"]
        )
        client.write.assert_not_called()
        self.assertEqual(out["result"]["status"], "preview")
        self.assertEqual(lines, [])

    def test_relational_commands_fall_back_to_ask(self):
        client, out, _lines = self.run_main(
            scoped(), ["production", "write", "helpdesk.ticket", "[4]", "{'name': [(2, 5)]}"]
        )
        client.write.assert_not_called()
        self.assertEqual(out["policy"], "ask")
        self.assertIn("relational commands", out["rule"])

    def test_tag_level_allow_keeps_relational_commands(self):
        client, _out, _lines = self.run_main(
            config(), ["upgrade-19", "write", "res.partner", "[4]", "{'name': [(4, 5)]}"]
        )
        client.write.assert_called_once()

    def test_confirmed_ask_is_audited(self):
        client, _out, lines = self.run_main(
            scoped(), ["production", "write", "sale.order", "[4]", "{'name': 'After'}", "--confirm"]
        )
        client.write.assert_called_once()
        self.assertTrue(json.loads(lines[0])["confirmed"])


if __name__ == "__main__":
    unittest.main()
