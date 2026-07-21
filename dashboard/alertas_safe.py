"""
alertas_safe.py — Helpers blindados para endpoints criticos del dashboard.

Modulo que encapsula la logica fragil de:
  - /api/admin/gmail-status
  - /api/alertas (generador de alertas)
  - /api/alertas/ack (acknowledgement)

Disenado para NUNCA romper:
  - Tabla agent_logs inexistente → fallback a respuesta vacia con OK
  - Tabla sync_control inexistente → fallback
  - Token JSON con schema nuevo/viejo → parse defensivo
  - Query compleja falla → degrada a lista vacia (no 500)
  - Path de credenciales no existe → devuelve "no configurado" sin error
  - Pydantic schema mismatch → mensaje claro, no traceback

Filosofia: un endpoint de notificaciones NUNCA debe romper la UI del dashboard.
Si algo falla, devuelve lo mejor posible y loguea. El usuario puede ver el resto
del dashboard aunque el sistema de alertas este degradado.

Tests: ver tests/test_api.py seccion "v9.0 PRO: blindaje alertas".
"""
import json as _json
import logging as _logging
import os as _os
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path as _Path
from typing import Any as _Any, Dict as _Dict, List as _List, Optional as _Opt

logger = _logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════
# GMAIL STATUS (read-only, NUNCA expone secretos)
# ════════════════════════════════════════════════════════════════════════

def _resolve_creds_dir() -> _Path:
    """Resuelve el directorio de credenciales Gmail con fallback multiple.

    Prioridad:
      1. ENV GMAIL_CREDENTIALS_DIR (para tests/CI/override)
      2. CWD/agente/credentials (produccion con WorkingDirectory=/root/liados)
      3. Path relativo al paquete dashboard (worktree/dev local)
      4. /root/liados/agente/credentials (path absoluto produccion)
      5. Path cualquiera (no falla si no existe)
    """
    override = _os.getenv("GMAIL_CREDENTIALS_DIR", "").strip()
    if override:
        return _Path(override)
    cwd = _Path(_os.getcwd()) / "agente" / "credentials"
    if cwd.is_dir():
        return cwd
    pkg = _Path(__file__).resolve().parent.parent / "agente" / "credentials"
    if pkg.is_dir():
        return pkg
    prod = _Path("/root/liados/agente/credentials")
    if prod.is_dir():
        return prod
    return cwd  # fallback final: devolver path aunque no exista


def _parse_issued_at(issued: _Any) -> _Opt[_dt]:
    """Parse robusto de timestamp en multiples formatos.

    Devuelve None si no se puede parsear (no falla).
    """
    if not issued:
        return None
    try:
        if isinstance(issued, str):
            return _dt.fromisoformat(issued.replace("Z", "+00:00"))
        if isinstance(issued, (int, float)):
            return _dt.fromtimestamp(issued, tz=_tz.utc)
    except (ValueError, TypeError, OSError):
        return None
    return None


def _gmail_token_status(token_data: _Dict, now: _dt) -> _Dict:
    """Evalua estado de un token parseado (dict).

    Devuelve:
      - status: 'OK' | 'STALE' | 'MISSING_TOKEN' | 'PARSE_ERROR'
      - age_days: dias desde emision (o None)
      - campos seguros (nunca expone secrets)
    """
    entry = {
        "has_refresh_token": False,
        "has_access_token": False,
        "client_id": None,
        "scope": None,
        "issued_at": None,
        "last_check": None,
        "age_days": None,
        "status": "PARSE_ERROR",
    }

    if not isinstance(token_data, dict):
        return entry

    # Extraer campos con fallback seguro (nunca lanza KeyError)
    entry["has_refresh_token"] = bool(token_data.get("refresh_token"))
    entry["has_access_token"] = bool(token_data.get("access_token"))
    cid = token_data.get("client_id") or ""
    entry["client_id"] = (cid[:24] + "...") if len(cid) > 24 else cid
    entry["scope"] = token_data.get("scope")
    entry["issued_at"] = token_data.get("issued_at")
    entry["last_check"] = token_data.get("last_check")

    # Calcular age sin fallar por TZ mismatch
    issued_dt = _parse_issued_at(token_data.get("issued_at"))
    if issued_dt:
        try:
            # Normalizar a UTC para comparacion segura
            if issued_dt.tzinfo is None:
                issued_aware = issued_dt.replace(tzinfo=_tz.utc)
            else:
                issued_aware = issued_dt.astimezone(_tz.utc)
            now_utc = now.astimezone(_tz.utc) if now.tzinfo else now.replace(tzinfo=_tz.utc)
            delta = now_utc - issued_aware
            entry["age_days"] = max(0, int(delta.total_seconds() // 86400))
        except (TypeError, ValueError):
            entry["age_days"] = None

    # Determinar status
    if not entry["has_refresh_token"]:
        entry["status"] = "MISSING_TOKEN"
    elif entry["age_days"] is not None and entry["age_days"] > 180:
        entry["status"] = "STALE"
    elif entry["has_refresh_token"]:
        entry["status"] = "OK"
    else:
        entry["status"] = "UNKNOWN"

    return entry


def get_gmail_status(q_fn=None) -> _Dict:
    """Lee estado de tokens Gmail de TODAS las cuentas configuradas.

    Args:
        q_fn: funcion de query a la BD (opcional). Si None, devuelve sin sync_control.

    Returns:
        {
          "accounts": [{account, credentials_file_exists, token_file_exists, status, ...}],
          "sync_control": {last_sync, status, ...} | None,
          "creds_dir_resolved": str,
          "generated_at": iso8601
        }

    Garantias:
      - NUNCA lanza excepcion (cualquier error se loguea y devuelve degraded state)
      - NUNCA expone access_token, refresh_token ni client_secret
      - Si el JSON del token tiene campos extra, los IGNORA silenciosamente
    """
    accounts_env = _os.getenv("GMAIL_ACCOUNTS", "").strip()
    configured = [a.strip() for a in accounts_env.split(",") if a.strip()] if accounts_env else []
    creds_dir = _resolve_creds_dir()

    result_accounts = []
    for acc in configured:
        if not isinstance(acc, str):
            continue
        try:
            token_file = creds_dir / f"gmail_token_{acc}.json"
            cred_file = creds_dir / f"gmail_credentials_{acc}.json"
            entry = {
                "account": acc,
                "credentials_file_exists": cred_file.exists(),
                "token_file_exists": token_file.exists(),
                "client_id": None,
                "scope": None,
                "issued_at": None,
                "last_check": None,
                "age_days": None,
                "status": "unknown",
                "has_refresh_token": False,
                "has_access_token": False,
            }
            if token_file.exists():
                try:
                    with open(token_file, "r") as f:
                        tok = _json.load(f)
                    status_data = _gmail_token_status(tok, _dt.utcnow())
                    entry.update(status_data)
                except (_json.JSONDecodeError, OSError) as e:
                    logger.warning(f"gmail_token parse fallo {acc}: {e!r}")
                    entry["status"] = "PARSE_ERROR"
            result_accounts.append(entry)
        except Exception as e:
            logger.exception(f"gmail_status account {acc} fallo: {e!r}")
            # Incluir entrada minima para que el frontend sepa que la cuenta existe
            result_accounts.append({"account": acc, "status": "ERROR", "credentials_file_exists": False, "token_file_exists": False})

    # sync_control (best-effort)
    sync_info = None
    if q_fn is not None:
        try:
            sync_rows = q_fn("SELECT source, last_sync, items_processed, errors, status FROM sync_control WHERE source = 'gmail'")
            if sync_rows:
                sync_info = {
                    "source": sync_rows[0].get("source"),
                    "last_sync": sync_rows[0].get("last_sync").isoformat() if sync_rows[0].get("last_sync") else None,
                    "items_processed": int(sync_rows[0].get("items_processed") or 0),
                    "errors": int(sync_rows[0].get("errors") or 0),
                    "status": sync_rows[0].get("status"),
                }
        except Exception as e:
            logger.warning(f"gmail_status sync_control query fallo: {e!r}")
            sync_info = None

    return {
        "accounts": result_accounts,
        "sync_control": sync_info,
        "creds_dir_resolved": str(creds_dir),
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }


# ════════════════════════════════════════════════════════════════════════
# ALERTAS ACK (persistencia robusta en agent_logs)
# ════════════════════════════════════════════════════════════════════════

# Whitelist de alert_id permitidos (anti inyeccion de basura en agent_logs)
ALLOWED_ALERT_TYPES = {
    "venta_caida", "canal_ausente", "gasto_pico", "factura_sin_categoria",
    "sync_stale", "facturas_sin_pdf", "locales_huerfanos", "duplicado_potencial",
    "ticket_anomalo", "bulk-ack",  # bulk-ack es el ack masivo
}

# Regex: alert_id debe ser TIPO_UUID (formato: tipo_[hex] o tipo_nombre)
import re as _re_alert
# v9.0.1: permitir cualquier identificador razonable (3+ chars alfanumericos/guion)
_ALERT_ID_PATTERN = _re_alert.compile(r'^[a-z][a-z0-9_-]{2,49}(?:_[a-z0-9][a-z0-9_-]{0,49})?$', _re_alert.I)


def _validate_alert_id(alert_id: str) -> _Opt[str]:
    """Valida que un alert_id tiene formato seguro. Devuelve el id normalizado o None.

    Formato esperado: <tipo>_<identificador> donde tipo esta en ALLOWED_ALERT_TYPES
    y el identificador es un UUID o hash hex.

    Casos especiales:
      - 'bulk-ack' o 'bulk-ack-<timestamp>' se aceptan como ack masivo
      - IDs muy largos (>200 chars) o vacios se rechazan
      - Caracteres no-alfanuméricos (espacios, /, etc) se rechazan
    """
    if not isinstance(alert_id, str):
        return None
    alert_id = alert_id.strip()
    if not alert_id or len(alert_id) > 200:
        return None

    # Caso especial: bulk-ack
    if alert_id == "bulk-ack" or alert_id.startswith("bulk-ack-"):
        return alert_id

    # Extraer el tipo (parte antes del primer _)
    if '_' not in alert_id:
        return None
    tipo = alert_id.split('_', 1)[0]
    if tipo not in ALLOWED_ALERT_TYPES:
        # Para tipos nuevos (futuros), validar formato
        if not _ALERT_ID_PATTERN.match(alert_id):
            return None
    return alert_id


def save_alert_ack(alert_id: str, note: str, acked_by: str,
                   q_exec_fn=None) -> _Dict:
    """Guarda un ack de alerta en agent_logs con manejo robusto de errores.

    Returns:
        {ok: True, ack_id, alert_id, acked_at, acked_by} en exito
        {ok: False, error, message, fallback: 'memory'} si la BD falla

    Garantia: NUNCA lanza excepcion. Si la BD falla, devuelve ack_id="memory-fallback"
    para que el frontend pueda mostrar feedback positivo sin mentir sobre la persistencia.
    """
    safe_id = _validate_alert_id(alert_id)
    if not safe_id:
        return {"ok": False, "error": "invalid_alert_id", "message": f"alert_id invalido: {alert_id[:50]!r}"}

    safe_note = (note or "")[:500]  # cap nota a 500 chars
    safe_by = (acked_by or "unknown")[:50]

    if q_exec_fn is None:
        return {"ok": False, "error": "no_db", "message": "BD no disponible", "fallback": "memory"}

    try:
        details = _json.dumps({
            "alert_id": safe_id,
            "note": safe_note,
            "acked_by": safe_by,
        }, ensure_ascii=False)
        rows = q_exec_fn("""
            INSERT INTO agent_logs (source, level, message, details)
            VALUES ('alertas', 'info', %s, %s::jsonb)
            RETURNING id, timestamp
        """, (f"ack: {safe_id}", details))
        if not rows:
            return {"ok": False, "error": "empty_insert", "message": "INSERT devolvio vacio"}
        new_id = str(rows[0]["id"])
        ts = rows[0]["timestamp"]
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        return {"ok": True, "ack_id": new_id, "alert_id": safe_id,
                "acked_at": ts or _dt.utcnow().isoformat(),
                "acked_by": safe_by}
    except Exception as e:
        logger.exception(f"alert_ack save fallo: {e!r}")
        return {"ok": False, "error": "db_error", "message": str(e)[:200],
                "fallback": "memory", "ack_id": f"memory-{_dt.utcnow().timestamp()}",
                "alert_id": safe_id}


def list_alert_acks(q_fn=None, limit: int = 100) -> _Dict:
    """Lista los acks de alertas (últimos N).

    Returns:
        {acks: [...], total: N} si OK
        {acks: [], total: 0, warning: '...'} si la BD falla

    Garantia: NUNCA lanza excepcion. Si la BD falla, devuelve lista vacia con warning.
    """
    if q_fn is None:
        return {"acks": [], "total": 0, "warning": "BD no disponible"}

    try:
        rows = q_fn(f"""
            SELECT id, timestamp,
                   details->>'alert_id' as alert_id_extracted,
                   details->>'note' as note_extracted,
                   details->>'acked_by' as acked_by_extracted
            FROM agent_logs
            WHERE source = 'alertas' AND level = 'info' AND message LIKE 'ack: %%'
            ORDER BY timestamp DESC
            LIMIT {int(limit)}
        """)
        acks = []
        for r in rows:
            acks.append({
                "ack_id": str(r["id"]),
                "alert_id": r["alert_id_extracted"],
                "note": r["note_extracted"],
                "acked_by": r["acked_by_extracted"],
                "acked_at": r["timestamp"].isoformat() if hasattr(r["timestamp"], "isoformat") else r["timestamp"],
            })
        return {"acks": acks, "total": len(acks)}
    except Exception as e:
        logger.exception(f"alert_acks list fallo: {e!r}")
        return {"acks": [], "total": 0, "warning": str(e)[:200]}


# ════════════════════════════════════════════════════════════════════════
# Detector de alertas (con try/except granular por detector)
# ════════════════════════════════════════════════════════════════════════

class AlertDetector:
    """Wrapper para detectores de alertas con blindaje.

    Cada detector es una funcion (q_fn) -> Dict con {id, severity, tipo, titulo, ...}.
    Si falla, se loguea con nombre del detector y se devuelve lista vacia
    para que el resto del /api/alertas funcione.
    """

    def __init__(self, name: str, fn, severity: str = "info"):
        self.name = name
        self.fn = fn
        self.severity = severity

    def run(self, q_fn) -> _List[_Dict]:
        try:
            result = self.fn(q_fn)
            if not isinstance(result, list):
                logger.warning(f"detector {self.name} devolvio {type(result).__name__}, no lista")
                return []
            return result
        except Exception as e:
            logger.warning(f"detector {self.name} fallo: {e!r}")
            return []
