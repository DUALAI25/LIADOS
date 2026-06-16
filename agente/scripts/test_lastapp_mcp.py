"""
Tests integrales del MCP LastApp server.
Mockea requests.post para no llamar a Last.app real.

Cubre:
  - Caché de tools de lectura
  - Flujo pending_action (crear, confirmar, cancelar)
  - Expiración de acciones pendientes
  - Manejo de errores con token inválido
"""
import os
import sys
import json
import time
import uuid
import pytest
from unittest import mock
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp'))

MOCK_PRODUCTS = [
    {"id": "p1", "name": "Kebab Pollo", "price": 6.50, "available": True},
    {"id": "p2", "name": "Kebab Ternera", "price": 7.00, "available": True},
    {"id": "p3", "name": "Tarta Queso", "price": 4.50, "available": False},
]


def _make_rpc_response(result, req_id=1):
    return mock.MagicMock(
        status_code=200,
        json=mock.MagicMock(return_value={"jsonrpc": "2.0", "id": req_id, "result": result}),
        raise_for_status=mock.MagicMock(),
    )


@pytest.fixture
def mock_mcp_server(monkeypatch):
    import lastapp_server
    import lastapp_client
    import lastapp_auth

    lastapp_server._client = None
    lastapp_server._client_available = None
    lastapp_server._pending_actions.clear()
    lastapp_server._message_cache.clear()

    monkeypatch.setenv("LASTAPP_OAUTH_BEARER_TOKEN", "test-token")

    mock_client = mock.MagicMock(spec=lastapp_client.LastAppClient)
    mock_client.call_tool.return_value = {"products": MOCK_PRODUCTS, "total": 3}

    with mock.patch.object(lastapp_server, "_check_or_init_client", return_value=True):
        with mock.patch.object(lastapp_server, "_call_remote") as mock_call_remote:
            mock_call_remote.side_effect = lambda tool, args: _mock_remote_call(tool, args)
            yield {
                "server": lastapp_server,
                "client": mock_client,
                "call_remote": mock_call_remote,
            }


def _mock_remote_call(tool_name, args):
    if tool_name == "list_products":
        return {"products": MOCK_PRODUCTS, "total": len(MOCK_PRODUCTS)}
    if tool_name == "get_product":
        return MOCK_PRODUCTS[0]
    if tool_name == "top_products":
        return {"products": MOCK_PRODUCTS[:2], "period": args.get("period", "week")}
    if tool_name == "list_reservations":
        return {"reservations": []}
    if tool_name == "set_product_unavailable":
        return {"success": True, "product_id": args.get("product_id"), "available": False}
    if tool_name == "set_product_available":
        return {"success": True, "product_id": args.get("product_id"), "available": True}
    if tool_name == "bump_product_price":
        return {"success": True, "product_id": args.get("product_id"), "new_price": 7.15}
    if tool_name == "open_support_ticket":
        return {"success": True, "ticket_id": "TK-123"}
    if tool_name == "list_locations":
        return {"locations": [{"id": "loc1", "name": "Liados Centro"}]}
    if tool_name == "list_printers":
        return {"printers": []}
    if tool_name == "list_integrations":
        return {"integrations": []}
    if tool_name == "search_kb":
        return {"articles": [{"title": "Cómo configurar impresoras", "url": "https://help.last.app/..."}]}
    if tool_name == "reservation_patterns":
        return {"patterns": {"avg_occupancy": 0.72, "cancellation_rate": 0.12}}
    raise RuntimeError(f"Tool no mockeada: {tool_name}")


# ─── Tests de caché ─────────────────────────────────────────────────

def test_list_products_caching(mock_mcp_server):
    server = mock_mcp_server["server"]
    mock_call = mock_mcp_server["call_remote"]

    result1 = server.list_products(limit=10)
    result2 = server.list_products(limit=10)

    assert result1 == result2
    assert json.loads(result1)["products"] == MOCK_PRODUCTS
    assert mock_call.call_count == 1

    result3 = server.list_products(limit=5)
    assert mock_call.call_count == 2


def test_cache_different_args(mock_mcp_server):
    server = mock_mcp_server["server"]
    mock_call = mock_mcp_server["call_remote"]

    server.list_products(location_id="loc1")
    server.list_products(location_id="loc2")
    assert mock_call.call_count == 2


# ─── Tests pending_action ───────────────────────────────────────────

def test_set_product_unavailable_creates_token(mock_mcp_server):
    server = mock_mcp_server["server"]
    result_json = server.set_product_unavailable("p1", reason="agotado")
    result = json.loads(result_json)
    assert result["status"] == "pending_confirmation"
    assert result["action"] == "set_product_unavailable"
    assert "confirmation_token" in result
    assert result["expires_in_seconds"] == 300
    assert len(server._pending_actions) == 1


def test_confirm_action_executes(mock_mcp_server):
    server = mock_mcp_server["server"]
    r = json.loads(server.set_product_unavailable("p1", reason="agotado"))
    token = r["confirmation_token"]

    confirm = json.loads(server.confirm_action(token))
    assert confirm["status"] == "executed"
    assert confirm["action"] == "set_product_unavailable"
    assert confirm["result"]["success"] is True
    assert len(server._pending_actions) == 0


def test_confirm_action_bad_token(mock_mcp_server):
    server = mock_mcp_server["server"]
    result = json.loads(server.confirm_action("token-falso"))
    assert result["status"] == "error"


def test_cancel_action(mock_mcp_server):
    server = mock_mcp_server["server"]
    r = json.loads(server.set_product_available("p3"))
    token = r["confirmation_token"]

    result = json.loads(server.cancel_action(token))
    assert result["status"] == "cancelled"
    assert result["action"] == "set_product_available"
    assert len(server._pending_actions) == 0


def test_cancel_action_bad_token(mock_mcp_server):
    server = mock_mcp_server["server"]
    result = json.loads(server.cancel_action("token-falso"))
    assert result["status"] == "error"


def test_action_expires(mock_mcp_server):
    server = mock_mcp_server["server"]
    r = json.loads(server.set_product_unavailable("p1"))
    token = r["confirmation_token"]

    server._pending_actions[token]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    result = json.loads(server.confirm_action(token))
    assert result["status"] == "error"


# ─── Tests de otras tools ──────────────────────────────────────────

def test_bump_product_price_pending(mock_mcp_server):
    server = mock_mcp_server["server"]
    result = json.loads(server.bump_product_price("p1", 5.0))
    assert result["status"] == "pending_confirmation"
    assert result["details"]["percent"] == 5.0


def test_open_support_ticket_pending(mock_mcp_server):
    server = mock_mcp_server["server"]
    result = json.loads(server.open_support_ticket("Error TPV", "No imprime tickets"))
    assert result["status"] == "pending_confirmation"
    assert "confirmation_token" in result


def test_list_locations(mock_mcp_server):
    server = mock_mcp_server["server"]
    result = json.loads(server.list_locations())
    assert "locations" in result


def test_search_kb(mock_mcp_server):
    server = mock_mcp_server["server"]
    result = json.loads(server.search_kb("impresoras"))
    assert "articles" in result


def test_reservation_patterns(mock_mcp_server):
    server = mock_mcp_server["server"]
    result = json.loads(server.reservation_patterns(period="week"))
    assert "patterns" in result


def test_multiple_pending_actions_independent(mock_mcp_server):
    server = mock_mcp_server["server"]
    r1 = json.loads(server.set_product_unavailable("p1"))
    r2 = json.loads(server.bump_product_price("p2", 10.0))
    assert r1["confirmation_token"] != r2["confirmation_token"]
    assert len(server._pending_actions) == 2

    c1 = json.loads(server.confirm_action(r1["confirmation_token"]))
    assert c1["status"] == "executed"
    assert len(server._pending_actions) == 1

    c2 = json.loads(server.cancel_action(r2["confirmation_token"]))
    assert c2["status"] == "cancelled"
    assert len(server._pending_actions) == 0
