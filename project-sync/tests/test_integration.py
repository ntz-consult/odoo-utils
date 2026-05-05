"""Integration tests for end-to-end workflows.

These tests verify the complete functionality of the Odoo Project Sync system
by testing full workflows from extraction to generation to sync.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from config import ProjectConfig
from feature_detector import FeatureDetector
from module_generator import ModuleGenerator
from odoo_client import OdooClient
from sync_engine import SyncEngine


class TestEndToEndWorkflow:
    """Test complete workflows from extraction to sync."""

    @pytest.fixture
    def temp_project(self, tmp_path: Path) -> Path:
        """Create a temporary project with config."""
        # Create .odoo-sync structure
        sync_dir = tmp_path / ".odoo-sync"
        sync_dir.mkdir()
        (sync_dir / "config").mkdir()
        (sync_dir / "data").mkdir()
        (sync_dir / "data" / "extraction-results").mkdir()
        (sync_dir / "data" / "snapshots").mkdir()
        (sync_dir / "data" / "audit").mkdir()

        # Create config
        config = {
            "instances": {
                "test": {
                    "description": "Test Instance",
                    "url": "https://test.odoo.com",
                    "database": "test_db",
                    "username": "test@example.com",
                    "api_key": "test_key",
                    "read_only": False,
                    "purpose": "development",
                    "odoo_version": "19",
                }
            },
            "project": {
                "name": "Test Project",
                "odoo_version": "19",
                "modules": ["test_module"],
            },
            "sync": {
                "default_instance": "test",
                "conflict_resolution": "prefer_local",
            },
        }

        with open(sync_dir / "odoo-instances.json", "w") as f:
            json.dump(config, f, indent=2)

        return tmp_path

    @patch("odoo_client.OdooClient")
    def test_full_extraction_to_generation_workflow(
        self, mock_odoo_client_class, temp_project: Path
    ):
        """Test complete workflow from Odoo extraction to module generation."""
        # Mock Odoo client (use MagicMock to allow arbitrary attributes)
        from unittest.mock import MagicMock
        mock_client = MagicMock()
        mock_odoo_client_class.return_value = mock_client

        # Mock extraction data
        mock_client.get_models.return_value = [
            {
                "model": "x_test.model",
                "name": "Test Model",
                "fields": [
                    {
                        "name": "x_test_field",
                        "type": "char",
                        "string": "Test Field",
                        "required": False,
                    }
                ],
            }
        ]

        mock_client.get_views.return_value = [
            {
                "id": 123,
                "model": "x_test.model",
                "type": "form",
                "arch": '<form><field name="x_test_field"/></form>',
            }
        ]

        # Step 1: Feature detection
        detector = FeatureDetector(
            odoo_client=mock_client,
            project_config=ProjectConfig(
                name="Test Project",
                odoo_version="19",
                modules=["test_module"],
            ),
        )

        features = detector.detect_features()
        assert len(features) > 0

        # Step 2: Module generation
        generator = ModuleGenerator(
            features=features,
            output_dir=temp_project / "generated_modules",
            odoo_client=mock_client,
        )

        generator.generate_modules()

        # Verify files were created
        output_dir = temp_project / "generated_modules" / "test_module"
        assert output_dir.exists()

        # Check for expected files
        assert (output_dir / "__init__.py").exists()
        assert (output_dir / "__manifest__.py").exists()
        assert (output_dir / "models").exists()
        assert (output_dir / "views").exists()

    def test_config_validation_integration(self, temp_project: Path):
        """Test that config validation works end-to-end."""
        from config_manager import ConfigManager

        # Valid config should load
        manager = ConfigManager(project_root=temp_project)
        config = manager.load_config()

        assert config is not None
        assert "instances" in config
        assert "test" in config["instances"]

        # Test validation
        is_valid, errors = manager.validate_config()
        assert is_valid, f"Config should be valid: {errors}"
