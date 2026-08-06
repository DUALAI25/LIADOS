"""
Agente de consultas para Liados.
Usa MiniMax (con fallback OpenCode) con function-calling contra dos MCP servers:
  - invoices_server: facturas (Postgres)
  - lastapp_server: operativa del restaurante via MCP oficial de Last.app
"""
import os
import json
import requests
from typing import Any
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agente', 'mcp'))
from invoices_server import (
    list_invoices, get_invoice, monthly_summary,
    vendor_summary, pending_payments, count_invoices
)

_lastapp_available = False
_lastapp_tools = {}
try:
    from lastapp_server import (
        list_products, get_product, top_products,
        list_reservations, reservation_patterns,
        list_locations, list_printers, list_integrations, search_kb,
        set_product_unavailable, set_product_available,
        bump_product_price, open_support_ticket,
        confirm_action, cancel_action,
    )
    _lastapp_available = True
    _lastapp_tools = {
        "list_products": list_products,
        "get_product": get_product,
        "top_products": top_products,
        "list_reservations": list_reservations,
        "reservation_patterns": reservation_patterns,
        "list_locations": list_locations,
        "list_printers": list_printers,
        "list_integrations": list_integrations,
        "search_kb": search_kb,
        "set_product_unavailable": set_product_unavailable,
        "set_product_available": set_product_available,
        "bump_product_price": bump_product_price,
        "open_support_ticket": open_support_ticket,
        "confirm_action": confirm_action,
        "cancel_action": cancel_action,
    }
except ImportError:
    pass

MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1").rstrip("/")
OPENCODE_GO_URL = MINIMAX_BASE_URL + "/chat/completions"
MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")

# ─── Tools de facturas (invoices_server) ────────────────────────────

INVOICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_invoices",
            "description": "Lista facturas con filtros. Devuelve hasta N facturas con sus datos basicos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["expense", "income", "all"], "default": "all"},
                    "status": {"type": "string", "enum": ["pending", "processed", "paid", "failed", "duplicate", "all"], "default": "all"},
                    "vendor_name": {"type": "string", "default": ""},
                    "category": {"type": "string", "default": ""},
                    "date_from": {"type": "string", "default": ""},
                    "date_to": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 20}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_invoice",
            "description": "Detalle completo de una factura por ID o numero.",
            "parameters": {
                "type": "object",
                "properties": {"identifier": {"type": "string"}},
                "required": ["identifier"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "monthly_summary",
            "description": "Resumen mensual: ingresos vs gastos por mes. Si no se pasa year, devuelve el año actual.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "default": 0},
                    "type": {"type": "string", "enum": ["expense", "income", "all"], "default": "all"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "vendor_summary",
            "description": "Top proveedores por gasto total. Util para 'en que me gasto mas?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                    "year": {"type": "integer", "default": 0},
                    "type": {"type": "string", "enum": ["expense", "income", "all"], "default": "expense"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pending_payments",
            "description": "Facturas de gasto sin pagar, ordenadas por vencimiento.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 20}}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "count_invoices",
            "description": "Cuenta rapida de facturas con filtros. Mas rapido que listar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["expense", "income", "all"], "default": "all"},
                    "status": {"type": "string", "default": "all"},
                    "date_from": {"type": "string", "default": ""},
                    "date_to": {"type": "string", "default": ""}
                }
            }
        }
    }
]

# ─── Tools de Last.app MCP ──────────────────────────────────────────

LASTAPP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_products",
            "description": "Lista productos del catalogo del restaurante (carta). Puedes filtrar por local y disponibilidad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_id": {"type": "string", "default": ""},
                    "available_only": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "default": 50}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_product",
            "description": "Detalle completo de un producto: precio, disponibilidad, stock por local.",
            "parameters": {
                "type": "object",
                "properties": {"product_id": {"type": "string"}},
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "top_products",
            "description": "Productos mas vendidos en un periodo. period: day, week, month, quarter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": ["day", "week", "month", "quarter"], "default": "week"},
                    "location_id": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 10}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_reservations",
            "description": "Reservas en rango de fechas. Fechas en formato YYYY-MM-DD.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "location_id": {"type": "string", "default": ""}
                },
                "required": ["date_from", "date_to"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reservation_patterns",
            "description": "Patrones de ocupacion y cancelacion por periodo. period: week, month, quarter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": ["week", "month", "quarter"], "default": "month"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_locations",
            "description": "Ubicaciones (locales) de la organizacion Liados.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_printers",
            "description": "Impresoras configuradas por local, con su estado actual.",
            "parameters": {
                "type": "object",
                "properties": {"location_id": {"type": "string", "default": ""}}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_integrations",
            "description": "Integraciones activas en la organizacion (delivery, ERP, etc).",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "Busca en la base de conocimiento de Last.app (ayuda, guias, FAQs).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_product_unavailable",
            "description": "Marca un producto como NO disponible. ACCION DESTRUCTIVA: devuelve un confirmation_token. No se ejecuta hasta que el usuario confirme explicitamente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "location_id": {"type": "string", "default": ""},
                    "reason": {"type": "string", "default": ""}
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_product_available",
            "description": "Marca un producto como disponible. ACCION DESTRUCTIVA: devuelve un confirmation_token.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "location_id": {"type": "string", "default": ""}
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bump_product_price",
            "description": "Sube el precio de un producto en un porcentaje. ACCION DESTRUCTIVA: devuelve confirmation_token con el diff de precio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "percent": {"type": "number"},
                    "location_id": {"type": "string", "default": ""}
                },
                "required": ["product_id", "percent"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_support_ticket",
            "description": "Abre un ticket de soporte en Last.app. ACCION DESTRUCTIVA: devuelve confirmation_token.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"}
                },
                "required": ["subject", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_action",
            "description": "Ejecuta una accion pendiente usando el confirmation_token devuelto por una tool destructiva. Usa esto cuando el usuario confirme explicitamente la accion.",
            "parameters": {
                "type": "object",
                "properties": {"confirmation_token": {"type": "string"}},
                "required": ["confirmation_token"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_action",
            "description": "Cancela una accion pendiente usando el confirmation_token.",
            "parameters": {
                "type": "object",
                "properties": {"confirmation_token": {"type": "string"}},
                "required": ["confirmation_token"]
            }
        }
    }
]

TOOLS_SCHEMA = INVOICE_TOOLS + (LASTAPP_TOOLS if _lastapp_available else [])

SYSTEM_PROMPT = """Eres el asistente operativo del restaurante Liados.

Respondes en espanol de Espana, de forma clara y concisa. Usas los importes en euros.

Tienes DOS grupos de herramientas:

FACTURAS (6 tools):
- list_invoices, get_invoice, monthly_summary, vendor_summary, pending_payments, count_invoices
  Consultan facturas historicas en la base de datos.

OPERATIVA LAST.APP (15 tools):
- Lectura: list_products, get_product, top_products, list_reservations, reservation_patterns,
  list_locations, list_printers, list_integrations, search_kb
- Accion (requieren confirmacion): set_product_unavailable, set_product_available,
  bump_product_price, open_support_ticket
- Confirmacion: confirm_action, cancel_action

REGLAS:
1. Cada pregunta es INDEPENDIENTE. No asumas contexto de mensajes anteriores.
2. Si el usuario no especifica fecha, asume el mes actual.
3. Si dice "el mes pasado" o similar, usa el mes anterior.
4. Si dice "este año" o "en 2026", usa el año actual.
5. Si la pregunta es ambigua, pregunta antes de asumir.
6. Los datos de BD (facturas) son SOLO LECTURA. NO intentes modificar nada.
7. Si una tool devuelve error o lista vacia, dilo claramente. No inventes datos.
8. Para importes grandes, redondea a 2 decimales y usa separador de millares (ej: 12.450,75).
9. Si el usuario pregunta por un analisis o recomendacion, basa tu respuesta SOLO en los datos devueltos.
10. Si no sabes la respuesta, di "No tengo datos suficientes para responder a eso".

ACCIONES DESTRUCTIVAS (catalogo, precios, tickets):
11. Cuando el usuario pida una accion destructiva (ej: "marca la tarta de queso como no disponible"),
    llama a la tool correspondiente (ej: set_product_unavailable). Esta devolvera un confirmation_token.
    INFORMA al usuario de que la accion requiere confirmacion y muestrale el token.
12. NO llames a confirm_action sin que el usuario lo pida explicitamente.
13. Si el usuario te da un token de confirmacion, usa confirm_action con ese token.
"""

TOOL_MAP = {
    "list_invoices": list_invoices,
    "get_invoice": get_invoice,
    "monthly_summary": monthly_summary,
    "vendor_summary": vendor_summary,
    "pending_payments": pending_payments,
    "count_invoices": count_invoices,
}
TOOL_MAP.update(_lastapp_tools)


def call_llm(messages: list) -> dict:
    """Llama a OpenCode Go con function-calling."""
    api_key = os.getenv("MINIMAX_API_KEY") or os.getenv("OPENCODE_API_KEY")
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY/OPENCODE_API_KEY no esta en .env")
    endpoint = OPENCODE_GO_URL if os.getenv("MINIMAX_API_KEY") else "https://opencode.ai/zen/go/v1/chat/completions"
    model = MODEL if os.getenv("MINIMAX_API_KEY") else os.getenv("OPENCODE_MODEL", "deepseek-v4-flash")

    resp = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": model,
            "messages": messages,
            "tools": TOOLS_SCHEMA,
            "tool_choice": "auto",
            "temperature": 0.1
        },
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def execute_tool(name: str, args) -> str:
    """Ejecuta una tool del MCP y devuelve su resultado como string.

    Acepta args=None o args={} sin fallar."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Tool '{name}' no existe"})
    try:
        # Normalizar args: None -> {} (algunos LLMs mandan arguments: null)
        if not args:
            args = {}
        return TOOL_MAP[name](**args)
    except Exception as e:
        return json.dumps({"error": str(e)})


def ask(question: str) -> str:
    """Pipeline completo: pregunta -> LLM -> tools (loop) -> respuesta final."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]

    max_iterations = 5
    for _ in range(max_iterations):
        result = call_llm(messages)
        choices = result.get("choices") or []
        if not choices:
            # Sin choices: el LLM devolvio un error o respuesta vacia.
            return "El modelo no devolvio una respuesta valida. Intentalo de nuevo."
        msg = choices[0].get("message", {})

        if msg.get("tool_calls"):
            messages.append(msg)
            for tool_call in msg["tool_calls"]:
                fn_name = tool_call["function"]["name"]
                fn_args = json.loads(tool_call["function"]["arguments"])
                tool_result = execute_tool(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result
                })
        else:
            return msg.get("content", "")

    return "Lo siento, no he podido procesar tu pregunta tras varios intentos."
