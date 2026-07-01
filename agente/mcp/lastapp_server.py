"""

MCP server que envuelve https://api.last.app/mcp con caché,
normalización y patrón de confirmación para acciones.

Tools de LECTURA (ejecutan directo, con caché TTL):
  list_products       — Lista productos del catálogo              (TTL: 5 min)
  get_product         — Detalle de un producto                    (TTL: 5 min)
  top_products        — Productos más vendidos                    (TTL: 5 min)
  list_reservations   — Reservas en rango de fechas               (TTL: 2 min)
  reservation_patterns — Patrones de ocupación/cancelación        (TTL: 30 min)
  list_locations      — Ubicaciones de la organización            (TTL: 1 hora)
  list_printers       — Impresoras configuradas                   (TTL: 1 min)
  list_integrations   — Integraciones activas                     (TTL: 30 min)
  search_kb           — Busca en la base de conocimiento          (TTL: 1 hora)

Tools de ACCIÓN (devuelven pending_action, NO ejecutan):
  set_product_unavailable  — Marcar producto no disponible       (pending 5 min)
  set_product_available    — Marcar producto disponible          (pending 5 min)
  bump_product_price       — Subir precio de un producto         (pending 5 min)
  open_support_ticket      — Abrir ticket de soporte             (pending 5 min)

Tools de CONFIRMACIÓN:
  confirm_action  — Ejecuta una acción pendiente
  cancel_action   — Cancela una acción pendiente

MAPEO DE TOOLS: las tools propias → tools del MCP remoto.
Este diccionario se actualiza con la salida real de tools/list tras handshake.
Si una tool remota no existe, la llamada falla con error descriptivo.

IMPORTANTE: estos nombres son conjeturas basadas en la documentación pública.
Cuando se obtengan credenciales OAuth, ejecutar:
  python -c "from agente.mcp.lastapp_client import LastAppClient; from agente.mcp.lastapp_auth import get_token; c=LastAppClient(get_token); c.initialize(); print(c.discover_tools())"
Y actualizar _TOOL_MAP con los nombres reales.
"""
import os
import sys
import json
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
import threading
from mcp.server.fastmcp import FastMCP

from lastapp_client import LastAppClient

logger = logging.getLogger(__name__)

mcp = FastMCP("lastapp")

_client: LastAppClient | None = None
_client_available: bool | None = None

TOOL_MAP = {
    "list_products": "get_catalog_items",
    "get_product": "get_catalog_item",
    "top_products": "get_top_selling_products",
    "list_reservations": "list_reservations",
    "reservation_patterns": "get_reservation_patterns",
    "list_locations": "list_locations",
    "list_printers": "list_printers",
    "list_integrations": "list_integrations",
    "search_kb": "search_knowledge_base",
    "set_product_unavailable": "update_catalog_item",
    "set_product_available": "update_catalog_item",
    "bump_product_price": "update_catalog_item",
    "open_support_ticket": "create_support_ticket",
}

_message_cache = {}
# _cache_lock = False  # unused, removed


def _check_or_init_client():
    global _client, _client_available
    if _client_available is not None:
        return _client_available

    try:
        from lastapp_auth import get_token
        token = get_token()
        _client = LastAppClient(auth_token_getter=get_token)
        _client.initialize()
        logger.info("Cliente LastApp MCP inicializado correctamente")
        _client_available = True

        tools = _client.discover_tools()
        logger.info("Tools remotas disponibles: %s",
                     ", ".join(t.get("name", "?") for t in tools))
        remote_names = {t.get("name") for t in tools}
        for our_name, remote_name in list(TOOL_MAP.items()):
            if remote_name not in remote_names:
                matching = [t.get("name") for t in tools
                            if remote_name.lower() in t.get("name", "").lower()]
                if matching:
                    TOOL_MAP[our_name] = matching[0]
                    logger.info("Mapeo corregido: %s -> %s (era %s)",
                                our_name, matching[0], remote_name)
                else:
                    logger.warning("Tool remota '%s' no encontrada para '%s'. Las tools disponibles son: %s",
                                   remote_name, our_name, ", ".join(remote_names))
        return True
    except Exception as e:
        logger.warning("Cliente LastApp MCP no disponible: %s", e)
        _client_available = False
        return False


def _call_remote(tool_name: str, args: dict) -> dict:
    if not _check_or_init_client() or _client is None:
        raise RuntimeError(
            "Cliente LastApp MCP no disponible. Configura OAuth siguiendo "
            "README > 'Last.app MCP setup'."
        )
    remote_name = TOOL_MAP.get(tool_name, tool_name)
    return _client.call_tool(remote_name, args)


def cached(ttl_seconds: int):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = json.dumps(
                {"fn": fn.__name__, "args": args, "kwargs": kwargs},
                sort_keys=True, default=str,
            )
            now = time.time()
            with _msg_cache_lock:
                if key in _message_cache:
                    value, expires_at = _message_cache[key]
                    if now < expires_at:
                        return value
                value = fn(*args, **kwargs)
                _message_cache[key] = (value, now + ttl_seconds)
                # A-1: limit cache size (LRU-style: remove oldest if over 1000)
                if len(_message_cache) > 1000:
                    try:
                        oldest = min(_message_cache, key=lambda k: _message_cache[k][1])
                        del _message_cache[oldest]
                    except (ValueError, KeyError):
                        pass
            return value
        return wrapper
    return decorator


_pending_actions = {}

# Thread-safety locks
_msg_cache_lock = threading.Lock()
_pending_lock = threading.Lock()
_tool_map_lock = threading.Lock()
PENDING_TTL = 300


def _clean_expired():
    now = datetime.now(timezone.utc)
    with _pending_lock:
        expired = [t for t, a in _pending_actions.items()
                   if a["expires_at"] < now]
        for t in expired:
            del _pending_actions[t]


def _normalize_result(result: dict) -> str:
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if isinstance(result, str):
        try:
            json.loads(result)
            return result
        except (json.JSONDecodeError, ValueError):
            return json.dumps({"result": result}, ensure_ascii=False)
    return json.dumps({"result": result}, ensure_ascii=False, indent=2, default=str)


# ─── Tools de lectura ───────────────────────────────────────────────

@mcp.tool()
@cached(ttl_seconds=300)
def list_products(location_id: str = "", available_only: bool = False, limit: int = 50) -> str:
    """Lista productos del catálogo. Si available_only=True, filtra los disponibles."""
    args = {"limit": limit}
    if location_id:
        args["location_id"] = location_id
    result = _call_remote("list_products", args)
    if available_only and isinstance(result, dict):
        items = result.get("items") or result.get("products") or result.get("data") or []
        if isinstance(items, list):
            items = [i for i in items if i.get("available") or i.get("is_available")]
            result = {"products": items, "total": len(items)}
    return _normalize_result(result)


@mcp.tool()
@cached(ttl_seconds=300)
def get_product(product_id: str) -> str:
    """Detalle completo de un producto (precio, stock, disponibilidad)."""
    result = _call_remote("get_product", {"product_id": product_id})
    return _normalize_result(result)


@mcp.tool()
@cached(ttl_seconds=300)
def top_products(period: str = "week", location_id: str = "", limit: int = 10) -> str:
    """Productos más vendidos. period ∈ day, week, month, quarter."""
    args = {"period": period, "limit": limit}
    if location_id:
        args["location_id"] = location_id
    result = _call_remote("top_products", args)
    return _normalize_result(result)


@mcp.tool()
@cached(ttl_seconds=120)
def list_reservations(date_from: str, date_to: str, location_id: str = "") -> str:
    """Reservas en un rango. Fechas ISO YYYY-MM-DD."""
    args = {"date_from": date_from, "date_to": date_to}
    if location_id:
        args["location_id"] = location_id
    result = _call_remote("list_reservations", args)
    return _normalize_result(result)


@mcp.tool()
@cached(ttl_seconds=1800)
def reservation_patterns(period: str = "month") -> str:
    """Patrones de ocupación/cancelación. period ∈ week, month, quarter."""
    result = _call_remote("reservation_patterns", {"period": period})
    return _normalize_result(result)


@mcp.tool()
@cached(ttl_seconds=3600)
def list_locations() -> str:
    """Ubicaciones (locales) de la organización."""
    result = _call_remote("list_locations", {})
    return _normalize_result(result)


@mcp.tool()
@cached(ttl_seconds=60)
def list_printers(location_id: str = "") -> str:
    """Impresoras configuradas por local, con estado."""
    args = {}
    if location_id:
        args["location_id"] = location_id
    result = _call_remote("list_printers", args)
    return _normalize_result(result)


@mcp.tool()
@cached(ttl_seconds=1800)
def list_integrations() -> str:
    """Integraciones activas en la organización."""
    result = _call_remote("list_integrations", {})
    return _normalize_result(result)


@mcp.tool()
@cached(ttl_seconds=3600)
def search_kb(query: str, limit: int = 5) -> str:
    """Busca artículos en la base de conocimiento de Last.app."""
    result = _call_remote("search_kb", {"query": query, "limit": limit})
    return _normalize_result(result)


# ─── Tools de acción (pending) ──────────────────────────────────────

@mcp.tool()
def set_product_unavailable(product_id: str, location_id: str = "", reason: str = "") -> str:
    """Marca un producto como no disponible. Requiere confirmación humana."""
    _clean_expired()
    token = str(uuid.uuid4())
    _pending_actions[token] = {
        "tool": "set_product_unavailable",
        "args": {"product_id": product_id, "location_id": location_id, "reason": reason},
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=PENDING_TTL),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps({
        "status": "pending_confirmation",
        "action": "set_product_unavailable",
        "confirmation_token": token,
        "expires_in_seconds": PENDING_TTL,
        "details": {"product_id": product_id, "location_id": location_id or "todos", "reason": reason},
        "message": "Para confirmar, ejecuta confirm_action con este token. Caduca en 5 minutos.",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def set_product_available(product_id: str, location_id: str = "") -> str:
    """Marca un producto como disponible. Requiere confirmación humana."""
    _clean_expired()
    token = str(uuid.uuid4())
    _pending_actions[token] = {
        "tool": "set_product_available",
        "args": {"product_id": product_id, "location_id": location_id},
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=PENDING_TTL),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps({
        "status": "pending_confirmation",
        "action": "set_product_available",
        "confirmation_token": token,
        "expires_in_seconds": PENDING_TTL,
        "details": {"product_id": product_id, "location_id": location_id or "todos"},
        "message": "Para confirmar, ejecuta confirm_action con este token. Caduca en 5 minutos.",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def bump_product_price(product_id: str, percent: float, location_id: str = "") -> str:
    """Sube el precio de un producto en el porcentaje indicado. Requiere confirmación humana."""
    _clean_expired()
    token = str(uuid.uuid4())
    _pending_actions[token] = {
        "tool": "bump_product_price",
        "args": {"product_id": product_id, "percent": percent, "location_id": location_id},
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=PENDING_TTL),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps({
        "status": "pending_confirmation",
        "action": "bump_product_price",
        "confirmation_token": token,
        "expires_in_seconds": PENDING_TTL,
        "details": {"product_id": product_id, "percent": percent, "location_id": location_id or "todos"},
        "message": f"Para confirmar la subida del {percent}%, ejecuta confirm_action con este token. Caduca en 5 minutos.",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def open_support_ticket(subject: str, description: str, priority: str = "normal") -> str:
    """Abre un ticket de soporte en Last.app. Requiere confirmación humana."""
    _clean_expired()
    token = str(uuid.uuid4())
    _pending_actions[token] = {
        "tool": "open_support_ticket",
        "args": {"subject": subject, "description": description, "priority": priority},
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=PENDING_TTL),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps({
        "status": "pending_confirmation",
        "action": "open_support_ticket",
        "confirmation_token": token,
        "expires_in_seconds": PENDING_TTL,
        "details": {"subject": subject, "priority": priority},
        "message": "Para confirmar la apertura del ticket, ejecuta confirm_action con este token. Caduca en 5 minutos.",
    }, ensure_ascii=False, indent=2)


# ─── Tools de confirmación ──────────────────────────────────────────

@mcp.tool()
def confirm_action(confirmation_token: str) -> str:
    """Ejecuta una acción pendiente. Devuelve el resultado de la acción."""
    _clean_expired()
    with _pending_lock:
        if confirmation_token not in _pending_actions:
            return json.dumps({
                "status": "error",
                "reason": "Token no encontrado o ha expirado (TTL: 5 minutos).",
            }, ensure_ascii=False)
        action = _pending_actions.pop(confirmation_token)
    try:
        result = _call_remote(action["tool"], action["args"])
        return json.dumps({
            "status": "executed",
            "action": action["tool"],
            "result": result,
        }, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "action": action["tool"],
            "error": str(e),
        }, ensure_ascii=False, indent=2)


@mcp.tool()
def cancel_action(confirmation_token: str) -> str:
    """Cancela una acción pendiente."""
    _clean_expired()
    with _pending_lock:
        if confirmation_token not in _pending_actions:
            return json.dumps({
                "status": "error",
                "reason": "Token no encontrado o ha expirado (TTL: 5 minutos).",
            }, ensure_ascii=False)
        action = _pending_actions.pop(confirmation_token)
    return json.dumps({
        "status": "cancelled",
        "action": action["tool"],
        "message": f"Acción '{action['tool']}' cancelada.",
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
