#!/usr/bin/env python3
"""Small Odoo 19 JSON-2 client used by the global odoo-direct command."""

from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


_OPENER = build_opener(_NoRedirect)


def urlopen(request, timeout):
    """Open one endpoint without following redirects to another target."""
    return _OPENER.open(request, timeout=timeout)


class OdooError(Exception):
    """Base JSON-2 error."""


class OdooAuthError(OdooError):
    """The bearer API key was rejected."""


class OdooConfigError(OdooError):
    """Required target configuration is missing or invalid."""


class OdooDirect:
    """Stateless client for ``POST /json/2/<model>/<method>``."""

    def __init__(self, config_path=None, config=None, timeout=30):
        cfg: dict[str, Any] = {}
        if config is not None:
            cfg = dict(config)
        else:
            path = Path(config_path) if config_path else Path(__file__).with_name("config.json")
            if path.exists():
                try:
                    cfg = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise OdooConfigError(f"Invalid JSON: {exc}") from exc
            for key, variable in {
                "url": "ODOO_DIRECT_URL",
                "database": "ODOO_DIRECT_DB",
                "api_key": "ODOO_DIRECT_API_KEY",
            }.items():
                if value := os.environ.get(variable):
                    cfg[key] = value

        missing = [key for key in ("url", "database", "api_key") if not cfg.get(key)]
        if missing:
            raise OdooConfigError(f"Missing fields: {', '.join(missing)}")
        if not str(cfg["url"]).startswith(("http://", "https://")):
            raise OdooConfigError("url must start with http:// or https://")

        self.url = str(cfg["url"]).rstrip("/")
        self.database = str(cfg["database"])
        self.api_key = str(cfg["api_key"])
        self.timeout = timeout

    @staticmethod
    def _validate_name(value: str, label: str) -> str:
        if not NAME_RE.fullmatch(value):
            raise OdooConfigError(f"Invalid {label}: {value!r}")
        return value

    @staticmethod
    def _error_message(body: bytes, fallback: str) -> str:
        text = body.decode("utf-8", errors="replace").strip()
        if not text:
            return fallback
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("name") or payload)
        return str(payload)

    def call(
        self,
        model: str,
        method: str,
        *,
        ids: list[int] | None = None,
        context: dict[str, Any] | None = None,
        **kwargs,
    ):
        """Call a public model method using JSON-2 named arguments."""
        model = self._validate_name(model, "model")
        method = self._validate_name(method, "method")
        payload = dict(kwargs)
        if ids is not None:
            payload["ids"] = ids
        if context is not None:
            payload["context"] = context
        endpoint = f"{self.url}/json/2/{quote(model, safe='.')}/{quote(method, safe='_.')}"
        request = Request(
            endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Odoo-Database": self.database,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            message = self._error_message(exc.read(), exc.reason or f"HTTP {exc.code}")
            error_type = OdooAuthError if exc.code == 401 else OdooError
            raise error_type(f"HTTP {exc.code}: {message}") from exc
        except socket.timeout as exc:
            raise OdooError(f"Request timed out after {self.timeout}s") from exc
        except URLError as exc:
            raise OdooError(f"Cannot connect to {self.url}: {exc.reason}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise OdooError("Odoo returned invalid JSON") from exc

    def context_get(self):
        return self.call("res.users", "context_get")

    def search(self, model, domain=None, limit=None, offset=0, order=None):
        values: dict[str, Any] = {"domain": domain or []}
        if limit is not None:
            values["limit"] = limit
        if offset:
            values["offset"] = offset
        if order:
            values["order"] = order
        return self.call(model, "search", **values)

    def search_read(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        values: dict[str, Any] = {"domain": domain or []}
        if fields:
            values["fields"] = fields
        if limit is not None:
            values["limit"] = limit
        if offset:
            values["offset"] = offset
        if order:
            values["order"] = order
        return self.call(model, "search_read", **values)

    def read(self, model, ids, fields=None):
        values = {"fields": fields} if fields else {}
        return self.call(model, "read", ids=ids, **values)

    def create(self, model, vals):
        result = self.call(model, "create", vals_list=vals)
        if not isinstance(result, list) or len(result) != 1:
            raise OdooError(f"Expected one created ID, got {result!r}")
        return result[0]

    def write(self, model, ids, vals):
        return self.call(model, "write", ids=ids, vals=vals)

    def unlink(self, model, ids):
        return self.call(model, "unlink", ids=ids)

    def search_count(self, model, domain=None):
        return self.call(model, "search_count", domain=domain or [])


_odoo_instance = None


def _get_odoo():
    global _odoo_instance
    if _odoo_instance is None:
        _odoo_instance = OdooDirect()
    return _odoo_instance


class _OdooProxy:
    def __getattr__(self, name):
        return getattr(_get_odoo(), name)

    def __setattr__(self, name, value):
        return setattr(_get_odoo(), name, value)


odoo = _OdooProxy()
