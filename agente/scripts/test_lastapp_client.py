"""
Tests para lastapp_client.py — cliente JSON-RPC MCP.

Verifica:
  - Handshake initialize
  - tools/list y tools/call
  - Retry en 401 con refresh
  - Reintentos con backoff exponencial
"""
import os
import sys
import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp'))


def _make_rpc_response(result, req_id=1):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_rpc_error(code, message, req_id=1):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


class TestLastAppClient:
    def token_getter(self):
        return "test-bearer-token"

    def setup_method(self):
        from lastapp_client import LastAppClient
        self.client = LastAppClient(auth_token_getter=self.token_getter)

    @mock.patch("lastapp_client.requests.post")
    def test_initialize_handshake(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = _make_rpc_response({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "lastapp-mcp", "version": "1.0.0"},
        })
        result = self.client.initialize()
        assert result["protocolVersion"] == "2024-11-05"
        assert self.client.capabilities == {"tools": {}, "resources": {}}
        assert self.client.server_info["name"] == "lastapp-mcp"
        assert mock_post.call_count >= 2

    @mock.patch("lastapp_client.requests.post")
    def test_discover_tools(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = _make_rpc_response({
            "tools": [
                {"name": "get_catalog_items", "description": "Lista productos del catálogo"},
                {"name": "get_sales_report", "description": "Reporte de ventas"},
                {"name": "list_reservations", "description": "Lista reservas"},
            ]
        }, req_id=2)
        tools = self.client.discover_tools()
        assert len(tools) == 3
        assert tools[0]["name"] == "get_catalog_items"
        assert tools[2]["name"] == "list_reservations"

    @mock.patch("lastapp_client.requests.post")
    def test_call_tool(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = _make_rpc_response({
            "content": [{"type": "text", "text": '{"products": []}'}]
        }, req_id=3)
        result = self.client.call_tool("get_catalog_items", {"limit": 10})
        assert "content" in result

    @mock.patch("lastapp_client.requests.post")
    def test_retry_on_401(self, mock_post):
        mock_401 = mock.MagicMock()
        mock_401.status_code = 401
        mock_401.json.return_value = {"error": "Unauthorized"}
        mock_401.raise_for_status.side_effect = __import__('requests').exceptions.HTTPError(response=mock_401)

        mock_ok = mock.MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = _make_rpc_response({"ok": True})
        mock_ok.raise_for_status.return_value = None

        mock_post.side_effect = [mock_401, mock_ok]

        result = self.client.call_tool("some_tool", {})
        assert result == {"ok": True}
        assert mock_post.call_count == 2

    @mock.patch("lastapp_client.requests.post")
    def test_retry_on_server_error(self, mock_post):
        import requests as req_mod
        error_500 = mock.MagicMock()
        error_500.status_code = 500
        error_500.raise_for_status.side_effect = req_mod.exceptions.HTTPError(response=error_500)

        mock_ok = mock.MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = _make_rpc_response({"ok": True})
        mock_ok.raise_for_status.return_value = None

        mock_post.side_effect = [error_500, error_500, mock_ok]
        result = self.client.call_tool("some_tool", {})
        assert result == {"ok": True}
        assert mock_post.call_count == 3

    @mock.patch("lastapp_client.requests.post")
    def test_jsonrpc_error_handling(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = _make_rpc_error(-32601, "Method not found")
        with pytest.raises(RuntimeError) as exc:
            self.client.call_tool("nonexistent_tool")
        assert "Method not found" in str(exc.value)
