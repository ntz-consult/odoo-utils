import json
import logging

from shared.python.cli import EXIT_CONFIG_ERROR, EXIT_SUCCESS, OdooSyncCLI


def test_project_sync_command_returns_config_error_when_not_configured(tmp_path):
    """Ensure 'project-sync' command runs and returns a config error when no
    config present."""
    cli = OdooSyncCLI()
    cli.project_root = tmp_path  # Use empty temporary directory
    rc = cli.run(["project-sync", "--execute"])
    assert rc == EXIT_CONFIG_ERROR


def test_import_alias_behaves_same_as_project_sync(tmp_path):
    """The old 'import' alias should still be accepted and behave the same."""
    cli = OdooSyncCLI()
    cli.project_root = tmp_path  # Use empty temporary directory
    rc = cli.run(["import", "--execute"])
    assert rc == EXIT_CONFIG_ERROR


def test_project_sync_uses_feature_user_story_map(
    tmp_path, monkeypatch, caplog
):
    """If a feature_user_story_map.toml exists, import should build user
    stories from it."""
    # Create minimal project layout
    project_root = tmp_path
    sync_dir = project_root / ".odoo-sync"
    data_dir = sync_dir / "data" / "extraction-results"
    data_dir.mkdir(parents=True)

    # Write a simple extraction result (one custom field on sale.order)
    cf = {
        "records": [
            {
                "id": 1,
                "name": "x_credit_limit",
                "field_description": "Credit Limit",
                "model": "sale.order",
                "is_studio": True,
            }
        ]
    }
    (data_dir / "custom_fields_output.json").write_text(json.dumps(cf))

    # Write a minimal config with development project
    config = {
        "instances": {
            "implementation": {
                "url": "https://impl",
                "database": "impl_db",
                "username": "impl",
                "api_key": "KEY",
                "read_only": True,
                "project": {},
            },
            "development": {
                "url": "https://dev",
                "database": "dev_db",
                "username": "dev",
                "api_key": "KEY",
                "read_only": False,
                "project": {"id": 1, "name": "Test Project"},
            },
        }
    }
    sync_dir.mkdir(parents=True, exist_ok=True)
    (sync_dir / "odoo-instances.json").write_text(json.dumps(config))

    # Create a feature_user_story_map.toml for the auto-detected feature name
    studio_dir = project_root / "studio"
    studio_dir.mkdir(parents=True, exist_ok=True)
    toml_content = """[features."Sales Order Customizations"]
description = "Sales order customizations"
user_stories = [ { description = "Add credit limit field", components = ["field.sale_order.x_credit_limit"] } ]
"""
    (studio_dir / "feature_user_story_map.toml").write_text(toml_content)

    # Monkeypatch OdooClient.from_config to prevent real connections
    class DummyClient:
        def test_connection(self):
            return {"success": True, "user_name": "tester"}

    monkeypatch.setattr(
        "shared.python.cli.OdooClient.from_config", lambda cfg: DummyClient()
    )

    # Run CLI (dry-run)
    cli = OdooSyncCLI()
    cli.project_root = project_root
    with caplog.at_level(logging.INFO):
        rc = cli.run(["project-sync"])  # dry-run

    assert rc == EXIT_SUCCESS
    assert "✓ Feature-user story map loaded" in caplog.text
    assert "Loaded 1 features with 1 user stories" in caplog.text
