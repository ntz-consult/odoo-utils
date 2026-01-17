"""Tests for configuration module."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from config import (
    Config,
    ConfigError,
    ExtractionFilters,
    InstanceConfig,
    ProjectConfig,
    SyncConfig,
    load_config,
    save_config,
)
from utils import resolve_env_vars, resolve_env_vars_in_dict


class TestResolveEnvVars:
    """Tests for environment variable resolution."""

    def test_resolve_single_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving a single environment variable."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = resolve_env_vars("prefix_${TEST_VAR}_suffix")
        assert result == "prefix_test_value_suffix"

    def test_resolve_multiple_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test resolving multiple environment variables."""
        monkeypatch.setenv("VAR1", "one")
        monkeypatch.setenv("VAR2", "two")
        result = resolve_env_vars("${VAR1}_and_${VAR2}")
        assert result == "one_and_two"

    def test_resolve_missing_var_raises(self) -> None:
        """Test that missing env var raises ValueError."""
        with pytest.raises(ValueError, match="NONEXISTENT_VAR"):
            resolve_env_vars("${NONEXISTENT_VAR}")

    def test_resolve_no_vars(self) -> None:
        """Test string without variables passes through."""
        result = resolve_env_vars("plain_string")
        assert result == "plain_string"

    def test_resolve_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving env vars in nested dictionary."""
        monkeypatch.setenv("API_KEY", "secret123")
        data = {
            "url": "https://example.com",
            "api_key": "${API_KEY}",
            "nested": {
                "key": "${API_KEY}",
            },
        }
        result = resolve_env_vars_in_dict(data)
        assert result["api_key"] == "secret123"
        assert result["nested"]["key"] == "secret123"
        assert result["url"] == "https://example.com"


class TestInstanceConfig:
    """Tests for InstanceConfig."""

    def test_from_dict_basic(self) -> None:
        """Test creating InstanceConfig from dict."""
        data = {
            "url": "https://odoo.com",
            "database": "db",
            "username": "user",
            "api_key": "key",
        }
        config = InstanceConfig.from_dict(data)
        assert config.url == "https://odoo.com"
        assert config.database == "db"
        assert config.username == "user"
        assert config.api_key == "key"
        assert config.read_only is True  # Default

    def test_from_dict_with_project(self) -> None:
        """Test creating InstanceConfig with project config."""
        data = {
            "url": "https://odoo.com",
            "database": "db",
            "username": "user",
            "api_key": "key",
            "read_only": False,
            "project": {
                "id": 123,
                "name": "Test",
                "sale_line_id": 456,
            },
        }
        config = InstanceConfig.from_dict(data)
        assert config.read_only is False
        assert config.project is not None
        assert config.project.id == 123
        assert config.project.name == "Test"
        assert config.project.sale_line_id == 456


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_config(
        self,
        temp_project: Path,
        sample_config: dict[str, Any],
    ) -> None:
        """Test loading valid configuration."""
        config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
        with open(config_path, "w") as f:
            json.dump(sample_config, f)

        config = load_config(temp_project)

        assert isinstance(config, Config)
        assert "implementation" in config.instances
        assert "development" in config.instances
        assert config.implementation.url == "https://impl.odoo.com"
        assert config.development.read_only is False

    def test_load_config_with_env_vars(
        self,
        temp_project: Path,
        config_with_env_vars: dict[str, Any],
        mock_env_vars: dict[str, str],
    ) -> None:
        """Test loading config with environment variable resolution."""
        config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
        with open(config_path, "w") as f:
            json.dump(config_with_env_vars, f)

        config = load_config(temp_project)

        assert config.implementation.api_key == "mock_impl_key_from_env"
        assert config.development.api_key == "mock_dev_key_from_env"

    def test_load_missing_config_raises(self, temp_project: Path) -> None:
        """Test that missing config file raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            load_config(temp_project)

    def test_load_invalid_json_raises(self, temp_project: Path) -> None:
        """Test that invalid JSON raises ConfigError."""
        config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
        with open(config_path, "w") as f:
            f.write("{ invalid json }")

        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(temp_project)

    def test_load_missing_required_field_raises(
        self, temp_project: Path
    ) -> None:
        """Test that missing required fields raise ConfigError."""
        config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
        with open(config_path, "w") as f:
            json.dump(
                {
                    "instances": {
                        "implementation": {
                            "url": "https://odoo.com",
                            "database": "test_db",
                        },
                        "test": {
                            "url": "https://odoo.com",
                            # Missing: database, username, api_key
                        }
                    }
                },
                f,
            )

        with pytest.raises(ConfigError, match="missing required fields"):
            load_config(temp_project)


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config(
        self,
        temp_project: Path,
        sample_config: dict[str, Any],
    ) -> None:
        """Test saving configuration."""
        config_path = save_config(sample_config, temp_project)

        assert config_path.exists()
        with open(config_path) as f:
            loaded = json.load(f)
        assert loaded == sample_config

    def test_save_creates_sync_dir(self, tmp_path: Path) -> None:
        """Test that save_config creates .odoo-sync directory."""
        config_data = {"instances": {}}
        config_path = save_config(config_data, tmp_path)

        assert (tmp_path / ".odoo-sync").is_dir()
        assert config_path.exists()


class TestConfig:
    """Tests for Config class."""

    def test_get_instance(
        self,
        temp_project: Path,
        sample_config: dict[str, Any],
    ) -> None:
        """Test getting instance by name."""
        config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
        with open(config_path, "w") as f:
            json.dump(sample_config, f)

        config = load_config(temp_project)

        impl = config.get_instance("implementation")
        assert impl.url == "https://impl.odoo.com"

        dev = config.get_instance("development")
        assert dev.url == "https://dev.odoo.com"

    def test_get_instance_not_found_raises(
        self,
        temp_project: Path,
        sample_config: dict[str, Any],
    ) -> None:
        """Test getting non-existent instance raises KeyError."""
        config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
        with open(config_path, "w") as f:
            json.dump(sample_config, f)

        config = load_config(temp_project)

        with pytest.raises(KeyError, match="nonexistent"):
            config.get_instance("nonexistent")

    def test_implementation_property(
        self,
        temp_project: Path,
        sample_config: dict[str, Any],
    ) -> None:
        """Test implementation property shortcut."""
        config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
        with open(config_path, "w") as f:
            json.dump(sample_config, f)

        config = load_config(temp_project)
        assert config.implementation.read_only is True

    def test_development_property(
        self,
        temp_project: Path,
        sample_config: dict[str, Any],
    ) -> None:
        """Test development property shortcut."""
        config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
        with open(config_path, "w") as f:
            json.dump(sample_config, f)

        config = load_config(temp_project)
        assert config.development.read_only is False
        assert config.development.project is not None
        assert config.development.project.id == 123
