"""Odoo JSON-RPC client for Odoo Project Sync."""

import json
from typing import Any
from urllib.parse import urljoin

import requests

from config import InstanceConfig
from error_handling import handle_odoo_api_errors
from exceptions import AuthenticationError, OdooAPIError
from interfaces import OdooClientInterface


class OdooClientError(OdooAPIError):
    """Odoo client error."""

    pass


class OdooAuthError(AuthenticationError):
    """Odoo authentication error."""

    pass


class OdooReadOnlyError(OdooClientError):
    """Attempted write operation on read-only instance."""

    pass


class OdooClient(OdooClientInterface):
    """JSON-RPC client for Odoo.

    Supports both JSON-RPC /jsonrpc endpoint (Odoo 14+) and legacy /xmlrpc/2
    endpoints.
    """

    def __init__(
        self,
        url: str,
        database: str,
        username: str,
        api_key: str,
        read_only: bool = False,
        timeout: int = 30,
    ):
        """Initialize Odoo client.

        Args:
            url: Odoo instance URL (e.g., https://mycompany.odoo.com)
            database: Database name
            username: Username (email)
            api_key: API key or password
            read_only: If True, block write operations
            timeout: Request timeout in seconds
        """
        self.url = url.rstrip("/")
        self.database = database
        self.username = username
        self.api_key = api_key
        self.read_only = read_only
        self.timeout = timeout

        self._uid: int | None = None
        self._request_id = 0

    @classmethod
    def from_config(cls, config: InstanceConfig) -> "OdooClient":
        """Create client from InstanceConfig.

        Args:
            config: Instance configuration

        Returns:
            Configured OdooClient
        """
        return cls(
            url=config.url,
            database=config.database,
            username=config.username,
            api_key=config.api_key,
            read_only=config.read_only,
        )

    @property
    def uid(self) -> int:
        """Get authenticated user ID, authenticating if necessary."""
        if self._uid is None:
            self.authenticate()
        return self._uid  # type: ignore

    def _next_id(self) -> int:
        """Get next JSON-RPC request ID."""
        self._request_id += 1
        return self._request_id

    def _jsonrpc(self, service: str, method: str, args: list[Any]) -> Any:
        """Make a JSON-RPC call.

        Args:
            service: Service name (common, object, db)
            method: Method name
            args: Method arguments

        Returns:
            Result from Odoo

        Raises:
            OdooClientError: If the request fails
        """
        endpoint = urljoin(self.url, "/jsonrpc")

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": service,
                "method": method,
                "args": args,
            },
            "id": self._next_id(),
        }

        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            raise OdooAPIError(f"Request failed: {e}")

        try:
            result = response.json()
        except json.JSONDecodeError as e:
            raise OdooAPIError(f"Invalid JSON response: {e}")

        if "error" in result:
            error = result["error"]
            message = error.get("data", {}).get("message") or error.get(
                "message", str(error)
            )
            raise OdooAPIError(f"Odoo error: {message}")

        return result.get("result")

    @handle_odoo_api_errors
    def authenticate(self) -> int:
        """Authenticate with Odoo and get user ID.

        Returns:
            User ID

        Raises:
            OdooAuthError: If authentication fails
        """
        try:
            uid = self._jsonrpc(
                "common",
                "authenticate",
                [self.database, self.username, self.api_key, {}],
            )
        except OdooAPIError as e:
            raise OdooAuthError(f"Authentication failed: {e}")

        if not uid:
            raise OdooAuthError(
                f"Authentication failed for {self.username}@{self.database}. "
                "Check credentials and API key."
            )

        self._uid = uid
        return uid

    def _check_write_allowed(self) -> None:
        """Check if write operations are allowed.

        Raises:
            OdooReadOnlyError: If instance is read-only
        """
        if self.read_only:
            raise OdooReadOnlyError(
                "Write operations not allowed on read-only instance"
            )

    def _execute(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a model method.

        Args:
            model: Model name (e.g., 'res.partner')
            method: Method name (e.g., 'search_read')
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Method result
        """
        return self._jsonrpc(
            "object",
            "execute_kw",
            [
                self.database,
                self.uid,
                self.api_key,
                model,
                method,
                args,
                kwargs or {},
            ],
        )

    def search_read(
        self,
        model: str,
        domain: list[Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search and read records.

        Args:
            model: Model name
            domain: Search domain (default: all records)
            fields: Fields to read (default: all)
            limit: Maximum records to return
            offset: Number of records to skip
            order: Sort order (e.g., 'name asc')

        Returns:
            List of record dictionaries
        """
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        if order:
            kwargs["order"] = order

        return self._execute(model, "search_read", [domain or []], kwargs)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read records by ID.

        Args:
            model: Model name
            ids: Record IDs to read
            fields: Fields to read (default: all)

        Returns:
            List of record dictionaries
        """
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields

        return self._execute(model, "read", [ids], kwargs)

    def search(
        self,
        model: str,
        domain: list[Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[int]:
        """Search for record IDs.

        Args:
            model: Model name
            domain: Search domain
            limit: Maximum records to return
            offset: Number of records to skip
            order: Sort order

        Returns:
            List of record IDs
        """
        kwargs: dict[str, Any] = {}
        if limit:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        if order:
            kwargs["order"] = order

        return self._execute(model, "search", [domain or []], kwargs)

    @handle_odoo_api_errors
    def create(self, model: str, vals: dict[str, Any]) -> int:
        """Create a new record.

        Args:
            model: Model name
            vals: Field values

        Returns:
            ID of created record

        Raises:
            OdooReadOnlyError: If instance is read-only
        """
        self._check_write_allowed()
        return self._execute(model, "create", [vals])

    def write(
        self,
        model: str,
        ids: list[int],
        vals: dict[str, Any],
    ) -> bool:
        """Update existing records.

        Args:
            model: Model name
            ids: Record IDs to update
            vals: Field values to update

        Returns:
            True if successful

        Raises:
            OdooReadOnlyError: If instance is read-only
        """
        self._check_write_allowed()
        return self._execute(model, "write", [ids, vals])

    @handle_odoo_api_errors
    def unlink(self, model: str, ids: list[int]) -> bool:
        """Delete records.

        Args:
            model: Model name
            ids: Record IDs to delete

        Returns:
            True if successful

        Raises:
            OdooReadOnlyError: If instance is read-only
        """
        self._check_write_allowed()
        return self._execute(model, "unlink", [ids])

    def search_count(
        self,
        model: str,
        domain: list[Any] | None = None,
    ) -> int:
        """Count records matching domain.

        Args:
            model: Model name
            domain: Search domain

        Returns:
            Number of matching records
        """
        return self._execute(model, "search_count", [domain or []])

    def fetch_task_timesheets(
        self,
        task_id: int,
        validated_only: bool = True,
    ) -> float:
        """Fetch total timesheet hours for a task.

        Args:
            task_id: Task ID to fetch timesheets for
            validated_only: If True, only include validated timesheets

        Returns:
            Total hours as float (0.0 if no timesheets or on error)
        """
        if task_id <= 0:
            return 0.0

        try:
            domain = [("task_id", "=", task_id)]
            if validated_only:
                domain.append(("validated", "=", True))

            timesheets = self.search_read(
                "account.analytic.line",
                domain=domain,
                fields=["unit_amount"],
            )

            total_hours = sum(
                float(ts.get("unit_amount", 0.0)) for ts in timesheets
            )
            return total_hours

        except (OdooAPIError, OdooClientError):
            # Return 0.0 on any error (graceful degradation)
            return 0.0

    @handle_odoo_api_errors
    def test_connection(self) -> dict[str, Any]:
        """Test connection and return server info.

        Returns:
            Dictionary with connection status and server info
        """
        try:
            # Get server version
            version_info = self._jsonrpc("common", "version", [])

            # Authenticate
            uid = self.authenticate()

            # Get user info
            user_info = self.read("res.users", [uid], ["name", "login"])[0]

            return {
                "success": True,
                "server_version": version_info.get("server_version"),
                "user_id": uid,
                "user_name": user_info.get("name"),
                "user_login": user_info.get("login"),
                "database": self.database,
                "url": self.url,
                "read_only": self.read_only,
            }
        except OdooAPIError as e:
            return {
                "success": False,
                "error": str(e),
                "url": self.url,
                "database": self.database,
            }
