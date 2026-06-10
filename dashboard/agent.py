"""
Agente de consultas financieras para Liados.
Usa OpenCode Go (deepseek-v4-flash) con function-calling contra las tools del MCP.
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

OPENCODE_GO_URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "deepseek-v4-flash"

TOOLS_SCHEMA = [
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

SYSTEM_PROMPT = """Eres el asistente financiero del restaurante Liados.

Respondes en espanol de Espana, de forma clara y concisa. Usas los importes en euros.

Tienes 6 herramientas para consultar la base de datos de facturas:
- list_invoices, get_invoice, monthly_summary, vendor_summary, pending_payments, count_invoices

REGLAS:
1. Cada pregunta es INDEPENDIENTE. No asumas contexto de mensajes anteriores.
2. Si el usuario no especifica fecha, asume el mes actual.
3. Si dice "el mes pasado" o similar, usa el mes anterior.
4. Si dice "este año" o "en 2026", usa el año actual.
5. Si la pregunta es ambigua (ej: "cuanto he gastado?" sin periodo), pregunta antes de asumir.
6. Los datos de BD son SOLO LECTURA. NO intentes modificar nada.
7. Si una tool devuelve error o lista vacia, dilo claramente. No inventes datos.
8. Para importes grandes, redondea a 2 decimales y usa separador de millares (ej: 12.450,75).
9. Si el usuario pregunta por un analisis o recomendacion, basa tu respuesta SOLO en los datos que devuelven las tools. No inventes tendencias.
10. Si no sabes la respuesta con los datos disponibles, di "No tengo datos suficientes para responder a eso" en vez de inventar.
"""

TOOL_MAP = {
    "list_invoices": list_invoices,
    "get_invoice": get_invoice,
    "monthly_summary": monthly_summary,
    "vendor_summary": vendor_summary,
    "pending_payments": pending_payments,
    "count_invoices": count_invoices,
}


def call_llm(messages: list) -> dict:
    """Llama a OpenCode Go con function-calling."""
    api_key = os.getenv("OPENCODE_API_KEY")
    if not api_key:
        raise RuntimeError("OPENCODE_API_KEY no esta en .env")

    resp = requests.post(
        OPENCODE_GO_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": MODEL,
            "messages": messages,
            "tools": TOOLS_SCHEMA,
            "tool_choice": "auto",
            "temperature": 0.1
        },
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def execute_tool(name: str, args: dict) -> str:
    """Ejecuta una tool del MCP y devuelve su resultado como string."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Tool '{name}' no existe"})
    try:
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
        choice = result["choices"][0]
        msg = choice["message"]

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
