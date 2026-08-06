"""
Wrapper de chat CONVERSACIONAL sobre agent.py (sin modificar agent.py).

Diferencias vs agent.ask():
- Mantiene historial por turno -> soporta el flujo de confirmacion en 2 pasos.
- Detecta tokens de confirmacion devueltos por tools destructivas.
- Devuelve metadatos (pending_confirmation, tools_used) para que el frontend
  muestre el boton "Confirmar accion".

El historial viaja en el payload (no hay estado de sesion en servidor) -> el
frontend lo guarda en localStorage y lo reenvia en cada mensaje.

FIX 2026-07-01 (ciclo 9): inyecta fecha actual al system prompt y al primer
mensaje del usuario. Sin esto el LLM alucinaba fechas (e.g. diciembre 2025
cuando estamos en julio 2026) porque no le dabamos contexto temporal.
"""
import json
from datetime import datetime, timezone

from dashboard.agent import (
    call_llm, execute_tool, TOOLS_SCHEMA, SYSTEM_PROMPT,
    OPENCODE_GO_URL, MODEL,
)

# Confirmacion/cancelacion directas (sin pasar por el LLM) para el 2o paso.
try:
    from agente.mcp.lastapp_server import confirm_action, cancel_action
    _CONFIRM = confirm_action
    _CANCEL = cancel_action
    import logging
    logging.getLogger(__name__).info("Last.app MCP cargado: confirm/cancel disponibles")
except Exception as e:
    _CONFIRM = None
    _CANCEL = None
    import logging
    logging.getLogger(__name__).warning("Last.app MCP NO cargado (puede afectar flujo 2-paso): " + str(e))

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
                   or "Accion pendiente: " + tool_name,
        "detail": parsed,
    }


def _now_str():
    """Fecha actual del sistema en formato estandar (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def chat(question: str, history: list = None) -> dict:
    """
    Pipeline conversacional: question (+ historial) -> LLM -> tools (loop).

    Devuelve:
      {
        "reply": str,
        "pending_confirmation": dict | None,
        "tools_used": [str],
        "history": [...]
      }
    """
    now_str = _now_str()
    system_with_date = (
        SYSTEM_PROMPT
        + "\n\n---\nFecha actual del sistema: "
        + now_str
        + "\nSi el usuario no especifica periodo, asume el mes/ano en curso basandote en esta fecha."
    )
    messages = [{"role": "system", "content": system_with_date}]
    if history:
        for m in history:
            if m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m.get("content", "")})

    if not history and question:
        question_with_date = "[Fecha actual: " + now_str + "] " + question
    else:
        question_with_date = question or ""
    messages.append({"role": "user", "content": question_with_date})

    pending = None
    tools_used = []
    new_history = list(messages[1:])

    for _ in range(MAX_ITERS):
        try:
            result = call_llm(messages)
            if not result.get("choices"):
                raise RuntimeError("LLM devolvio sin choices: " + str(result))
            choice = result["choices"][0]
            msg = choice["message"]
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Error en LLM call: " + str(e))
            return {
                "reply": "Lo siento, hubo un error al procesar tu pregunta (LLM). Intentalo de nuevo.",
                "pending_confirmation": pending,
                "tools_used": tools_used,
                "history": messages[1:] + [{"role": "assistant", "content": "(error del LLM)"}],
            }

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
        "reply": "Lo siento, no he podido procesar tu pregunta tras varios intentos. Intenta reformularla con menos ambiguedad o con un periodo explicito (ej: 'este mes' o 'marzo 2026').",
        "pending_confirmation": pending,
        "tools_used": tools_used,
        "history": new_history,
    }


def _call_llm_stream(messages: list):
    """Llama a OpenCode Go con stream=True. Generador de deltas (chunks)."""
    import os
    import requests
    api_key = os.getenv("MINIMAX_API_KEY") or os.getenv("OPENCODE_API_KEY")
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY/OPENCODE_API_KEY no esta en .env")
    try:
        resp = requests.post(
            OPENCODE_GO_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            json={
                "model": MODEL,
                "messages": messages,
                "tools": TOOLS_SCHEMA,
                "tool_choice": "auto",
                "temperature": 0.1,
                "stream": True,
            },
            timeout=(10, 120),
            stream=True,
        )
        resp.raise_for_status()
    except requests.exceptions.ReadTimeout:
        raise RuntimeError("Timeout del LLM (>120s) durante streaming")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error de conexion con el LLM: {e}")
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if choices:
                yield choices[0].get("delta", {}) or {}
    finally:
        try:
            resp.close()
        except Exception:
            pass


def chat_stream(question: str, history: list = None):
    """
    Pipeline conversacional STREAMING. Generador que yields eventos:
      {"type": "token", "text": "..."}        -> token de la respuesta final
      {"type": "tool",  "name": "..."}        -> se esta ejecutando una tool
      {"type": "done",  "reply": "...", "pending_confirmation": ..., "tools_used": [...], "history": [...]}
      {"type": "error", "message": "..."}
    """
    now_str = _now_str()
    system_with_date = (
        SYSTEM_PROMPT
        + "\n\n---\nFecha actual del sistema: " + now_str
        + "\nSi el usuario no especifica periodo, asume el mes/ano en curso basandote en esta fecha."
    )
    messages = [{"role": "system", "content": system_with_date}]
    if history:
        for m in history:
            if m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m.get("content", "")})
    question_with_date = (
        ("[Fecha actual: " + now_str + "] " + question) if (not history and question) else (question or "")
    )
    messages.append({"role": "user", "content": question_with_date})

    new_history = list(messages[1:])
    pending = None
    tools_used = []

    for _ in range(MAX_ITERS):
        content_parts = []
        tool_acc = {}  # index -> {"id","name","arguments"}

        try:
            for delta in _call_llm_stream(messages):
                if delta.get("content"):
                    content_parts.append(delta["content"])
                    yield {"type": "token", "text": delta["content"]}
                tcs = delta.get("tool_calls")
                if tcs:
                    for tc in tcs:
                        idx = tc.get("index", 0)
                        if idx not in tool_acc:
                            tool_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.get("id"):
                            tool_acc[idx]["id"] = tc["id"]
                        fn = tc.get("function", {}) or {}
                        if fn.get("name"):
                            tool_acc[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_acc[idx]["arguments"] += fn["arguments"]
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Error en streaming LLM: " + str(e))
            yield {"type": "error", "message": f"Error del modelo: {e}"}
            return

        reply = "".join(content_parts)

        if tool_acc:
            tcs_sorted = [tool_acc[i] for i in sorted(tool_acc)]
            assistant_msg = {
                "role": "assistant",
                "content": reply or None,
                "tool_calls": [
                    {"id": t["id"], "type": "function",
                     "function": {"name": t["name"], "arguments": t["arguments"]}}
                    for t in tcs_sorted
                ],
            }
            messages.append(assistant_msg)
            for t in tcs_sorted:
                yield {"type": "tool", "name": t["name"]}
                try:
                    fn_args = json.loads(t["arguments"] or "{}")
                except json.JSONDecodeError:
                    fn_args = {}
                tool_result = execute_tool(t["name"], fn_args)
                messages.append({"role": "tool", "tool_call_id": t["id"], "content": tool_result})
                tools_used.append(t["name"])
                if not pending:
                    pending = _extract_pending(tool_result, t["name"])
        else:
            updated_history = new_history + [{"role": "assistant", "content": reply}]
            yield {
                "type": "done",
                "reply": reply,
                "pending_confirmation": pending,
                "tools_used": tools_used,
                "history": updated_history,
            }
            return

    yield {
        "type": "done",
        "reply": "Lo siento, no he podido procesar tu pregunta tras varios intentos.",
        "pending_confirmation": pending,
        "tools_used": tools_used,
        "history": new_history,
    }


def confirm(confirmation_token: str) -> dict:
    """Ejecuta una accion pendiente directamente (2o paso del flujo)."""
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
