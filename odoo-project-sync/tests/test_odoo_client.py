"""Tests for Odoo JSON-RPC client."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import responses
from odoo_client import (
    OdooAuthError,
    OdooClient,
    OdooClientError,
    OdooReadOnlyError,
)


class TestOdooClientInit:
    """Tests for OdooClient initialization."""

    def test_init_strips_trailing_slash(self) -> None:
        """Test that URL trailing slash is stripped."""
        client = OdooClient(
            url="https://odoo.com/",
            database="db",
            username="user",
            api_key="key",
        )
        assert client.url == "https://odoo.com"

    def test_init_defaults(self) -> None:
        """Test default values."""
        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        assert client.read_only is False
        assert client.timeout == 30
        assert client._uid is None


class TestOdooClientAuthentication:
    """Tests for authentication."""

    @responses.activate
    def test_authenticate_success(self) -> None:
        """Test successful authentication."""
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "result": 42},
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        uid = client.authenticate()

        assert uid == 42
        assert client._uid == 42

    @responses.activate
    def test_authenticate_failure(self) -> None:
        """Test authentication failure."""
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "result": False},
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="wrong_key",
        )

        with pytest.raises(OdooAuthError, match="Authentication failed"):
            client.authenticate()

    @responses.activate
    def test_authenticate_error_response(self) -> None:
        """Test authentication with error response."""
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "message": "Access Denied",
                    "data": {"message": "Invalid credentials"},
                },
            },
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )

        with pytest.raises(OdooAuthError):
            client.authenticate()


class TestOdooClientReadOperations:
    """Tests for read operations."""

    @responses.activate
    def test_search_read(self) -> None:
        """Test search_read operation."""
        # Auth response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "result": 42},
            status=200,
        )
        # search_read response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "result": [
                    {"id": 1, "name": "Record 1"},
                    {"id": 2, "name": "Record 2"},
                ],
            },
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        records = client.search_read(
            "res.partner",
            domain=[["is_company", "=", True]],
            fields=["id", "name"],
            limit=10,
        )

        assert len(records) == 2
        assert records[0]["name"] == "Record 1"

    @responses.activate
    def test_read(self) -> None:
        """Test read operation."""
        # Auth response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "result": 42},
            status=200,
        )
        # read response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "result": [{"id": 1, "name": "Record 1"}],
            },
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        records = client.read("res.partner", [1], ["id", "name"])

        assert len(records) == 1
        assert records[0]["id"] == 1

    @responses.activate
    def test_search_count(self) -> None:
        """Test search_count operation."""
        # Auth response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "result": 42},
            status=200,
        )
        # search_count response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 2, "result": 150},
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        count = client.search_count("res.partner", [["is_company", "=", True]])

        assert count == 150


class TestOdooClientWriteOperations:
    """Tests for write operations."""

    @responses.activate
    def test_create(self) -> None:
        """Test create operation."""
        # Auth response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "result": 42},
            status=200,
        )
        # create response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 2, "result": 123},
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        record_id = client.create("res.partner", {"name": "New Partner"})

        assert record_id == 123

    @responses.activate
    def test_write(self) -> None:
        """Test write operation."""
        # Auth response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "result": 42},
            status=200,
        )
        # write response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"jsonrpc": "2.0", "id": 2, "result": True},
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        result = client.write("res.partner", [1], {"name": "Updated"})

        assert result is True

    def test_create_read_only_raises(self) -> None:
        """Test that create on read-only instance raises."""
        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
            read_only=True,
        )
        client._uid = 42  # Skip auth

        with pytest.raises(OdooReadOnlyError):
            client.create("res.partner", {"name": "Test"})

    def test_write_read_only_raises(self) -> None:
        """Test that write on read-only instance raises."""
        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
            read_only=True,
        )
        client._uid = 42  # Skip auth

        with pytest.raises(OdooReadOnlyError):
            client.write("res.partner", [1], {"name": "Test"})

    def test_unlink_read_only_raises(self) -> None:
        """Test that unlink on read-only instance raises."""
        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
            read_only=True,
        )
        client._uid = 42  # Skip auth

        with pytest.raises(OdooReadOnlyError):
            client.unlink("res.partner", [1])


class TestOdooClientTestConnection:
    """Tests for test_connection method."""

    @responses.activate
    def test_connection_success(
        self,
        mock_odoo_version_response: dict[str, Any],
        mock_odoo_auth_response: dict[str, Any],
        mock_odoo_user_response: dict[str, Any],
    ) -> None:
        """Test successful connection test."""
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json=mock_odoo_version_response,
            status=200,
        )
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json=mock_odoo_auth_response,
            status=200,
        )
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json=mock_odoo_user_response,
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        result = client.test_connection()

        assert result["success"] is True
        assert result["server_version"] == "19.0"
        assert result["user_id"] == 42
        assert result["user_name"] == "Test User"

    @responses.activate
    def test_connection_failure(self) -> None:
        """Test failed connection test."""
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"message": "Connection refused"},
            },
            status=200,
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )
        result = client.test_connection()

        assert result["success"] is False
        assert "error" in result


class TestOdooClientFromConfig:
    """Tests for from_config class method."""

    def test_from_config(self) -> None:
        """Test creating client from InstanceConfig."""
        from config import InstanceConfig

        instance = InstanceConfig(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
            read_only=True,
        )

        client = OdooClient.from_config(instance)

        assert client.url == "https://odoo.com"
        assert client.database == "db"
        assert client.username == "user"
        assert client.api_key == "key"
        assert client.read_only is True

class TestOdooClientTimesheets:
    """Tests for timesheet fetching functionality."""

    @responses.activate
    def test_fetch_task_timesheets_success(self) -> None:
        """Test successful timesheet fetching."""
        # Mock authentication
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"result": 1},
        )
        
        # Mock timesheet search_read
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"result": [
                {"unit_amount": 2.5},
                {"unit_amount": 1.75},
                {"unit_amount": 0.5},
            ]},
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )

        total_hours = client.fetch_task_timesheets(task_id=123, validated_only=True)

        assert total_hours == 4.75  # 2.5 + 1.75 + 0.5

    @responses.activate
    def test_fetch_task_timesheets_no_timesheets(self) -> None:
        """Test fetching timesheets when none exist."""
        # Mock authentication
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"result": 1},
        )
        
        # Mock empty timesheet result
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"result": []},
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )

        total_hours = client.fetch_task_timesheets(task_id=456)

        assert total_hours == 0.0

    def test_fetch_task_timesheets_invalid_task_id(self) -> None:
        """Test fetching timesheets with invalid task_id returns 0.0."""
        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )

        # Task ID <= 0 should return 0.0 without API call
        assert client.fetch_task_timesheets(task_id=0) == 0.0
        assert client.fetch_task_timesheets(task_id=-1) == 0.0

    @responses.activate
    def test_fetch_task_timesheets_api_error(self) -> None:
        """Test graceful handling of API errors."""
        # Mock authentication
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"result": 1},
        )
        
        # Mock API error
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"error": {"message": "Access denied"}},
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )

        # Should return 0.0 on error (graceful degradation)
        total_hours = client.fetch_task_timesheets(task_id=789)

        assert total_hours == 0.0

    @responses.activate
    def test_fetch_task_timesheets_validated_only_filter(self) -> None:
        """Test that validated_only parameter is used in domain filter."""
        # Mock authentication
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"result": 1},
        )
        
        # Mock timesheet response
        responses.add(
            responses.POST,
            "https://odoo.com/jsonrpc",
            json={"result": [{"unit_amount": 3.0}]},
        )

        client = OdooClient(
            url="https://odoo.com",
            database="db",
            username="user",
            api_key="key",
        )

        # Call with validated_only=True
        total_hours = client.fetch_task_timesheets(task_id=111, validated_only=True)

        assert total_hours == 3.0
        
        # Verify the API call was made with correct domain
        last_request = responses.calls[-1].request
        assert b'"validated"' in last_request.body
        assert b'"task_id"' in last_request.body