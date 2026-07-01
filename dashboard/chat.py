"""
Wrapper de chat CONVERSACIONAL sobre agent.py (sin modificar agent.py).

Diferencias vs agent.ask():
- Mantiene historial por turno -> soporta el flujo de confirmacion en 2 pasos.
- Detecta tokens de confirmacion devueltos por tools destructivas.
- Devuelve metadatos (pending_confirmation, tools_used) para que el frontend
  muestre el boton "Confirmar accion".

El historial viaja en el payload (no hay estado de sesion en servidor) -> el
frontend lo guarda en localStorage y lo reenvia en cada mensaje.
"""
import json

from dashboard.agent import (
    call_llm, execute_tool, TOOLS_SCHEMA, SYSTEM_PROMPT
)

# Confirmacion/cancelacion directas (sin pasar por el LLM) para el 2º paso.
try:
    from agente.mcp.lastapp_server import confirm_action, cancel_action
    _CONFIRM = confirm_action
    _CANCEL = cancel_action
except Exception:
    _CONFIRM = None
    _CANCEL = None

MAX_ITERS = 6


def _extract_pending(tool_result_str: str, tool_name: str):
    """Si una tool destructiva devolvio un confirmation_token, lo captura."""
    try:
        parsed = json.loads(tool_result_str)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    token = parsed.get("confirmation_token") or parsed.get("token")
    if not token:
        return None
    return {
        "token": token,
        "action": tool_name,
        "message": parsed.get("message") or parsed.get("summary")
                   or f"Accion pendiente: {tool_name}",
        "detail": parsed,
    }


def chat(question: str, history: list = None) -> dict:
    """
    Pipeline conversacional: question (+ historial) -> LLM -> tools (loop).

    Devuelve:
      {
        "reply": str,
        "pending_confirmation": dict | None,  # si una tool destructiva pidio confirmar
        "tools_used": [str],
        "history": [...]  # historial actualizado para reenviar
      }
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        # Sanitizar: solo roles validos y sin system duplicado.
        for m in history:
            if m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m.get("content", "")})
    messages.append({"role": "user", "content": question})

    pending = None
    tools_used = []
    new_history = list(messages[1:])  # todo lo conversado (sin system)

    for _ in range(MAX_ITERS):
        result = call_llm(messages)
        choice = result["choices"][0]
        msg = choice["message"]

        if msg.get("tool_calls"):
            messages.append(msg)
            for tool_call in msg["tool_calls"]:
                fn_name = tool_call["function"]["name"]
                try:
                    fn_args = json.loads(tool_call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    fn_args = {}
                tool_result = execute_tool(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result,
                })
                tools_used.append(fn_name)
                if not pending:
                    pending = _extract_pending(tool_result, fn_name)
        else:
            reply = msg.get("content", "") or ""
            updated_history = new_history + [{"role": "assistant", "content": reply}]
            return {
                "reply": reply,
                "pending_confirmation": pending,
                "tools_used": tools_used,
                "history": updated_history,
            }

    return {
        "reply": "Lo siento, no he podido procesar tu pregunta tras varios intentos.",
        "pending_confirmation": pending,
        "tools_used": tools_used,
        "history": new_history,
    }


def confirm(confirmation_token: str) -> dict:
    """Ejecuta una accion pendiente directamente (2º paso del flujo)."""
    if not _CONFIRM:
        return {"error": "Confirmacion no disponible (Last.app MCP no cargado)"}
    raw = _CONFIRM(confirmation_token=confirmation_token)
    try:
        return json.loads(raw)
    except Exception:
        return {"result": raw}


def cancel(confirmation_token: str) -> dict:
    """Cancela una accion pendiente."""
    if not _CANCEL:
        return {"error": "Cancelacion no disponible (Last.app MCP no cargado)"}
    raw = _CANCEL(confirmation_token=confirmation_token)
    try:
        return json.loads(raw)
    except Exception:
        return {"result": raw}
