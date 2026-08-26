#!/usr/bin/env python3
"""Transport tests for the version-specific Odoo clients."""

import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from odoo_direct import OdooAuthError, OdooDirect, OdooError, OdooXmlRpc, _NoRedirect


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class Json2ClientTests(unittest.TestCase):
    def test_redirects_are_never_followed(self):
        self.assertIsNone(_NoRedirect().redirect_request())

    def setUp(self):
        self.client = OdooDirect(
            config={
                "url": "https://example.odoo.com",
                "database": "example-db",
                "api_key": "secret-key",
            }
        )

    @patch("odoo_direct.urlopen")
    def test_search_uses_json2_endpoint_headers_and_named_body(self, mocked_open):
        mocked_open.return_value = FakeResponse([7])

        result = self.client.search("res.partner", [["name", "=", "Acme"]], limit=3)

        self.assertEqual(result, [7])
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.odoo.com/json/2/res.partner/search")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        self.assertEqual(request.get_header("X-odoo-database"), "example-db")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data),
            {"domain": [["name", "=", "Acme"]], "limit": 3},
        )

    @patch("odoo_direct.urlopen")
    def test_record_method_sends_ids_and_context(self, mocked_open):
        mocked_open.return_value = FakeResponse(True)

        result = self.client.call(
            "sale.order",
            "action_confirm",
            ids=[42],
            context={"lang": "en_US"},
        )

        self.assertTrue(result)
        request = mocked_open.call_args.args[0]
        self.assertEqual(
            json.loads(request.data),
            {"ids": [42], "context": {"lang": "en_US"}},
        )

    @patch("odoo_direct.urlopen")
    def test_create_normalizes_single_returned_id(self, mocked_open):
        mocked_open.return_value = FakeResponse([91])
        self.assertEqual(self.client.create("res.partner", {"name": "Acme"}), 91)

    @patch("odoo_direct.urlopen")
    def test_structured_unauthorized_response_raises_auth_error(self, mocked_open):
        body = json.dumps({"name": "Unauthorized", "message": "Invalid apikey"}).encode()
        mocked_open.side_effect = HTTPError(
            "https://example.odoo.com/json/2/res.users/context_get",
            401,
            "Unauthorized",
            {},
            io.BytesIO(body),
        )
        with self.assertRaisesRegex(OdooAuthError, "Invalid apikey"):
            self.client.call("res.users", "context_get")

    @patch("odoo_direct.urlopen")
    def test_non_json_error_body_is_preserved(self, mocked_open):
        mocked_open.side_effect = HTTPError(
            "https://example.odoo.com/json/2/res.partner/search",
            502,
            "Bad Gateway",
            {},
            io.BytesIO(b"upstream unavailable"),
        )
        with self.assertRaisesRegex(OdooError, "upstream unavailable"):
            self.client.search("res.partner", [])


class XmlRpcClientTests(unittest.TestCase):
    def setUp(self):
        self.client = OdooXmlRpc({
            "url": "https://legacy.example.com",
            "database": "legacy-db",
            "username": "agent@example.com",
            "api_key": "secret-key",
            "odoo_version": 17,
        })

    @patch("odoo_direct.xmlrpc.client.ServerProxy")
    def test_authenticates_and_reads_through_execute_kw(self, server_proxy):
        common = MagicMock()
        common.authenticate.return_value = 7
        objects = MagicMock()
        objects.execute_kw.return_value = [{"id": 4, "name": "Acme"}]
        server_proxy.side_effect = lambda url, **_kwargs: common if url.endswith("/common") else objects

        result = self.client.read("res.partner", [4], ["name"])

        self.assertEqual(result[0]["name"], "Acme")
        common.authenticate.assert_called_once_with("legacy-db", "agent@example.com", "secret-key", {})
        objects.execute_kw.assert_called_once_with(
            "legacy-db", 7, "secret-key", "res.partner", "read", [[4]], {"fields": ["name"]}
        )

    @patch("odoo_direct.xmlrpc.client.ServerProxy")
    def test_write_uses_positional_ids_and_values(self, server_proxy):
        common = MagicMock()
        common.authenticate.return_value = 7
        objects = MagicMock()
        objects.execute_kw.return_value = True
        server_proxy.side_effect = lambda url, **_kwargs: common if url.endswith("/common") else objects

        self.assertTrue(self.client.write("res.partner", [4], {"name": "After"}))

        objects.execute_kw.assert_called_once_with(
            "legacy-db", 7, "secret-key", "res.partner", "write", [[4], {"name": "After"}], {}
        )

    @patch("odoo_direct.xmlrpc.client.ServerProxy")
    def test_reports_server_major_version(self, server_proxy):
        common = MagicMock()
        common.version.return_value = {"server_version": "17.0+e"}
        server_proxy.return_value = common
        self.assertEqual(self.client.server_major_version(), 17)


if __name__ == "__main__":
    unittest.main()
