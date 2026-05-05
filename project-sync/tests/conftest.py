"""Pytest configuration and fixtures for Odoo Project Sync tests."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Generator

import pytest

# Add shared/python to path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared" / "python"))


@pytest.fixture
def temp_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary project directory with .odoo-sync structure."""
    sync_dir = tmp_path / ".odoo-sync"
    sync_dir.mkdir()

    # Create subdirectories
    (sync_dir / "config").mkdir()
    (sync_dir / "data").mkdir()
    (sync_dir / "data" / "extraction-results").mkdir()
    (sync_dir / "data" / "snapshots").mkdir()
    (sync_dir / "data" / "audit").mkdir()

    yield tmp_path


@pytest.fixture
def sample_config() -> dict[str, Any]:
    """Sample configuration dictionary."""
    return {
        "instances": {
            "implementation": {
                "description": "Test Implementation",
                "url": "https://impl.odoo.com",
                "database": "impl_db",
                "username": "impl@test.com",
                "api_key": "impl_key_123",
                "read_only": True,
                "purpose": "extraction",
                "odoo_version": "19",
            },
            "development": {
                "description": "Test Development",
                "url": "https://dev.odoo.com",
                "database": "dev_db",
                "username": "dev@test.com",
                "api_key": "dev_key_456",
                "read_only": False,
                "purpose": "development",
                "odoo_version": "19",
                "project": {
                    "id": 123,
                    "name": "Test Project",                    "sale_line_id": None,
                },
            },
        },
        "active_instance": "development",
        "sync": {
            "conflict_resolution": "prefer_local",
            "preserve_logged_time": True,
            "auto_move_completed": True,
            "require_confirmation": False,
        },
  
    }


@pytest.fixture
def config_with_env_vars() -> dict[str, Any]:
    """Configuration with environment variable references."""
    return {
        "instances": {
            "implementation": {
                "url": "https://impl.odoo.com",
                "database": "impl_db",
                "username": "impl@test.com",
                "api_key": "${TEST_IMPL_API_KEY}",
                "read_only": True,
            },
            "development": {
                "url": "https://dev.odoo.com",
                "database": "dev_db",
                "username": "dev@test.com",
                "api_key": "${TEST_DEV_API_KEY}",
                "read_only": False,
            },
        },
    }


@pytest.fixture
def temp_config_file(
    temp_project: Path, sample_config: dict[str, Any]
) -> Path:
    """Create a temporary config file."""
    config_path = temp_project / ".odoo-sync" / "odoo-instances.json"
    with open(config_path, "w") as f:
        json.dump(sample_config, f)
    return config_path


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set up mock environment variables."""
    env_vars = {
        "TEST_IMPL_API_KEY": "mock_impl_key_from_env",
        "TEST_DEV_API_KEY": "mock_dev_key_from_env",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture
def mock_odoo_response() -> dict[str, Any]:
    """Sample Odoo JSON-RPC response."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": True,
    }


@pytest.fixture
def mock_odoo_version_response() -> dict[str, Any]:
    """Sample Odoo version response."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "server_version": "19.0",
            "server_version_info": [19, 0, 0, "final", 0, ""],
            "server_serie": "19.0",
            "protocol_version": 1,
        },
    }


@pytest.fixture
def mock_odoo_auth_response() -> dict[str, Any]:
    """Sample Odoo authentication response."""
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "result": 42,  # User ID
    }


@pytest.fixture
def mock_odoo_user_response() -> dict[str, Any]:
    """Sample Odoo user read response."""
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "result": [
            {
                "id": 42,
                "name": "Test User",
                "login": "test@example.com",
            }
        ],
    }
