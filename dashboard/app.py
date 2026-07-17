"""
Liados Dashboard v5 - FastAPI + HTML plano + Chart.js + design system premium.
Datos REALES desde lastapp_bills + lastapp_payments (canales) + invoices (gastos).

v5 (premium):
- Design system con tokens (dark+light), Inter + JetBrains Mono self-hosted.
- Sidebar colapsable, header sticky, hero KPI band.
- Cards premium con hover/sombras, estados skeleton/empty/error.
- Charts Chart.js con tooltip custom, counter animation, cross-filter, MoM.
- Chat AI end-to-end (agent.py + MCP Last.app) con confirmacion de acciones.
"""
import os
import json
import secrets
import threading
from datetime import date, datetime
from decimal import Decimal
from fastapi import Query, FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Optional, List
import psycopg2
from psycopg2 import pool as pgpool
from psycopg2.extras import RealDictCursor
import logging as _logging

logger = _logging.getLogger(__name__)

# Chat conversacional (wrapper sobre agent.py, sin modificarlo).
from dashboard import chat as chat_engine
try:
    from agente.scripts.oauth_drive import get_drive_status as _gd_status
except Exception:
    def _gd_status(account): return {"account": account, "status": "NOT_AVAILABLE", "error": "oauth_drive no importable"}

app = FastAPI(title="Liados Dashboard", version="8.3.0")
security = HTTPBasic()

# Servir assets estaticos (fuentes, css, js) sin auth (son publicos, sin secretos).
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ── Middleware de seguridad ────────────────────────────────────────────
# Headers minimos recomendados. CSP permite los recursos necesarios
# (Chart.js via CDN, inline scripts/styles del HTML generado).
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # CSP: self para todo lo nuestro, cdn.jsdelivr.net solo para Chart.js
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self';"
    )
    resp.headers.setdefault("Content-Security-Policy", csp)
    # v6.0.1: Anti-cache para el HTML principal y assets que cambian a menudo.
    # Esto evita que el navegador sirva versiones cacheadas después de un deploy.
    no_cache_paths = (
        '/', '/static/app.js', '/static/app.css', '/static/sw.js',
    )
    if request.url.path in no_cache_paths:
        resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
    # v7.1 PRO: endpoints /api/* autenticados no deben cachearse en proxies
    # compartidos (riesgo de fuga entre usuarios). Vary: Authorization es
    # importante por si un CDN intermedio cachea por Authorization header.
    elif request.url.path.startswith('/api/'):
        # Solo si no es /api/health (que es publica)
        if not request.url.path.startswith('/api/health'):
            resp.headers['Cache-Control'] = 'private, no-store'
            resp.headers['Vary'] = 'Authorization'
    return resp


def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    expected_user = os.environ["DASHBOARD_USER"]  # fail-fast si no esta en .env
    expected_pass = os.environ["DASHBOARD_PASSWORD"]  # fail-fast si no esta en .env
    if not (secrets.compare_digest(credentials.username, expected_user)
            and secrets.compare_digest(credentials.password, expected_pass)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ── Pool de conexiones ────────────────────────────────────────────────
# ThreadedConnectionPool: evita abrir/cerrar conexion en cada query.
# minconn=2, maxconn=20 (margen para SSE largos + dashboard en paralelo).
# Si la BD cae, getconn() levanta PoolError y devolvemos 503.
_POOL = None
_POOL_LOCK = threading.Lock()


@app.exception_handler(psycopg2.pool.PoolError)
def _pool_error_handler(request, exc):
    """Devuelve 503 en lugar de 500 cuando el pool se agota."""
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": "BD sobrecargada, reintenta en unos segundos"})


@app.exception_handler(psycopg2.OperationalError)
def _db_error_handler(request, exc):
    """Devuelve 503 en lugar de 500 cuando la BD no responde."""
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": f"BD no disponible: {exc}"})


# ── Rate limiter simple (in-memory) ───────────────────────────────────
# Protege /api/chat y /api/chat/stream de 429s del LLM upstream.
# Por IP de cliente, X requests por ventana de Y segundos.
# Suficiente para 1 usuario; en produccion con N usuarios, usar Redis.
import time as _time
from collections import deque as _deque
_RL_LOCK = threading.Lock()
_RL_BUCKETS = {}  # {ip_key: deque[timestamp]}


def _client_ip(request: Request) -> str:
    return (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def _rate_limit_check(request: Request, key: str, max_requests: int, window_s: int) -> bool:
    """Token-bucket in-memory. Devuelve True si OK, False si excedido."""
    ip = _client_ip(request) + ":" + key
    now = _time.time()
    with _RL_LOCK:
        bucket = _RL_BUCKETS.setdefault(ip, _deque())
        # purgar timestamps fuera de ventana
        while bucket and bucket[0] < now - window_s:
            bucket.popleft()
        if len(bucket) >= max_requests:
            return False
        bucket.append(now)
        return True


def _init_pool():
    global _POOL
    if _POOL is not None:
        return _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = pgpool.ThreadedConnectionPool(
                minconn=2, maxconn=20,
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "desliado"),
                user=os.getenv("DB_USER", "desliado"),
                password=os.environ["DB_PASSWORD"],
                connect_timeout=5,
                # v7.1 PRO: limites en sesion para evitar queries colgadas
                options="-c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000",
            )
    return _POOL


def get_conn():
    """Obtiene una conexion cruda del pool. Usar SIEMPRE con try/finally + put_conn.
    NO uses 'with get_conn() as c' (cierra la conexion, rompe el pool)."""
    return _init_pool().getconn()


def put_conn(conn):
    """Devuelve la conexion al pool (no la cierra). Hace rollback defensivo."""
    if _POOL is not None and conn is not None:
        try:
            conn.rollback()
        except Exception:
            pass
        _POOL.putconn(conn)


def q(sql, params=()):
    """Helper: ejecuta SELECT y devuelve filas. Garantiza release del slot del pool.
    Si el pool esta agotado, devuelve 503 en lugar de 500."""
    try:
        conn = get_conn()
    except psycopg2.pool.PoolError:
        raise HTTPException(status_code=503, detail="BD sobrecargada, reintenta en unos segundos")
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()
    except Exception:
        try: conn.rollback()
        except: pass
        raise
    finally:
        put_conn(conn)


def q_exec(sql, params=()):
    """Helper: ejecuta INSERT/UPDATE/DELETE y hace commit. Garantiza release del slot.
    Devuelve las filas devueltas por RETURNING (si lo hay), sino []."""
    try:
        conn = get_conn()
    except psycopg2.pool.PoolError:
        raise HTTPException(status_code=503, detail="BD sobrecargada, reintenta en unos segundos")
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(sql, params)
            try:
                result = cur.fetchall()
            except psycopg2.ProgrammingError:
                # No hay resultados (no es SELECT ni RETURNING)
                result = []
            conn.commit()
            return result
        finally:
            cur.close()
    except Exception:
        try: conn.rollback()
        except: pass
        raise
    finally:
        put_conn(conn)


def q_exec_returning(sql, params=()):
    """Helper: ejecuta INSERT con RETURNING y devuelve la PRIMERA fila como dict.

    CRITICAL fix v7.1 PRO: antes este helper no existía y reclasificar()
    con categoria nueva petaba con NameError. Ahora devuelve el row o None."""
    rows = q_exec(sql, params)
    return rows[0] if rows else None


def to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
    return d


# Filtros de gasto compartidos (excluir nominas/administrativo/basura y no-facturas)
# alias="" para tablas sin alias; alias="i." para queries con JOIN.
def expense_filter(alias: str = "") -> str:
    p = lambda f: f"{alias}{f}"
    return (
        f"{p('type')} = 'expense' AND {p('status')} != 'rejected' "
        f"AND {p('is_invoice')} = true "
        f"AND COALESCE({p('category_raw')}, '') NOT IN ('nomina', 'administrativo', 'basura') "
        f"AND {p('invoice_date')} IS NOT NULL "
        f"AND {p('vendor_name')} IS NOT NULL"
    )


# ── API Endpoints (existentes) ──────────────────────────────────

@app.get("/api/kpis")
def api_kpis(user: str = Depends(get_current_user)):
    """KPIs del mes actual: ventas (lastapp_bills), gastos (invoices), margen."""
    ventas = q("""
        SELECT count(*) as facturas,
               coalesce(sum(total_cents), 0)/100.0 as total,
               coalesce(sum(tax_cents), 0)/100.0 as iva,
               coalesce(sum(delivery_fee_cents), 0)/100.0 as delivery
        FROM lastapp_bills
        WHERE deleted = false
          AND date_trunc('month', creation_time) = date_trunc('month', now())
    """)[0]

    gastos = q(f"""
        SELECT count(*) as facturas,
               coalesce(sum(total_amount), 0) as total
        FROM invoices
        WHERE {expense_filter()}
          AND date_trunc('month', invoice_date) = date_trunc('month', now())
    """)[0]

    total_ventas = float(ventas["total"])
    total_gastos = float(gastos["total"])

    return {
        "ventas_mes": total_ventas,
        "gastos_mes": total_gastos,
        "margen_mes": total_ventas - total_gastos,
        "facturas_ventas": ventas["facturas"],
        "facturas_gastos": gastos["facturas"],
        "iva_mes": float(ventas["iva"]),
        "delivery_mes": float(ventas["delivery"]),
    }


@app.get("/api/ventas-por-canal")
def api_ventas_por_canal(user: str = Depends(get_current_user)):
    """Ventas del mes actual agrupadas por canal de pago."""
    return [to_dict(r) for r in q("""
        SELECT p.type as canal,
               count(*) as pagos,
               coalesce(sum(p.amount_cents), 0)/100.0 as total_eur,
               coalesce(sum(p.tip_cents), 0)/100.0 as propinas_eur
        FROM lastapp_payments p
        JOIN lastapp_bills b ON b.id = p.bill_id
        WHERE b.deleted = false AND p.deleted = false
          AND date_trunc('month', b.creation_time) = date_trunc('month', now())
        GROUP BY p.type
        ORDER BY total_eur DESC
    """)]


@app.get("/api/canal-por-mes")
def api_canal_por_mes(user: str = Depends(get_current_user)):
    """Ventas por canal y mes (ultimos 6 meses). Para grafico apilado."""
    return [to_dict(r) for r in q("""
        SELECT to_char(b.creation_time, 'YYYY-MM') as mes,
               p.type as canal,
               count(*) as pagos,
               coalesce(sum(p.amount_cents), 0)/100.0 as total_eur
        FROM lastapp_bills b
        JOIN lastapp_payments p ON p.bill_id = b.id
        WHERE b.deleted = false AND p.deleted = false
          AND b.creation_time >= now() - interval '6 months'
        GROUP BY mes, canal
        ORDER BY mes, total_eur DESC
    """)]


@app.get("/api/ingresos-por-mes")
def api_ingresos_por_mes(user: str = Depends(get_current_user)):
    """Ingresos mensuales desde lastapp_bills (ultimos 6 meses)."""
    return [to_dict(r) for r in q("""
        SELECT to_char(creation_time, 'YYYY-MM') as mes,
               count(*) as facturas,
               coalesce(sum(total_cents), 0)/100.0 as total_eur,
               coalesce(sum(tax_cents), 0)/100.0 as iva_eur,
               coalesce(sum(taxable_base_cents), 0)/100.0 as base_eur,
               coalesce(sum(delivery_fee_cents), 0)/100.0 as delivery_eur,
               coalesce(sum(discount_total_cents), 0)/100.0 as descuentos_eur
        FROM lastapp_bills
        WHERE deleted = false
          AND creation_time >= now() - interval '6 months'
        GROUP BY mes
        ORDER BY mes
    """)]


@app.get("/api/gastos-por-proveedor")
def api_gastos_por_proveedor(limit: int = Query(10, ge=1, le=200, description='Maximo 200 proveedores'), user: str = Depends(get_current_user)):
    """Top proveedores por gasto total."""
    return [to_dict(r) for r in q(f"""
        SELECT coalesce(vendor_name, 'Sin nombre') as proveedor,
               count(*) as facturas,
               coalesce(sum(total_amount), 0) as total_eur,
               string_agg(distinct category_raw, ', ') as categorias
        FROM invoices
        WHERE {expense_filter()}
          AND vendor_name IS NOT NULL
        GROUP BY vendor_name
        ORDER BY total_eur DESC, facturas DESC
        LIMIT %s
    """, (limit,))]


@app.get("/api/gastos-por-categoria")
def api_gastos_por_categoria(user: str = Depends(get_current_user)):
    """Gastos agrupados por categoria."""
    return [to_dict(r) for r in q(f"""
        SELECT coalesce(c.name, i.category_raw, 'Sin categoria') as categoria,
               coalesce(c.color, '#6B7280') as color,
               count(*) as facturas,
               coalesce(sum(i.total_amount), 0) as total_eur
        FROM invoices i
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE {expense_filter('i.')}
        GROUP BY categoria, color
        ORDER BY total_eur DESC
    """)]


@app.get("/api/margen-por-mes")
def api_margen_por_mes(user: str = Depends(get_current_user)):
    """Margen = ingresos (lastapp_bills) - gastos (invoices) por mes."""
    ingresos = {r["mes"]: float(r["total_eur"]) for r in q("""
        SELECT to_char(creation_time, 'YYYY-MM') as mes,
               coalesce(sum(total_cents), 0)/100.0 as total_eur
        FROM lastapp_bills
        WHERE deleted = false AND creation_time >= now() - interval '6 months'
        GROUP BY mes
    """)}

    gastos_raw = q(f"""
        SELECT to_char(invoice_date, 'YYYY-MM') as mes,
               coalesce(sum(total_amount), 0) as total_eur
        FROM invoices
        WHERE {expense_filter()}
          AND invoice_date >= now() - interval '6 months'
        GROUP BY mes
    """)
    gastos = {}
    for r in gastos_raw:
        m = r["mes"]
        if m:
            gastos[m] = float(r["total_eur"])

    meses = sorted(set(list(ingresos.keys()) + list(gastos.keys())))
    result = []
    for m in meses:
        ing = ingresos.get(m, 0)
        gas = gastos.get(m, 0)
        result.append({"mes": m, "ingresos": ing, "gastos": gas, "margen": ing - gas})
    return result


@app.get("/api/facturas-recientes")
def api_facturas_recientes(limit: int = Query(15, ge=1, le=100, description='Maximo 100 facturas'), user: str = Depends(get_current_user)):
    """Ultimas facturas de Last.app con su canal de pago."""
    return [to_dict(r) for r in q("""
        SELECT b.number,
               to_char(b.creation_time, 'YYYY-MM-DD HH24:MI') as fecha,
               coalesce(b.total_cents, 0)/100.0 as total_eur,
               coalesce(b.customer_name, 'Mostrador') as cliente,
               string_agg(distinct p.type, ', ') as canales
        FROM lastapp_bills b
        LEFT JOIN lastapp_payments p ON p.bill_id = b.id AND p.deleted = false
        WHERE b.deleted = false
        GROUP BY b.number, b.creation_time, b.total_cents, b.customer_name
        ORDER BY b.creation_time DESC
        LIMIT %s
    """, (limit,))]


@app.get("/api/health")
def health():
    """Health check enriquecido: BD OK, pool stats, version."""
    out = {"status": "ok", "version": "8.3.0", "checks": {}}
    # Test BD (importante: usar try/finally + put_conn para no romper el pool)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        out["checks"]["database"] = "ok"
    except Exception as e:
        out["status"] = "degraded"
        out["checks"]["database"] = f"error: {e}"
    finally:
        put_conn(conn)
    # Pool stats
    try:
        if _POOL is not None:
            # ThreadedConnectionPool no expone getters en todas las versiones;
            # usamos getattr defensivo
            used = getattr(_POOL, "_used", None)
            free = getattr(_POOL, "_pool", None)
            out["checks"]["pool"] = {
                "used": len(used) if used is not None and hasattr(used, '__len__') else None,
                "free": len(free) if free is not None and hasattr(free, '__len__') else None,
            }
    except Exception:
        out["checks"]["pool"] = "unavailable"
    return out


# ── API Endpoints NUEVOS (v4) ───────────────────────────────────

@app.get("/api/kpis-comparativa")
def api_kpis_comparativa(user: str = Depends(get_current_user)):
    """Comparativa mes actual vs mes anterior: ventas, gastos, margen con % delta."""
    ventas = q("""
        SELECT to_char(date_trunc('month', creation_time), 'YYYY-MM') as mes,
               coalesce(sum(total_cents), 0)/100.0 as total
        FROM lastapp_bills
        WHERE deleted = false
          AND creation_time >= date_trunc('month', now()) - interval '1 month'
        GROUP BY 1
    """)
    v = {r["mes"]: float(r["total"]) for r in ventas}

    gastos = q(f"""
        SELECT to_char(date_trunc('month', invoice_date), 'YYYY-MM') as mes,
               coalesce(sum(total_amount), 0) as total
        FROM invoices
        WHERE {expense_filter()}
          AND invoice_date >= date_trunc('month', now()) - interval '1 month'
        GROUP BY 1
    """)
    g = {r["mes"]: float(r["total"]) for r in gastos}

    from datetime import timedelta
    now = datetime.utcnow()
    cur_key = now.strftime("%Y-%m")
    prev_dt = (now.replace(day=1) - timedelta(days=1))
    prev_key = prev_dt.strftime("%Y-%m")

    def pct(cur, prev):
        if prev == 0:
            return None
        return (cur - prev) / abs(prev) * 100.0

    v_cur, v_prev = v.get(cur_key, 0), v.get(prev_key, 0)
    g_cur, g_prev = g.get(cur_key, 0), g.get(prev_key, 0)
    m_cur, m_prev = v_cur - g_cur, v_prev - g_prev

    return {
        "ventas": {"actual": v_cur, "anterior": v_prev, "delta_pct": pct(v_cur, v_prev)},
        "gastos": {"actual": g_cur, "anterior": g_prev, "delta_pct": pct(g_cur, g_prev)},
        "margen": {"actual": m_cur, "anterior": m_prev, "delta_pct": pct(m_cur, m_prev)},
    }


@app.get("/api/locales")
def api_locales(user: str = Depends(get_current_user)):
    """Lista de locales (location_id) con nombre derivado de la company."""
    return [to_dict(r) for r in q("""
        SELECT coalesce(location_id::text, 'sin-local') as id,
               coalesce(max(raw_json->'company'->>'name'), 'Sin local') as nombre,
               count(*) as facturas,
               coalesce(sum(total_cents), 0)/100.0 as total_eur
        FROM lastapp_bills
        WHERE deleted = false
        GROUP BY location_id
        ORDER BY total_eur DESC
    """)]


@app.get("/api/ventas-por-local")
def api_ventas_por_local(user: str = Depends(get_current_user)):
    """Ventas del mes actual por local."""
    return [to_dict(r) for r in q("""
        SELECT coalesce(b.location_id::text, 'sin-local') as id,
               coalesce(max(b.raw_json->'company'->>'name'), 'Sin local') as nombre,
               count(*) as facturas,
               coalesce(sum(b.total_cents), 0)/100.0 as total_eur,
               coalesce(sum(b.tax_cents), 0)/100.0 as iva_eur
        FROM lastapp_bills b
        WHERE b.deleted = false
          AND date_trunc('month', b.creation_time) = date_trunc('month', now())
        GROUP BY b.location_id
        ORDER BY total_eur DESC
    """)]


@app.get("/api/ventas-por-dia")
def api_ventas_por_dia(days: int = Query(30, ge=1, le=365, description='Maximo 365 dias'), user: str = Depends(get_current_user)):
    """Serie diaria de ventas (ingresos + nº facturas) para los ultimos N dias."""
    rows = q("""
        SELECT to_char(date(d), 'YYYY-MM-DD') as dia,
               count(b) as facturas,
               coalesce(sum(b.total_cents), 0)/100.0 as total_eur
        FROM generate_series(
            date_trunc('day', now()) - (%s || ' days')::interval,
            date_trunc('day', now()),
            '1 day'
        ) d
        LEFT JOIN lastapp_bills b
          ON date(b.creation_time) = d AND b.deleted = false
        GROUP BY d
        ORDER BY d
    """, (days,))
    return [to_dict(r) for r in rows]


@app.get("/api/ingresos-6m")
def api_ingresos_6m(user: str = Depends(get_current_user)):
    """Serie mensual de ingresos para sparklines (6 meses)."""
    return [to_dict(r) for r in q("""
        SELECT to_char(creation_time, 'YYYY-MM') as mes,
               coalesce(sum(total_cents), 0)/100.0 as total_eur
        FROM lastapp_bills
        WHERE deleted = false AND creation_time >= now() - interval '6 months'
        GROUP BY mes ORDER BY mes
    """)]


# ── Chat AI endpoints (Fase 3) ──────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None


class ConfirmRequest(BaseModel):
    confirmation_token: str


@app.post("/api/chat")
def api_chat(req: ChatRequest, request: Request, user: str = Depends(get_current_user)):
    """Chat conversacional contra el agente (OpenCode Go + MCP)."""
    if not _rate_limit_check(request, key="chat", max_requests=20, window_s=60):
        raise HTTPException(status_code=429, detail="Demasiadas peticiones. Espera unos segundos.")
    try:
        result = chat_engine.chat(req.message, req.history)
        return result
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"reply": f"Error del agente: {e}",
                     "pending_confirmation": None, "tools_used": [], "history": req.history or []},
        )


@app.post("/api/chat/confirm")
def api_chat_confirm(req: ConfirmRequest, user: str = Depends(get_current_user)):
    """Confirma (ejecuta) una accion pendiente usando su token."""
    return chat_engine.confirm(req.confirmation_token)


@app.post("/api/chat/cancel")
def api_chat_cancel(req: ConfirmRequest, user: str = Depends(get_current_user)):
    """Cancela una accion pendiente usando su token."""
    return chat_engine.cancel(req.confirmation_token)


@app.post("/api/chat/stream")
def api_chat_stream(req: ChatRequest, request: Request, user: str = Depends(get_current_user)):
    """Chat conversacional STREAMING via Server-Sent Events.

    Emite eventos SSE:
      event: token  data: {"text": "..."}        (tokens de la respuesta final)
      event: tool   data: {"name": "..."}        (inicio de ejecucion de tool)
      event: done   data: {"reply","pending_confirmation","tools_used","history"}
      event: error  data: {"message": "..."}
    """
    if not _rate_limit_check(request, key="chat-stream", max_requests=15, window_s=60):
        raise HTTPException(status_code=429, detail="Demasiadas peticiones. Espera unos segundos.")

    def gen():
        try:
            for ev in chat_engine.chat_stream(req.message, req.history):
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # desactivar buffering en proxies
            "Connection": "keep-alive",
        },
    )


# ── Capa 6: Búsqueda global, export CSV, drill-down ─────────────

from fastapi.responses import Response


@app.get("/api/search")
def api_search(term: str = Query("", alias="q"), user: str = Depends(get_current_user)):
    """Busqueda global full-text sobre facturas + ilike sobre vendors."""
    term = (term or "").strip()
    if len(term) < 2:
        return {"facturas": [], "proveedores": [], "total": 0}

    # 1. Facturas (full-text con el indice GIN existente + ilike)
    facturas = q("""
        SELECT id, invoice_number, vendor_name, total_amount, invoice_date,
               category_raw, type, status, description,
               ts_rank(
                   to_tsvector('spanish', coalesce(vendor_name,'')||' '||coalesce(description,'')||' '||coalesce(invoice_number,'')),
                   plainto_tsquery('spanish', %s)
               ) as rank
        FROM invoices
        WHERE to_tsvector('spanish', coalesce(vendor_name,'')||' '||coalesce(description,'')||' '||coalesce(invoice_number,'')) @@ plainto_tsquery('spanish', %s)
           OR vendor_name ILIKE %s
        ORDER BY rank DESC NULLS LAST, invoice_date DESC
        LIMIT 15
    """, (term, term, f"%{term}%"))

    # 2. Proveedores agregados (por vendor_name)
    proveedores = q("""
        SELECT coalesce(vendor_name, 'Sin nombre') as proveedor,
               count(*) as facturas,
               coalesce(sum(total_amount), 0) as total_eur
        FROM invoices
        WHERE vendor_name ILIKE %s AND is_invoice = true
        GROUP BY vendor_name
        ORDER BY total_eur DESC
        LIMIT 8
    """, (f"%{term}%",))

    return {
        "facturas": [to_dict(r) for r in facturas],
        "proveedores": [to_dict(r) for r in proveedores],
        "total": len(facturas) + len(proveedores),
    }


@app.get("/api/proveedor/{nombre}/facturas")
def api_proveedor_facturas(nombre: str, limit: int = 50, user: str = Depends(get_current_user)):
    """Drill-down: todas las facturas de un proveedor."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="nombre requerido")
    rows = q("""
        SELECT invoice_number, invoice_date, total_amount, base_amount, tax_amount,
               category_raw, status, description
        FROM invoices
        WHERE vendor_name ILIKE %s
          AND type = 'expense' AND status != 'rejected' AND is_invoice = true
        ORDER BY invoice_date DESC
        LIMIT %s
    """, (f"%{nombre}%", limit))
    stats = q("""
        SELECT count(*) as total_facturas,
               coalesce(sum(total_amount), 0) as total_eur,
               coalesce(avg(total_amount), 0) as ticket_medio,
               min(invoice_date) as primera,
               max(invoice_date) as ultima
        FROM invoices
        WHERE vendor_name ILIKE %s
          AND type = 'expense' AND status != 'rejected' AND is_invoice = true
    """, (f"%{nombre}%",))[0]
    return {"stats": to_dict(stats), "facturas": [to_dict(r) for r in rows]}


@app.get("/api/categoria/{categoria}/facturas")
def api_categoria_facturas(categoria: str, limit: int = 50, user: str = Depends(get_current_user)):
    """Drill-down: todas las facturas de una categoria."""
    categoria = (categoria or "").strip()
    if not categoria:
        raise HTTPException(status_code=400, detail="categoria requerida")
    rows = q("""
        SELECT coalesce(vendor_name, 'Sin nombre') as proveedor,
               invoice_number, invoice_date, total_amount, status
        FROM invoices
        WHERE category_raw ILIKE %s
          AND type = 'expense' AND status != 'rejected' AND is_invoice = true
        ORDER BY invoice_date DESC
        LIMIT %s
    """, (f"%{categoria}%", limit))
    return {"facturas": [to_dict(r) for r in rows]}


def _csv(rows: list, columns: list, filename: str) -> Response:
    """Genera una respuesta CSV a partir de filas (dicts) + columnas."""
    import csv
    import io
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM para que Excel lea UTF-8
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow([r.get(c, "") for c in columns])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/{view}")
def api_export(view: str, user: str = Depends(get_current_user)):
    """Exporta a CSV: proveedores | categorias | facturas | ingresos."""
    if view == "proveedores":
        rows = q(f"""
            SELECT coalesce(vendor_name, 'Sin nombre') as proveedor,
                   count(*) as facturas,
                   coalesce(sum(total_amount), 0) as total_eur,
                   string_agg(distinct category_raw, ', ') as categorias
            FROM invoices
            WHERE {expense_filter()} AND vendor_name IS NOT NULL
            GROUP BY vendor_name ORDER BY total_eur DESC
        """)
        return _csv([to_dict(r) for r in rows],
                    ["proveedor", "facturas", "total_eur", "categorias"], "gastos-proveedores.csv")
    if view == "categorias":
        rows = q(f"""
            SELECT coalesce(c.name, i.category_raw, 'Sin categoria') as categoria,
                   count(*) as facturas, coalesce(sum(i.total_amount), 0) as total_eur
            FROM invoices i
            LEFT JOIN categories c ON c.id = i.category_id
            WHERE {expense_filter('i.')}
            GROUP BY categoria ORDER BY total_eur DESC
        """)
        return _csv([to_dict(r) for r in rows],
                    ["categoria", "facturas", "total_eur"], "gastos-categorias.csv")
    if view == "facturas":
        rows = q(f"""
            SELECT invoice_number, invoice_date, vendor_name, total_amount,
                   category_raw, status, description
            FROM invoices
            WHERE {expense_filter()}
            ORDER BY invoice_date DESC LIMIT 500
        """)
        return _csv([to_dict(r) for r in rows],
                    ["invoice_number", "invoice_date", "vendor_name", "total_amount",
                     "category_raw", "status", "description"], "facturas-gastos.csv")
    if view == "ingresos":
        rows = q("""
            SELECT to_char(creation_time, 'YYYY-MM') as mes, number, customer_name,
                   total_cents/100.0 as total_eur, tax_cents/100.0 as iva_eur
            FROM lastapp_bills WHERE deleted = false
            ORDER BY creation_time DESC LIMIT 500
        """)
        return _csv([to_dict(r) for r in rows],
                    ["mes", "number", "customer_name", "total_eur", "iva_eur"], "ingresos.csv")
    raise HTTPException(status_code=404, detail="Vista no soportada")


# ── API: Gmail status (read-only, Entregable B) ─────────────────

@app.get("/api/admin/gmail-status")
def api_gmail_status(user: str = Depends(get_current_user)):
    """Estado de las cuentas Gmail configuradas. SOLO LECTURA de metadatos.
    Nunca expone tokens (access/refresh/client_secret). Lee los JSON de
    agente/credentials/ sin modificarlos (denylist respetado)."""
    import json as _json
    from pathlib import Path as _Path

    accounts_env = os.getenv("GMAIL_ACCOUNTS", "").strip()
    configured = [a.strip() for a in accounts_env.split(",") if a.strip()] if accounts_env else []
    # Resolver credentials dir en orden de prioridad:
    # 1. ENV GMAIL_CREDENTIALS_DIR (sobrescribe para tests/CI)
    # 2. CWD/agente/credentials (producción con WorkingDirectory=/root/liados)
    # 3. Path relativo al paquete dashboard (worktree/dev local)
    creds_override = os.getenv("GMAIL_CREDENTIALS_DIR", "").strip()
    if creds_override:
        creds_dir = _Path(creds_override)
    else:
        creds_dir = _Path(os.getcwd()) / "agente" / "credentials"
        if not creds_dir.is_dir():
            creds_dir = _Path(__file__).resolve().parent.parent / "agente" / "credentials"
        if not creds_dir.is_dir():
            # Fallback final: /root/liados/agente/credentials (path absoluto producción)
            prod_path = _Path("/root/liados/agente/credentials")
            if prod_path.is_dir():
                creds_dir = prod_path

    result = []
    for acc in configured:
        token_file = creds_dir / f"gmail_token_{acc}.json"
        cred_file = creds_dir / f"gmail_credentials_{acc}.json"

        entry = {
            "account": acc,
            "credentials_file_exists": cred_file.exists(),
            "token_file_exists": token_file.exists(),
            "has_refresh_token": False,
            "has_access_token": False,
            "client_id": None,
            "scope": None,
            "issued_at": None,
            "last_check": None,
            "age_days": None,
            "status": "unknown",
        }

        if token_file.exists():
            try:
                with open(token_file) as f:
                    tok = _json.load(f)
                entry["has_refresh_token"] = bool(tok.get("refresh_token"))
                entry["has_access_token"] = bool(tok.get("access_token"))
                cid = tok.get("client_id") or ""
                entry["client_id"] = (cid[:24] + "...") if len(cid) > 24 else cid
                entry["scope"] = tok.get("scope")
                entry["issued_at"] = tok.get("issued_at")
                entry["last_check"] = tok.get("last_check")

                issued = tok.get("issued_at")
                if issued:
                    try:
                        from datetime import datetime as _dt
                        if isinstance(issued, str):
                            ts = _dt.fromisoformat(issued.replace("Z", "+00:00"))
                        elif isinstance(issued, (int, float)):
                            ts = _dt.fromtimestamp(issued, tz=_dt.now().astimezone().tzinfo)
                        else:
                            ts = None
                        if ts:
                            entry["age_days"] = (datetime.utcnow().replace(tzinfo=ts.tzinfo) - ts).days
                    except Exception:
                        pass

                if not entry["has_refresh_token"]:
                    entry["status"] = "MISSING_TOKEN"
                elif entry["age_days"] is not None and entry["age_days"] > 180:
                    entry["status"] = "STALE"
                else:
                    entry["status"] = "OK"
            except Exception as e:
                entry["status"] = f"PARSE_ERROR: {e}"

        result.append(entry)

    # Última sincronización desde sync_control
    sync_rows = q("SELECT source, last_sync, items_processed, errors, status FROM sync_control WHERE source = 'gmail'")
    sync_info = to_dict(sync_rows[0]) if sync_rows else None

    return {"accounts": result, "sync_control": sync_info}


# ── API: Gastos desglosados (Entregable D1) ──────────────────────
# Lista paginada con filtros + detalle + descarga PDF + facets + timeline + stats.

@app.get("/api/gastos")
def api_gastos(
    page: int = Query(1, ge=1, le=10000, description='Número de página'),
    page_size: int = Query(25, ge=1, le=200, description='Resultados por página'),
    from_: str = Query("", alias="from", description='Fecha desde YYYY-MM-DD'),
    to: str = Query("", alias="to", description='Fecha hasta YYYY-MM-DD'),
    vendor: str = Query("", description='Filtro por vendor (ILIKE)'),
    categoria: str = Query("", description='Filtro por categoría (ILIKE)'),
    cuenta: str = Query("", description='Filtro por source_account'),
    status: str = Query("", description='Filtro por status'),
    query: str = Query("", alias="q", description='Búsqueda full-text'),
    min_eur: float = Query(None, description='Importe mínimo'),
    max_eur: float = Query(None, description='Importe máximo'),
    sort: str = Query("invoice_date", description='Campo de orden: invoice_date|total_amount|vendor_name|created_at'),
    order: str = Query("desc", description='asc|desc'),
    user: str = Depends(get_current_user),
):
    """Lista paginada de facturas de gasto con filtros combinados (AND).
    Devuelve rows + total + page + facets para popular los filtros dinámicos."""
    where = [expense_filter()]
    params = []

    if from_:
        where.append("invoice_date >= %s")
        params.append(from_)
    if to:
        where.append("invoice_date <= %s")
        params.append(to)
    if vendor:
        where.append("vendor_name ILIKE %s")
        params.append(f"%{vendor}%")
    if categoria:
        where.append("COALESCE(category_raw, '') ILIKE %s")
        params.append(f"%{categoria}%")
    if cuenta:
        where.append("source_account = %s")
        params.append(cuenta)
    if status:
        where.append("status = %s")
        params.append(status)
    if query:
        where.append("(to_tsvector('spanish', coalesce(vendor_name,'')||' '||coalesce(description,'')||' '||coalesce(invoice_number,'')) @@ plainto_tsquery('spanish', %s) OR vendor_name ILIKE %s)")
        params.append(query)
        params.append(f"%{query}%")
    if min_eur is not None:
        where.append("total_amount >= %s")
        params.append(min_eur)
    if max_eur is not None:
        where.append("total_amount <= %s")
        params.append(max_eur)

    where_sql = " AND ".join(where)

    valid_sorts = {"invoice_date": "invoice_date", "total_amount": "total_amount",
                   "vendor_name": "vendor_name", "created_at": "created_at"}
    sort_col = valid_sorts.get(sort, "invoice_date")
    order_sql = "DESC" if order.lower() == "desc" else "ASC"

    # Total count (sin LIMIT)
    total_row = q(f"SELECT count(*) as c FROM invoices WHERE {where_sql}", tuple(params))[0]
    total = int(total_row["c"])

    # Página
    offset = (page - 1) * page_size
    rows = q(f"""
        SELECT id, invoice_number, invoice_date, vendor_name, total_amount,
               base_amount, tax_amount, category_raw, status, source, source_account,
               description, raw_file_url, confidence_score, created_at
        FROM invoices
        WHERE {where_sql}
        ORDER BY {sort_col} {order_sql} NULLS LAST
        LIMIT %s OFFSET %s
    """, tuple(params) + (page_size, offset))

    # Facets (solo si estamos en página 1, para no recalcular en navegación)
    facets = {}
    if page == 1:
        facets_row = q(f"""
            SELECT
              count(DISTINCT source_account) as n_cuentas,
              count(DISTINCT vendor_name) as n_vendors,
              count(*) FILTER (WHERE category_raw IS NULL) as n_sin_cat,
              count(*) FILTER (WHERE raw_file_url IS NOT NULL) as n_con_pdf,
              coalesce(sum(total_amount), 0) as total_eur,
              coalesce(avg(total_amount), 0) as ticket_medio
            FROM invoices WHERE {where_sql}
        """, tuple(params))[0]
        facets = {
            "cuentas": [to_dict(r) for r in q(f"""
                SELECT source_account, count(*) as n, coalesce(sum(total_amount),0) as total
                FROM invoices WHERE {where_sql} AND source_account IS NOT NULL
                GROUP BY source_account ORDER BY n DESC
            """, tuple(params))],
            "statuses": [to_dict(r) for r in q(f"""
                SELECT status, count(*) as n FROM invoices WHERE {where_sql}
                GROUP BY status ORDER BY n DESC
            """, tuple(params))],
            "summary": {
                "total_facturas": total,
                "total_eur": float(facets_row["total_eur"]),
                "ticket_medio": float(facets_row["ticket_medio"]),
                "vendors_unicos": int(facets_row["n_vendors"]),
                "facturas_sin_categoria": int(facets_row["n_sin_cat"]),
                "facturas_con_pdf": int(facets_row["n_con_pdf"]),
            },
        }

    return {
        "rows": [to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "facets": facets,
    }




# ── API: Google Drive status (read-only) ────────────────────────

@app.get("/api/admin/gdrive-status")
def api_gdrive_status(user: str = Depends(get_current_user)):
    """Estado de los tokens Drive de las cuentas configuradas. SOLO LECTURA."""
    accounts_env = os.getenv("GMAIL_ACCOUNTS", "").strip()
    configured = [a.strip() for a in accounts_env.split(",") if a.strip()] if accounts_env else []
    result = []
    for acc in configured:
        try:
            entry = _gd_status(acc)
        except Exception as e:
            entry = {"account": acc, "error": str(e)}
        result.append(entry)
    return {"accounts": result}

# ── API: Gastos desglose (Entregable D2) ─────────────────────────

@app.get("/api/gastos/desglose")
def api_gastos_desglose(
    group_by: str = Query(..., description="Dimensiones separadas por coma. Ej: category,month"),
    metric: str = Query("sum", description="count|sum|avg|min|max"),
    date_from: str = Query(None, description="YYYY-MM-DD"),
    date_to: str = Query(None, description="YYYY-MM-DD"),
    cuenta: str = Query(None, description="Filtrar por source_account"),
    status: str = Query(None, description="Filtrar por status"),
    min_eur: float = Query(None, ge=0),
    max_eur: float = Query(None, ge=0),
    user: str = Depends(get_current_user),
):
    """Desglose multidimensional de gastos.

    Devuelve filas agrupadas por las dimensiones indicadas con la métrica aplicada.

    Ejemplo de uso:
        /api/gastos/desglose?group_by=category,month&metric=sum
        /api/gastos/desglose?group_by=vendor&metric=avg&min_eur=100
    """
    from dashboard.desglose import build_desglose, normalize_invoice_row, DesgloseError
    from urllib.parse import unquote_plus

    # Parsear dimensiones (max 4)
    dims = [d.strip() for d in group_by.split(",") if d.strip()]

    # v7.1.1: Validar metric
    if metric not in ("count", "sum", "avg", "min", "max"):
        raise HTTPException(status_code=422, detail=f"metric inválida: {metric}")

    # v7.1.1: Validar fechas (YYYY-MM-DD). Antes pasaban crudas a SQL -> 500.
    from datetime import datetime as _dt
    if date_from:
        try: _dt.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=422, detail="date_from debe ser YYYY-MM-DD")
    if date_to:
        try: _dt.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=422, detail="date_to debe ser YYYY-MM-DD")

    # Construir WHERE dinámico
    where_parts = [expense_filter()]
    params = []
    if date_from:
        where_parts.append("invoice_date >= %s")
        params.append(date_from)
    if date_to:
        where_parts.append("invoice_date <= %s")
        params.append(date_to)
    if cuenta:
        where_parts.append("source_account = %s")
        params.append(cuenta)
    if status:
        where_parts.append("status = %s")
        params.append(status)
    if min_eur is not None:
        where_parts.append("total_amount >= %s")
        params.append(min_eur)
    if max_eur is not None:
        where_parts.append("total_amount <= %s")
        params.append(max_eur)

    where_sql = " AND ".join(where_parts)

    # SELECT campos necesarios para todas las dimensiones posibles
    # JOIN categories para devolver la FK canonica (no el category_raw libre)
    rows = q(f"""
        SELECT i.vendor_name,
               COALESCE(c.name, i.category_raw) as category,
               i.source_account, i.source, i.status,
               i.invoice_date, i.total_amount
        FROM invoices i
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE {where_sql}
        LIMIT 5000
    """, tuple(params))

    # Normalizar y delegar al módulo
    norm_rows = [normalize_invoice_row(dict(r)) for r in rows]

    try:
        out = build_desglose(norm_rows, dims, metric)
    except DesgloseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return out


@app.post("/api/gastos/{factura_id}/reclasificar")
def api_gastos_reclasificar(
    factura_id: str,
    payload: dict,
    user: str = Depends(get_current_user),
):
    """Reclasifica una factura existente (manual override).

    Body esperado (todos opcionales; sólo se actualizan los enviados):
        {
            "vendor_name": str,
            "category_raw": str,
            "total_amount": float (en euros),
            "invoice_date": "YYYY-MM-DD",
            "description": str,
            "reason": str (motivo, requerido para auditoría)
        }
    """
    if not payload.get("reason"):
        raise HTTPException(status_code=422, detail="Falta 'reason' para auditar el cambio")

    # Verificar que la factura existe y es expense
    rows = q(
        "SELECT id, vendor_name, category_raw, total_amount, invoice_date, status "
        "FROM invoices WHERE id = %s AND type = 'expense'",
        (factura_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    old = dict(rows[0])

    # Construir UPDATE dinámico (sólo campos enviados)
    update_parts = []
    update_params = []
    field_map = {
        "vendor_name": "vendor_name",
        "category_raw": None,  # especial: se traduce a category_id (FK)
        "category_name": None,  # alias para buscar por nombre canonico
        "total_amount_cents": None,  # especial
        "invoice_date": "invoice_date",
        "description": "description",
    }
    for key, col in field_map.items():
        if key not in payload:
            continue
        if key == "total_amount_cents":
            # convertir euros a céntimos
            update_parts.append(f"{col or 'total_amount'} = %s")
            update_params.append(int(payload[key] * 100))
        elif key == "category_raw":
            # Lookup en categories por nombre canonico
            cr_value = payload[key].strip()
            cat_rows = q("SELECT id FROM categories WHERE LOWER(name) = LOWER(%s)", (cr_value,))
            if cat_rows:
                update_parts.append("category_id = %s")
                update_params.append(cat_rows[0]['id'])
            else:
                # Si no existe la categoria, la creamos (v7.1: usar q_exec_returning + id)
                new_cat = q_exec_returning(
                    "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id",
                    (cr_value,)
                )
                if new_cat and 'id' in new_cat:
                    update_parts.append("category_id = %s")
                    update_params.append(new_cat['id'])
                else:
                    # Fallback de seguridad: no rompemos el update
                    logger.warning(f"reclasificar: no se pudo crear/encontrar categoria '{cr_value}'")
            # Tambien guardamos el category_raw para auditoria
            update_parts.append("category_raw = %s")
            update_params.append(cr_value)
        elif key == "category_name":
            # Alias de category_raw
            cn_value = payload[key].strip()
            cat_rows = q("SELECT id FROM categories WHERE LOWER(name) = LOWER(%s)", (cn_value,))
            if cat_rows:
                update_parts.append("category_id = %s")
                update_params.append(cat_rows[0]['id'])
        elif col:
            update_parts.append(f"{col} = %s")
            update_params.append(payload[key])
    if not update_parts:
        raise HTTPException(status_code=422, detail="No hay campos para actualizar")

    update_parts.append("verified_by = %s")
    update_params.append(user)
    update_parts.append("verified_at = NOW()")
    update_parts.append("updated_at = NOW()")
    update_params.append(factura_id)

    sql = f"UPDATE invoices SET {', '.join(update_parts)} WHERE id = %s"
    try:
        q_exec(sql, tuple(update_params))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error actualizando: {e}")

    # Insertar en tabla de auditoría (si existe; si no, la creamos)
    # Usamos un INSERT idempotente: si la tabla no existe, la creamos on-the-fly.
    # En producción la tabla se crea via migración 005.
    import json as _json
    from decimal import Decimal as _Dec
    from datetime import date as _Date, datetime as _DateTime
    class _JsonSafeEncoder(_json.JSONEncoder):
        def default(self, o):
            if isinstance(o, (_Dec, _Date, _DateTime)): return str(o)
            return super().default(o)
    try:
        q_exec("""
            INSERT INTO invoice_corrections
                (invoice_id, user_id, reason, before_json, after_json, created_at)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW())
        """, (
            factura_id,
            user,
            payload.get("reason", ""),
            _json.dumps({k: str(v) for k, v in old.items()}, cls=_JsonSafeEncoder),
            _json.dumps({k: payload.get(k, old.get(k)) for k in ["vendor_name","category_raw","total_amount","invoice_date","description"]}, cls=_JsonSafeEncoder),
        ))
    except psycopg2.errors.UndefinedTable:
        # Tabla no existe: la creamos y reintentamos (one-shot)
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS invoice_corrections (
                    id BIGSERIAL PRIMARY KEY,
                    invoice_id UUID NOT NULL,
                    user_id TEXT NOT NULL,
                    reason TEXT,
                    before_json JSONB,
                    after_json JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_invoice_corrections_invoice
                    ON invoice_corrections(invoice_id);
            """)
            conn.commit()
        finally:
            put_conn(conn)
        # Reintentar
        q_exec("""
            INSERT INTO invoice_corrections
                (invoice_id, user_id, reason, before_json, after_json, created_at)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW())
        """, (
            factura_id,
            user,
            payload.get("reason", ""),
            _json.dumps({k: str(v) for k, v in old.items()}, cls=_JsonSafeEncoder),
            _json.dumps({k: payload.get(k, old.get(k)) for k in ["vendor_name","category_raw","total_amount","invoice_date","description"]}, cls=_JsonSafeEncoder),
        ))
    except Exception as _aud_err:
        # NO tragamos el error: si la auditoría falla, lo logueamos para investigar.
        import logging as _logging
        _logging.getLogger("dashboard.app").error(f"reclasificar auditoria fallo: {_aud_err!r}", exc_info=True)

    # Devolver la fila actualizada
    new = q("""
        SELECT i.id, i.vendor_name, i.category_raw, i.total_amount, i.invoice_date,
               i.description, i.status, i.verified_by, i.verified_at, i.updated_at
        FROM invoices i WHERE id = %s
    """, (factura_id,))

    if not new:
        raise HTTPException(status_code=500, detail="Factura desapareció tras update")

    out = to_dict(new[0])
    out["correction_reason"] = payload.get("reason")
    return out


@app.get("/api/gastos/stats")
def api_gastos_stats(user: str = Depends(get_current_user)):
    """Estadísticas globales de gastos (para header de la vista)."""
    r = q(f"""
        SELECT count(*) as total_facturas,
               coalesce(sum(total_amount), 0) as total_eur,
               coalesce(avg(total_amount), 0) as ticket_medio,
               count(distinct vendor_name) as vendors_unicos,
               count(*) FILTER (WHERE category_id IS NULL) as sin_categoria,
               count(*) FILTER (WHERE raw_file_url IS NOT NULL) as con_pdf,
               count(*) FILTER (WHERE raw_file_url IS NULL) as sin_pdf,
               min(invoice_date) as primera,
               max(invoice_date) as ultima
        FROM invoices WHERE {expense_filter()}
    """)[0]
    total = int(r["total_facturas"]) or 1
    return {
        "total_facturas": total,
        "total_eur": float(r["total_eur"]),
        "ticket_medio": float(r["ticket_medio"]),
        "vendors_unicos": int(r["vendors_unicos"]),
        "facturas_sin_categoria": int(r["sin_categoria"]),
        "facturas_con_pdf": int(r["con_pdf"]),
        "facturas_sin_pdf": int(r["sin_pdf"]),
        "ratio_pdf_disponible": int(r["con_pdf"]) / total,
        "primera": r["primera"].isoformat() if r["primera"] else None,
        "ultima": r["ultima"].isoformat() if r["ultima"] else None,
    }


@app.get("/api/gastos/{factura_id}")
def api_gastos_detalle(factura_id: str, user: str = Depends(get_current_user)):
    """Detalle completo de una factura de gasto por id (UUID)."""
    import re as _re_det
    # v7.1.1: Validar UUID para evitar 500 al hacer SELECT ... = 'not-a-uuid'
    if not _re_det.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', factura_id, _re_det.I):
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    rows = q("""
        SELECT i.id, i.invoice_number, i.invoice_date, i.due_date, i.vendor_name,
               i.vendor_tax_id, i.base_amount, i.tax_amount, i.total_amount, i.currency,
               i.category_raw, c.name as category_name, c.color as category_color,
               i.status, i.source, i.source_account, i.description, i.raw_file_url,
               i.confidence_score, i.created_at, i.updated_at, i.verified_by, i.verified_at,
               i.tags, i.parsed_json
        FROM invoices i
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE i.id = %s AND i.type = 'expense'
    """, (factura_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    fac = to_dict(rows[0])

    # Pagos asociados (tabla opcional: payments puede no existir en todos los entornos).
    fac["pagos"] = []
    try:
        pagos = q("SELECT payment_date, amount, source, source_detail, reference FROM payments WHERE invoice_id = %s ORDER BY payment_date DESC", (factura_id,))
        fac["pagos"] = [to_dict(r) for r in pagos]
    except Exception:
        pass

    # ¿Existe el PDF en disco?
    pdf_exists = False
    pdf_size = None
    if fac.get("raw_file_url"):
        try:
            import os as _os
            p = fac["raw_file_url"]
            pdf_exists = _os.path.isfile(p)
            if pdf_exists:
                pdf_size = _os.path.getsize(p)
        except Exception:
            pass

    fac["pagos"] = fac.get("pagos", [])
    fac["pdf_exists"] = pdf_exists
    fac["pdf_size_bytes"] = pdf_size
    return fac


@app.get("/api/gastos/{factura_id}/pdf")
def api_gastos_pdf(factura_id: str, user: str = Depends(get_current_user)):
    """Descarga el PDF de una factura (raw_file_url). Solo lectura del archivo.

    v7.1 PRO: Validaciones de seguridad contra path traversal:
      - factura_id debe ser UUID válido
      - pdf_path resuelto debe estar dentro de data/invoices/raw/
    """
    import re as _re
    from pathlib import Path as _Path
    from fastapi.responses import FileResponse
    # v7.1: Validar formato UUID para evitar inyeccion de path en la URL
    if not _re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', factura_id, _re.I):
        raise HTTPException(status_code=400, detail="ID de factura invalido (debe ser UUID)")
    rows = q("SELECT raw_file_url, invoice_number, vendor_name FROM invoices WHERE id = %s::uuid AND type = 'expense'", (factura_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    r = rows[0]
    pdf_path = r["raw_file_url"]
    if not pdf_path:
        raise HTTPException(status_code=404, detail="Esta factura no tiene PDF asociado")
    # v7.1: Verificar que la ruta resuelta esta dentro del directorio permitido (anti path-traversal)
    try:
        raw_root = (_Path("/root/liados") / "data" / "invoices" / "raw").resolve()
        resolved = _Path(pdf_path).resolve()
        resolved.relative_to(raw_root)  # lanza ValueError si esta fuera
    except (ValueError, OSError) as _e:
        raise HTTPException(status_code=403, detail="Acceso al archivo denegado") from None
    if not _Path(pdf_path).is_file():
        raise HTTPException(status_code=404, detail="PDF no encontrado en disco")
    vendor = (r["vendor_name"] or "vendor").replace(" ", "_").replace("/", "-")[:40]
    num = (r["invoice_number"] or "sinn").replace("/", "-")[:30]
    filename = f"{vendor}_{num}.pdf"
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)


@app.get("/api/gastos/timeline/groups")
def api_gastos_timeline_groups(user: str = Depends(get_current_user)):
    """Distribución temporal de gastos por día para heatmap calendario.
    Grupo por día con total + nº facturas."""
    return [to_dict(r) for r in q(f"""
        SELECT to_char(invoice_date, 'YYYY-MM-DD') as dia,
               count(*) as n,
               coalesce(sum(total_amount), 0) as total
        FROM invoices
        WHERE {expense_filter()}
          AND invoice_date >= now() - interval '12 months'
        GROUP BY dia ORDER BY dia
    """)]



@app.get("/api/alertas")
def api_alertas(user: str = Depends(get_current_user)):
    """Detector de anomalías y alertas operativas. Todo on-the-fly (SQL), sin LLM.
    Severidades: high | medium | low | info. Ordenado por severidad."""
    from datetime import timedelta
    items = []

    def sev_rank(s):
        return {"high": 0, "medium": 1, "low": 2, "info": 3}.get(s, 9)

    now = datetime.utcnow()

    # 1. venta_caida: Δ% MoM < -30% (solo si mes actual tiene datos)
    try:
        comp = q("""
            SELECT to_char(date_trunc('month', creation_time), 'YYYY-MM') as mes,
                   coalesce(sum(total_cents), 0)/100.0 as total
            FROM lastapp_bills
            WHERE deleted = false AND creation_time >= date_trunc('month', now()) - interval '1 month'
            GROUP BY 1
        """)
        v = {r["mes"]: float(r["total"]) for r in comp}
        cur_key = now.strftime("%Y-%m")
        prev_dt = now.replace(day=1) - timedelta(days=1)
        prev_key = prev_dt.strftime("%Y-%m")
        v_cur, v_prev = v.get(cur_key, 0), v.get(prev_key, 0)
        if v_prev > 0 and v_cur > 0:
            delta = (v_cur - v_prev) / v_prev * 100
            if delta < -30:
                items.append({
                    "id": "venta_caida_mom",
                    "severity": "high" if delta < -50 else "medium",
                    "tipo": "venta_caida",
                    "titulo": f"Caída del {abs(delta):.0f}% en ventas vs mes anterior",
                    "descripcion": f"Las ventas de {cur_key} ({v_cur:,.0f}€) son un {abs(delta):.0f}% inferiores a {prev_key} ({v_prev:,.0f}€).".replace(",", "."),
                    "contexto": {"actual": v_cur, "anterior": v_prev, "delta_pct": round(delta, 1), "periodo": "MoM"},
                    "accion_sugerida": "Revisar si el sync de Last.app está al día o si hay días sin actividad registrada.",
                    "cta": {"label": "Analizar en chat", "prefill": f"¿Por qué cayeron las ventas un {abs(delta):.0f}% este mes?"},
                })
    except Exception as _e:
        logger.warning(f"detector #1 fallo: " + repr(_e))

    # 2. canal_ausente: canal con ventas hace 7d pero 0 en últimos 3d
    try:
        canales = q("""
            WITH reciente AS (
                SELECT p.type as canal, count(*) as n
                FROM lastapp_payments p JOIN lastapp_bills b ON b.id = p.bill_id
                WHERE b.deleted = false AND p.deleted = false
                  AND b.creation_time >= now() - interval '3 days'
                GROUP BY p.type
            ), previo AS (
                SELECT p.type as canal, count(*) as n
                FROM lastapp_payments p JOIN lastapp_bills b ON b.id = p.bill_id
                WHERE b.deleted = false AND p.deleted = false
                  AND b.creation_time >= now() - interval '7 days'
                  AND b.creation_time < now() - interval '3 days'
                GROUP BY p.type
            )
            SELECT previo.canal, previo.n as n_prev, coalesce(reciente.n, 0) as n_reciente
            FROM previo LEFT JOIN reciente ON reciente.canal = previo.canal
            WHERE previo.n >= 3 AND coalesce(reciente.n, 0) = 0
        """)
        for r in canales:
            items.append({
                "id": f"canal_ausente_{r['canal']}",
                "severity": "medium",
                "tipo": "canal_ausente",
                "titulo": f"Canal '{r['canal']}' sin ventas en 3 días",
                "descripcion": f"El canal {r['canal']} tuvo {r['n_prev']} ventas hace 4-7 días pero 0 en los últimos 3 días.",
                "contexto": {"canal": r["canal"], "n_prev": int(r["n_prev"]), "n_reciente": int(r["n_reciente"])},
                "accion_sugerida": "Verificar si hay incidencia con el proveedor de delivery o si es estacionalidad.",
                "cta": {"label": "Ver ventas por canal", "prefill": f"¿Cómo van las ventas del canal {r['canal']} esta semana?"},
            })
    except Exception as _e:
        logger.warning(f"detector #2 fallo: " + repr(_e))

    # 3. gasto_pico: gasto diario > 2.5× media últimos 30d
    try:
        pico = q("""
            WITH base AS (
                SELECT coalesce(avg(daily), 0) as media
                FROM (
                    SELECT date(invoice_date) as d, sum(total_amount) as daily
                    FROM invoices
                    WHERE type = 'expense' AND status != 'rejected' AND is_invoice = true
                      AND invoice_date >= now() - interval '30 days'
                    GROUP BY d
                ) s
            )
            SELECT to_char(i.invoice_date, 'YYYY-MM-DD') as dia,
                   sum(i.total_amount) as total,
                   b.media
            FROM invoices i CROSS JOIN base b
            WHERE i.type = 'expense' AND i.status != 'rejected' AND i.is_invoice = true
              AND i.invoice_date >= now() - interval '3 days'
              AND b.media > 0
            GROUP BY i.invoice_date, b.media
            HAVING sum(i.total_amount) > b.media * 2.5
            ORDER BY i.invoice_date DESC LIMIT 3
        """)
        for r in pico:
            ratio = float(r["total"]) / float(r["media"]) if r["media"] else 0
            items.append({
                "id": f"gasto_pico_{r['dia']}",
                "severity": "medium",
                "tipo": "gasto_pico",
                "titulo": f"Pico de gasto el {r['dia']} ({ratio:.1f}× la media)",
                "descripcion": f"El gasto del {r['dia']} ({float(r['total']):.2f}€) es {ratio:.1f} veces la media diaria de los últimos 30 días ({float(r['media']):.2f}€).",
                "contexto": {"dia": r["dia"], "total": float(r["total"]), "media": float(r["media"]), "ratio": round(ratio, 1)},
                "accion_sugerida": "Revisar si es un gasto puntual esperado (compra mensual) o un error de categorización.",
                "cta": {"label": "Ver facturas del día", "prefill": f"Muéstrame las facturas de gasto del {r['dia']}"},
            })
    except Exception as _e:
        logger.warning(f"detector #3 fallo: " + repr(_e))

    # 4. factura_sin_categoria: facturas nuevas (7d) sin categorizar
    try:
        sc = q("""
            SELECT count(*) as n, coalesce(sum(total_amount), 0) as total
            FROM invoices
            WHERE category_id IS NULL AND is_invoice = true AND type = 'expense'
              AND created_at >= now() - interval '7 days'
        """)[0]
        if int(sc["n"]) > 0:
            items.append({
                "id": "facturas_sin_categoria",
                "severity": "low" if int(sc["n"]) < 5 else "medium",
                "tipo": "factura_sin_categoria",
                "titulo": f"{sc['n']} facturas nuevas sin categorizar ({float(sc['total']):.0f}€)",
                "descripcion": f"En los últimos 7 días entraron {sc['n']} facturas sin categoría asignada, sumando {float(sc['total']):.2f}€.",
                "contexto": {"n": int(sc["n"]), "total": float(sc["total"])},
                "accion_sugerida": "Revisar y asignar categoría desde la vista de Gastos.",
                "cta": {"label": "Ver facturas sin categoría", "prefill": "Muéstrame las facturas sin categoría de los últimos 7 días"},
            })
    except Exception as _e:
        logger.warning(f"detector #4 fallo: " + repr(_e))

    # 5. sync_stale: sync_control con status != ok o muy antiguo
    try:
        sync = q("""
            SELECT source, last_sync, items_processed, errors, status,
                   extract(epoch from now() - last_sync)/3600 as horas
            FROM sync_control WHERE status != 'ok' OR last_sync < now() - interval '6 hours'
        """)
        for r in sync:
            horas = float(r["horas"]) if r["horas"] is not None else 0
            items.append({
                "id": f"sync_stale_{r['source']}",
                "severity": "high" if r["status"] == "error" else ("medium" if horas > 12 else "low"),
                "tipo": "sync_stale",
                "titulo": f"Sync '{r['source']}' en estado {r['status']}",
                "descripcion": f"La sincronización de {r['source']} está en estado '{r['status']}' hace {horas:.1f} horas.",
                "contexto": {"source": r["source"], "horas": round(horas, 1), "status": r["status"], "errors": int(r["errors"] or 0)},
                "accion_sugerida": "Ejecutar manualmente el collector correspondiente y revisar los logs.",
                "cta": {"label": "Ver logs", "prefill": f"¿Qué errores hay en el sync de {r['source']}?"},
            })
    except Exception as _e:
        logger.warning(f"detector #5 fallo: " + repr(_e))

    # 6. facturas_sin_pdf: ratio de facturas sin PDF
    try:
        pdf_stats = q(f"""
            SELECT count(*) as total,
                   count(*) FILTER (WHERE raw_file_url IS NULL) as sin_pdf
            FROM invoices WHERE {expense_filter()}
        """)[0]
        total_f = int(pdf_stats["total"])
        sin_pdf = int(pdf_stats["sin_pdf"])
        if total_f > 0 and sin_pdf / total_f > 0.2:
            items.append({
                "id": "facturas_sin_pdf",
                "severity": "info",
                "tipo": "facturas_sin_pdf",
                "titulo": f"{sin_pdf} facturas ({sin_pdf/total_f*100:.0f}%) sin PDF adjunto",
                "descripcion": f"De {total_f} facturas de gasto, {sin_pdf} no tienen el archivo PDF disponible para descarga.",
                "contexto": {"total": total_f, "sin_pdf": sin_pdf, "ratio": round(sin_pdf / total_f, 2)},
                "accion_sugerida": "Informativo. No bloquea la operativa.",
                "cta": None,
            })
    except Exception as _e:
        logger.warning(f"detector #6 fallo: " + repr(_e))

    # 7. locales_huerfanos: bills sin location_id (post-migración debería ser 0)
    try:
        orphans = q("SELECT count(*) as n FROM lastapp_bills WHERE location_id IS NULL AND deleted = false")[0]
        n = int(orphans["n"])
        if n > 0:
            items.append({
                "id": "locales_huerfanos",
                "severity": "low",
                "tipo": "locales_huerfanos",
                "titulo": f"{n} facturas sin local asignado",
                "descripcion": f"Hay {n} facturas de Last.app con location_id NULL. Considerar re-ejecutar la migración 005.",
                "contexto": {"n": n},
                "accion_sugerida": "Revisar y ejecutar db/migrations/005_fix_sin_local.sql si procede.",
                "cta": None,
            })
    except Exception as _e:
        logger.warning(f"detector #7 fallo: " + repr(_e))

    # 8. duplicado_potencial: facturas con mismo vendor+total±3d
    # v7.1 PRO: GROUP BY + EXISTS (no self-join cuadrático)
    try:
        dups = q("""
            WITH grupos AS (
                SELECT vendor_name, total_amount
                FROM invoices
                WHERE type = 'expense' AND status NOT IN ('rejected','duplicate')
                  AND is_invoice = true
                  AND vendor_name IS NOT NULL
                  AND total_amount IS NOT NULL
                GROUP BY vendor_name, total_amount
                HAVING count(*) > 1
                  AND bool_and(
                    abs(
                      extract(epoch FROM (max(invoice_date) - min(invoice_date))) <= 259200
                    )
                  )
            )
            SELECT count(*) as n FROM grupos
        """)[0]
        n_dup = int(dups["n"])
        if n_dup > 0:
            items.append({
                "id": "duplicados_potenciales",
                "severity": "medium",
                "tipo": "duplicado_potencial",
                "titulo": f"{n_dup} posibles facturas duplicadas",
                "descripcion": f"Se detectaron {n_dup} pares de facturas con mismo proveedor, mismo importe y fechas a ±3 días que no están marcadas como duplicadas.",
                "contexto": {"n": n_dup},
                "accion_sugerida": "Revisar y marcar como 'duplicate' las que correspondan.",
                "cta": {"label": "Ver posibles duplicados", "prefill": "Muéstrame las facturas que podrían estar duplicadas"},
            })
    except Exception as _e:
        logger.warning(f"detector #8 fallo: " + repr(_e))

    # 9. ticket_anomalo: facturas con importe > 5× la mediana histórica (últimos 6m).
    #    Detecta outliers como LS1-8242 (13.913€ vs mediana ~22€).
    try:
        outliers = q("""
            WITH stats AS (
                SELECT
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY total_cents) as mediana,
                    count(*) as n
                FROM lastapp_bills
                WHERE deleted = false
                  AND creation_time >= now() - interval '6 months'
            )
            SELECT b.id::text, b.number, b.creation_time,
                   b.total_cents/100.0 as eur,
                   (b.total_cents::float / NULLIF(s.mediana, 0)) as ratio_mediana,
                   s.mediana/100.0 as mediana_eur
            FROM lastapp_bills b, stats s
            WHERE b.deleted = false
              AND b.creation_time >= now() - interval '60 days'
              AND s.n >= 30
              AND b.total_cents > GREATEST(s.mediana * 5, 50000)
            ORDER BY ratio_mediana DESC
            LIMIT 3
        """)
        for r in outliers:
            ratio = float(r["ratio_mediana"]) if r["ratio_mediana"] else 0
            sev = "high" if ratio >= 50 else ("medium" if ratio >= 10 else "low")
            items.append({
                "id": f"ticket_anomalo_{r['id']}",
                "severity": sev,
                "tipo": "ticket_anomalo",
                "titulo": f"Factura outlier {r['number']} ({float(r['eur']):.0f}€, {ratio:.1f}× mediana)",
                "descripcion": f"La factura {r['number']} del {r['creation_time'].strftime('%Y-%m-%d %H:%M')} tiene un importe de {float(r['eur']):.2f}€, que es {ratio:.1f}× la mediana del último medio año ({float(r['mediana_eur']):.2f}€). Verificar si es legítima (evento grande, backfill) o error de captura.",
                "contexto": {"id": r["id"], "number": r["number"], "eur": float(r["eur"]), "ratio_mediana": round(ratio, 1), "mediana_eur": float(r["mediana_eur"])},
                "accion_sugerida": "Comprobar en Last.app que la factura es real. Si es backfill de datos históricos, marcar como verificada. Si es error, corregir el importe.",
                "cta": {"label": "Ver factura", "prefill": f"Analiza la factura {r['number']} de {float(r['eur']):.0f}€ del {r['creation_time'].strftime('%d/%m/%Y')}"},
            })
    except Exception as _e:
        logger.warning(f"detector #9 fallo: " + repr(_e))

    items.sort(key=lambda x: sev_rank(x["severity"]))
    resumen = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for it in items:
        resumen[it["severity"]] += 1

    return {
        "generated_at": now.isoformat() + "Z",
        "items": items,
        "resumen": resumen,
        "total": len(items),
    }


# ── API: Gestión de alertas (dismiss / acknowledge) ──────────────

class _AlertAckRequest(BaseModel):
    alert_id: str
    note: Optional[str] = None


@app.post("/api/alertas/ack")
def api_alertas_ack(req: _AlertAckRequest, user: str = Depends(get_current_user)):
    """Marca una alerta como revisada. Persiste en agent_logs (no crea tabla nueva).

    Body: {"alert_id": "ticket_anomalo_xxx", "note": "verificado en Last.app"}

    Devuelve: {"ack_id": "uuid", "alert_id": "...", "acked_at": "...", "acked_by": "jefe"}
    """
    try:
        details = {
            "alert_id": req.alert_id,
            "note": req.note or "",
            "acked_by": user,
        }
        # Insertar como log de tipo 'info' (no es warning/error, es ack)
        rows = q_exec("""
            INSERT INTO agent_logs (source, level, message, details)
            VALUES ('alertas', 'info', %s, %s::jsonb)
            RETURNING id, timestamp
        """, (f"ack: {req.alert_id}", json.dumps(details, ensure_ascii=False)))
        new_id = str(rows[0]["id"])
        ts = rows[0]["timestamp"].isoformat() if rows[0]["timestamp"] else datetime.utcnow().isoformat()
        return {"ack_id": new_id, "alert_id": req.alert_id, "acked_at": ts, "acked_by": user}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando ack: {e}")


@app.get("/api/alertas/ack")
def api_alertas_ack_list(user: str = Depends(get_current_user)):
    """Lista los acks de alertas (últimos 100). Útil para sincronizar entre dispositivos."""
    try:
        rows = q("""
            SELECT id, timestamp,
                   details->>'alert_id' as alert_id_extracted,
                   details->>'note' as note_extracted,
                   details->>'acked_by' as acked_by_extracted
            FROM agent_logs
            WHERE source = 'alertas' AND level = 'info' AND message LIKE 'ack: %%'
            ORDER BY timestamp DESC
            LIMIT 100
        """)
        return {
            "acks": [
                {
                    "ack_id": str(r["id"]),
                    "alert_id": r["alert_id_extracted"],
                    "note": r["note_extracted"],
                    "acked_by": r["acked_by_extracted"],
                    "acked_at": r["timestamp"].isoformat() if r["timestamp"] else None,
                }
                for r in rows
            ],
            "total": len(rows),
        }
    except Exception as e:
        logger.exception(f"alertas ack list fallo: {e!r}")
        _tb.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listando acks: {e}")


# ── HTML Dashboard ─────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0a0f1d">
<link rel="icon" href="/static/icons/icon-192.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/static/icons/icon-192.svg">
<link rel="manifest" href="/static/manifest.webmanifest">
<title>Liados · Dashboard</title>
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/app.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body>
<div class="app" id="app">
  <div class="sidebar-backdrop" id="backdrop"></div>

  <!-- ── Sidebar ── -->
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-head">
      <div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2h8M9 2v6.5a5.5 5.5 0 0 0 6 5.48M9 8.5a5.5 5.5 0 0 1-6 5.48M5.5 14h13M12 19v3"/></svg></div>
      <div class="brand">Liados<small>Analytics</small></div>
    </div>
    <nav class="sidebar-nav">
      <div class="nav-section-label">Operativa</div>
      <a class="nav-item active" data-view="dashboard"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg><span class="nav-label">Dashboard</span></a>
      <a class="nav-item" data-view="ventas"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg><span class="nav-label">Ventas</span></a>
      <a class="nav-item" data-view="gastos"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg><span class="nav-label">Gastos</span></a>
      <a class="nav-item" data-view="gastos-detalle"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg><span class="nav-label">Detalle gastos</span></a>
      <a class="nav-item" data-view="alertas"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg><span class="nav-label">Alertas</span><span class="nav-badge" id="nav-alert-badge"></span></a>
      <a class="nav-item" data-view="desglose"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/></svg><span class="nav-label">Desglose</span><span class="kbd-inline">g → b</span></a>
      <div class="nav-section-label">Restaurante</div>
      <a class="nav-item" data-view="productos"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/></svg><span class="nav-label">Productos</span></a>
      <div class="nav-section-label">Sistema</div>
      <a class="nav-item" data-view="config"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg><span class="nav-label">Configuración</span></a>
    </nav>
    <div class="sidebar-foot">
      <span class="live-dot"></span>
      <div class="foot-text">Datos en vivo<br><b id="syncTime">cargando…</b></div>
    </div>
  </aside>

  <!-- ── Header ── -->
  <header class="header">
    <button class="icon-btn" id="sidebarToggle" title="Menú"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>
    <div class="crumbs"><b id="crumbView">Dashboard</b></div>
    <div class="header-spacer"></div>
    <span id="clock" style="color:var(--fg-2);font-size:var(--fz-sm);padding-right:var(--s-3)"></span>
    <label class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg><input type="text" placeholder="Buscar…"><kbd>/</kbd></label>
    <button class="icon-btn" id="themeToggle" title="Cambiar tema"></button>
  </header>

   <!-- ── Main ── -->
   <main class="main">
   <div id="last-invoice-card" data-loading="1">Cargando última factura extraída...</div>
   <script>
    // B3: Cargar la card server-rendered. Usa misma auth que el resto de la app.
    _fetchAuth("/api/invoices/last-invoice-card")
      .then(r => r.ok ? r.text() : Promise.reject(new Error("HTTP "+r.status)))
      .then(html => { const el = document.getElementById("last-invoice-card"); if (el) el.innerHTML = html; })
      .catch(() => { const el = document.getElementById("last-invoice-card"); if (el) el.innerHTML = ""; });
   </script>

    <!-- ═══ Vista: Dashboard ═══ -->
    <section class="view active" data-view="dashboard">
    <!-- Hero -->
    <section class="hero">
      <div>
        <div class="hero-label">💰 Margen del mes</div>
        <div class="hero-value pos" id="heroValue">0€</div>
        <div style="margin-bottom:var(--s-2)"><span class="delta flat" id="heroDelta">—</span></div>
        <div class="hero-meta" id="heroMeta"></div>
      </div>
      <div class="hero-spark"><canvas id="heroSpark"></canvas></div>
    </section>

    <!-- KPIs -->
    <div class="kpis" id="kpis"></div>

    <!-- Grid -->
    <div class="grid">
      <div class="card grid-full">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><rect x="7" y="11" width="3" height="7"/><rect x="12" y="7" width="3" height="11"/><rect x="17" y="13" width="3" height="5"/></svg><h2>Ventas por canal</h2><span class="subtitle">últimos 6 meses</span>
          <div class="actions"><select class="seg" id="canalFilter"></select></div>
        </div>
        <div class="card-body"><div class="chart-wrap tall"><canvas id="chart-canales"></canvas></div></div>
      </div>

      <div class="card grid-full">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg><h2>Tendencia diaria</h2><span class="subtitle">últimos 30 días</span>
          <div class="actions"><div class="seg-group"><button id="momToggle">vs mes anterior</button></div></div>
        </div>
        <div class="card-body"><div class="chart-wrap"><canvas id="chart-diario"></canvas></div></div>
      </div>

      <div class="card">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg><h2>Canales este mes</h2></div>
        <div class="card-body"><div class="bars" id="canal-mes"></div></div>
      </div>

      <div class="card">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/></svg><h2>Ventas por local</h2><span class="subtitle">este mes</span></div>
        <div class="card-body"><div class="bars" id="local-mes"></div></div>
      </div>

      <div class="card">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg><h2>Margen por mes</h2></div>
        <div class="card-body"><div id="margen"></div></div>
      </div>

      <div class="card">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg><h2>Ingresos por mes</h2><div class="actions"><a class="icon-btn sm" href="/api/export/ingresos" title="Exportar CSV" download><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></a></div></div>
        <div class="card-body" id="ingresos"></div>
      </div>

      <div class="card">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg><h2>Gastos por proveedor</h2><div class="actions"><a class="icon-btn sm" href="/api/export/proveedores" title="Exportar CSV" download><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></a></div></div>
        <div class="card-body"><div class="bars" id="proveedores"></div></div>
      </div>

      <div class="card">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg><h2>Gastos por categoría</h2><div class="actions"><a class="icon-btn sm" href="/api/export/categorias" title="Exportar CSV" download><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></a></div></div>
        <div class="card-body"><div class="bars" id="categorias"></div></div>
      </div>

      <div class="card grid-full">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13h6M9 17h4"/></svg><h2>Últimas facturas</h2><div class="actions"><a class="icon-btn sm" href="/api/export/facturas" title="Exportar CSV" download><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></a></div></div>
        <div class="card-body" id="facturas"></div>
      </div>
    </div>
    </section><!-- /view dashboard -->

    <!-- ═══ Vista: Ventas ═══ -->
    <section class="view" data-view="ventas">
      <div class="card">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg><h2>Evolución de ventas (90 días)</h2><span class="subtitle">ingresos diarios</span></div>
        <div class="card-body"><div class="chart-wrap tall"><canvas id="ventas-chart-90"></canvas></div></div>
      </div>
      <div class="grid">
        <div class="card">
          <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg><h2>Canales · histórico 6 meses</h2></div>
          <div class="card-body"><div class="bars" id="ventas-canales-hist"></div></div>
        </div>
        <div class="card">
          <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg><h2>Resumen mensual de ingresos</h2><div class="actions"><a class="icon-btn sm" href="/api/export/ingresos" title="Exportar CSV" download><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></a></div></div>
          <div class="card-body" id="ventas-resumen"></div>
        </div>
      </div>
      <p class="view-hint">💡 ¿Quieres más detalle? Abre el <b>asistente AI</b> 💬 y pregunta «¿cuáles son mis 5 productos más vendidos esta semana?».</p>
    </section>

    <!-- ═══ Vista: Gastos ═══ -->
    <section class="view" data-view="gastos">
      <div class="card">
        <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg><h2>Todos los proveedores</h2><span class="subtitle">click en una fila para ver detalle</span><div class="actions"><a class="icon-btn sm" href="/api/export/proveedores" title="Exportar CSV" download><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></a></div></div>
        <div class="card-body" id="gastos-tabla"></div>
      </div>
      <div class="grid">
        <div class="card">
          <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg><h2>Gastos por categoría</h2><span class="subtitle">click para drill-down</span><div class="actions"><a class="icon-btn sm" href="/api/export/categorias" title="Exportar CSV" download><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></a></div></div>
          <div class="card-body"><div class="bars" id="gastos-categorias"></div></div>
        </div>
        <div class="card">
          <div class="card-head"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg><h2>Margen mensual</h2><span class="subtitle">ingresos vs gastos</span></div>
          <div class="card-body"><div id="gastos-margen"></div></div>
        </div>
      </div>
    </section>

    <!-- ═══ Vista: Gastos Detalle (nueva v6) ═══ -->
    <section class="view" data-view="gastos-detalle">
      <!-- Header con stats -->
      <div class="gd-stats" id="gd-stats">
        <div class="gd-stat"><span class="gd-stat-label">Facturas</span><b id="gd-stat-n">—</b></div>
        <div class="gd-stat"><span class="gd-stat-label">Total</span><b id="gd-stat-total">—</b></div>
        <div class="gd-stat"><span class="gd-stat-label">Ticket medio</span><b id="gd-stat-ticket">—</b></div>
        <div class="gd-stat"><span class="gd-stat-label">Vendors únicos</span><b id="gd-stat-vendors">—</b></div>
        <div class="gd-stat"><span class="gd-stat-label">Con PDF</span><b id="gd-stat-pdf">—</b></div>
      </div>

      <!-- Desglose multidimensional -->
      <div class="card gd-desglose-card">
        <div class="card-head">
          <h2>📊 Desglose multidimensional</h2>
          <span class="subtitle">Agrupar facturas por varias dimensiones</span>
        </div>
        <div class="card-body">
          <div class="gd-desglose-controls">
            <label class="gd-field"><span>Agrupar por</span>
              <select id="gd-desglose-dims">
                <option value="category">Categoría</option>
                <option value="vendor">Proveedor</option>
                <option value="month">Mes</option>
                <option value="quarter">Trimestre</option>
                <option value="cuenta">Cuenta (Gmail)</option>
                <option value="source">Origen (gmail/drive/erp)</option>
                <option value="status">Estado</option>
                <option value="category,month">Categoría × Mes</option>
                <option value="category,vendor">Categoría × Proveedor</option>
              </select>
            </label>
            <label class="gd-field"><span>Métrica</span>
              <select id="gd-desglose-metric">
                <option value="sum">Suma €</option>
                <option value="count">Nº facturas</option>
                <option value="avg">Ticket medio €</option>
                <option value="max">Importe máximo €</option>
              </select>
            </label>
            <label class="gd-field"><span>Importe ≥ €</span>
              <input type="number" id="gd-desglose-min" min="0" step="0.01" placeholder="0">
            </label>
            <button class="btn primary" id="gd-desglose-apply">Aplicar desglose</button>
          </div>
          <div id="gd-desglose-results" class="gd-desglose-results">
            <div class="muted">Selecciona agrupación + métrica y pulsa «Aplicar desglose»</div>
          </div>
        </div>
      </div>

      <!-- Filtros -->
      <div class="gd-filters card">
        <div class="gd-filter-row">
          <label class="gd-search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg><input type="text" id="gd-q" placeholder="Buscar factura, vendor, descripción…" autocomplete="off"></label>
          <label class="gd-field"><span>Desde</span><input type="date" id="gd-from"></label>
          <label class="gd-field"><span>Hasta</span><input type="date" id="gd-to"></label>
          <button class="btn primary" id="gd-apply">Aplicar</button>
          <button class="btn ghost" id="gd-clear">Limpiar</button>
          <div class="gd-spacer"></div>
          <a class="btn ghost" href="/api/export/facturas" download title="Exportar CSV">Exportar CSV</a>
        </div>
        <div class="gd-filter-row">
          <label class="gd-field"><span>Vendor</span><input type="text" id="gd-vendor" placeholder="ej. Makro" list="gd-vendors-list" autocomplete="off"></label>
          <datalist id="gd-vendors-list"></datalist>
          <label class="gd-field"><span>Categoría</span><input type="text" id="gd-cat" placeholder="ej. Suministros"></label>
          <label class="gd-field"><span>Cuenta</span><select id="gd-cuenta"><option value="">Todas</option><option value="principal">principal</option><option value="secundaria">secundaria</option></select></label>
          <label class="gd-field"><span>Status</span><select id="gd-status"><option value="">Todos</option><option value="verified">Verificada</option><option value="classified">Clasificada</option><option value="pending">Pendiente</option><option value="paid">Pagada</option></select></label>
          <label class="gd-field"><span>Importe ≥</span><input type="number" id="gd-min" min="0" step="0.01" placeholder="0"></label>
          <label class="gd-field"><span>Importe ≤</span><input type="number" id="gd-max" min="0" step="0.01" placeholder="∞"></label>
        </div>
      </div>

      <!-- Tabla -->
      <div class="card">
        <div class="card-head">
          <h2>Facturas de gasto</h2>
          <span class="subtitle" id="gd-result-count">—</span>
        </div>
        <div class="card-body" id="gd-table-wrap">
          <div class="skeleton-table" aria-hidden="true">
            <div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>
            <div class="skeleton-row"></div><div class="skeleton-row"></div>
          </div>
        </div>
        <div class="card-foot">
          <button class="btn ghost" id="gd-prev" disabled>← Anterior</button>
          <span id="gd-page-info">—</span>
          <button class="btn ghost" id="gd-next" disabled>Siguiente →</button>
        </div>
      </div>
    </section>

    <!-- ═══ Vista: Alertas (nueva v6) ═══ -->
    <section class="view" data-view="alertas">
      <div class="al-header">
        <div>
          <h2>🔔 Alertas y anomalías</h2>
          <span class="subtitle">Detector automático · Última actualización: <span id="al-generated">—</span></span>
        </div>
        <div class="al-header-actions">
          <button class="btn ghost" id="al-bulk-ack" style="display:none">✓ Marcar todas como revisadas</button>
          <div class="al-resumen" id="al-resumen"></div>
        </div>
      </div>
      <div id="al-list" class="al-list">
        <div class="skeleton-card" aria-hidden="true"></div>
        <div class="skeleton-card" aria-hidden="true"></div>
      </div>
    </section>

    <!-- ═══ Vista: Desglose (nueva v8) ═══ -->
    <section class="view" data-view="desglose">
      <!-- Tabs estilo Excel -->
      <div class="excel-tabs" id="excel-tabs">
        <button class="excel-tab active" data-tab="resumen">
          <span class="excel-tab-ico">📋</span>
          <span>Resumen</span>
        </button>
        <button class="excel-tab" data-tab="analisis">
          <span class="excel-tab-ico">📊</span>
          <span>Análisis (matriz)</span>
        </button>
        <button class="excel-tab" data-tab="top">
          <span class="excel-tab-ico">🏆</span>
          <span>Top N</span>
        </button>
        <button class="excel-tab" data-tab="calendario">
          <span class="excel-tab-ico">📅</span>
          <span>Calendario</span>
        </button>
        <button class="excel-tab" data-tab="comparar">
          <span class="excel-tab-ico">⚖️</span>
          <span>Comparar</span>
        </button>
        <div class="excel-tabs-spacer"></div>
        <button class="excel-tab-excel" id="desglose-export-btn" title="Exportar pestaña activa a CSV">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>CSV</span>
        </button>
      </div>

      <!-- Filtros globales persistentes -->
      <div class="card gd-filters">
        <div class="gd-filter-row">
          <label class="gd-field"><span>Desde</span><input type="date" id="dg-from"></label>
          <label class="gd-field"><span>Hasta</span><input type="date" id="dg-to"></label>
          <label class="gd-field"><span>Cuenta</span>
            <select id="dg-cuenta">
              <option value="">Todas</option>
              <option value="principal">principal</option>
              <option value="secundaria">secundaria</option>
            </select>
          </label>
          <button class="btn primary" id="dg-apply">🔄 Aplicar a todas las pestañas</button>
          <span class="dg-gen-at" id="dg-gen-at"></span>
        </div>
      </div>

      <!-- TAB: Resumen -->
      <div class="excel-panel active" data-tab-panel="resumen">
        <div class="resumen-grid" id="resumen-grid">
          <div class="skeleton-card"></div>
          <div class="skeleton-card"></div>
          <div class="skeleton-card"></div>
          <div class="skeleton-card"></div>
        </div>
      </div>

      <!-- TAB: Análisis (matriz) -->
      <div class="excel-panel" data-tab-panel="analisis">
        <div class="card">
          <div class="card-head">
            <h2>📊 Matriz cruzada</h2>
            <span class="subtitle">Selecciona dimensiones filas × columnas</span>
          </div>
          <div class="card-body">
            <div class="gd-matrix-controls">
              <label class="gd-field"><span>Filas</span>
                <select id="mtx-rows">
                  <option value="month">Mes</option>
                  <option value="vendor">Proveedor</option>
                  <option value="category">Categoría</option>
                  <option value="cuenta">Cuenta</option>
                  <option value="status">Estado</option>
                </select>
              </label>
              <label class="gd-field"><span>Columnas</span>
                <select id="mtx-cols">
                  <option value="category" selected>Categoría</option>
                  <option value="month">Mes</option>
                  <option value="vendor">Proveedor</option>
                  <option value="cuenta">Cuenta</option>
                  <option value="status">Estado</option>
                </select>
              </label>
              <label class="gd-field"><span>Métrica</span>
                <select id="mtx-metric">
                  <option value="sum" selected>Suma €</option>
                  <option value="count">Nº facturas</option>
                  <option value="avg">Ticket medio</option>
                  <option value="max">Máximo</option>
                </select>
              </label>
              <button class="btn primary" id="mtx-apply">Generar matriz</button>
            </div>
            <div id="mtx-results" class="mtx-results"></div>
          </div>
        </div>
      </div>

      <!-- TAB: Top N -->
      <div class="excel-panel" data-tab-panel="top">
        <div class="card">
          <div class="card-head">
            <h2>🏆 Top N elementos</h2>
            <div class="gd-top-controls">
              <label class="gd-field"><span>Agrupar por</span>
                <select id="top-by">
                  <option value="vendor" selected>Proveedor</option>
                  <option value="category">Categoría</option>
                  <option value="cuenta">Cuenta</option>
                  <option value="source">Origen</option>
                </select>
              </label>
              <label class="gd-field"><span>Métrica</span>
                <select id="top-metric">
                  <option value="sum" selected>Suma €</option>
                  <option value="count">Nº facturas</option>
                  <option value="avg">Ticket medio</option>
                </select>
              </label>
              <label class="gd-field"><span>Top</span>
                <input type="number" id="top-limit" min="5" max="100" value="20" step="5">
              </label>
              <label class="gd-toggle">
                <input type="checkbox" id="top-sparkline">
                <span>Mostrar tendencia 6m</span>
              </label>
              <button class="btn primary" id="top-apply">Generar Top</button>
            </div>
          </div>
          <div class="card-body" id="top-results"></div>
        </div>
      </div>

      <!-- TAB: Calendario (heatmap) -->
      <div class="excel-panel" data-tab-panel="calendario">
        <div class="card">
          <div class="card-head">
            <h2>📅 Calendario de gastos</h2>
            <div class="gd-cal-controls">
              <label class="gd-field"><span>Año</span>
                <input type="number" id="cal-year" min="2024" max="2030" step="1">
              </label>
              <button class="btn primary" id="cal-apply">Cargar calendario</button>
              <span class="gd-legend">
                <span class="gd-legend-box" style="background:var(--green-100)"></span>
                <small>bajo</small>
                <span class="gd-legend-box" style="background:var(--green-400)"></span>
                <small>medio</small>
                <span class="gd-legend-box" style="background:var(--green-700)"></span>
                <small>alto</small>
              </span>
            </div>
          </div>
          <div class="card-body" id="cal-results"></div>
        </div>
      </div>

      <!-- TAB: Comparar -->
      <div class="excel-panel" data-tab-panel="comparar">
        <div class="card">
          <div class="card-head">
            <h2>⚖️ Comparar 2 períodos</h2>
            <div class="gd-cmp-controls">
              <label class="gd-field"><span>Agrupar por</span>
                <select id="cmp-by">
                  <option value="vendor" selected>Proveedor</option>
                  <option value="category">Categoría</option>
                  <option value="cuenta">Cuenta</option>
                </select>
              </label>
            </div>
          </div>
          <div class="card-body">
            <div class="gd-cmp-ranges">
              <fieldset>
                <legend>Período 1 (actual)</legend>
                <label class="gd-field"><span>Desde</span><input type="date" id="cmp-p1-from"></label>
                <label class="gd-field"><span>Hasta</span><input type="date" id="cmp-p1-to"></label>
              </fieldset>
              <fieldset>
                <legend>Período 2 (comparar)</legend>
                <label class="gd-field"><span>Desde</span><input type="date" id="cmp-p2-from"></label>
                <label class="gd-field"><span>Hasta</span><input type="date" id="cmp-p2-to"></label>
                <div class="gd-cmp-presets">
                  <button type="button" class="btn ghost sm" data-cmp-preset="prev-month">Mes anterior</button>
                  <button type="button" class="btn ghost sm" data-cmp-preset="same-last-year">Mismo período año anterior</button>
                </div>
              </fieldset>
              <button class="btn primary" id="cmp-apply">Comparar</button>
            </div>
            <div id="cmp-results"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- ═══ Vista: Productos (próximamente) ═══ -->
    <section class="view" data-view="productos">
      <div class="coming-soon">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/></svg>
        <h2>Catálogo de productos</h2>
        <p>Próximamente: top productos más vendidos, disponibilidad por local y control de stock. Mientras tanto, pregunta al <b>asistente AI</b> 💬 por tus productos más vendidos.</p>
      </div>
    </section>

    <!-- ═══ Vista: Productos (nueva v8.3) ═══ -->
    <section class="view" data-view="productos">
      <div class="pr-stats" id="pr-stats">
        <div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div>
      </div>
      <div class="pr-controls">
        <input type="search" id="pr-search" placeholder="🔍 Buscar producto..." autocomplete="off">
        <label class="pr-toggle"><input type="checkbox" id="pr-available-only"> <span>Solo disponibles</span></label>
        <select id="pr-sort">
          <option value="name">Nombre A-Z</option>
          <option value="price-asc">Precio ↑</option>
          <option value="price-desc">Precio ↓</option>
        </select>
        <span class="pr-gen-at" id="pr-gen-at"></span>
      </div>
      <div id="pr-list" class="pr-list">
        <div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div>
      </div>
    </section>

    <!-- ═══ Vista: Configuración (nueva v6) ═══ -->
    <section class="view" data-view="config">
      <div class="card">
        <div class="card-head"><h2>🔌 Fuentes de datos</h2><span class="subtitle">Estado de los conectores</span></div>
        <div class="card-body" id="cfg-fuentes">
          <div class="skeleton-card" aria-hidden="true"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h2>🛠️ Sistema</h2></div>
        <div class="card-body">
          <dl class="cfg-list">
            <dt>Versión dashboard</dt><dd id="cfg-version">—</dd>
            <dt>Base de datos</dt><dd id="cfg-db">—</dd>
            <dt>Pool conexiones</dt><dd id="cfg-pool">—</dd>
            <dt>Documentación</dt><dd><a href="/api/health" target="_blank">/api/health</a> · <a href="/static/app.js" target="_blank">app.js</a> · <a href="https://github.com/anomalyco/opencode" target="_blank" rel="noopener">OpenCode</a></dd>
          </dl>
        </div>
      </div>
    </section>

    <footer class="appfoot">Liados · Vamos al lío S.L. · B22774590 · <a href="/api/health">estado API</a></footer>
  </main>
</div>

<!-- ── Chat ── -->
<button class="chat-fab" id="chatFab" title="Asistente AI"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg><span class="fab-badge"></span></button>
<div class="chat-panel" id="chatPanel">
  <div class="chat-head">
    <div class="title"><span class="av">🤖</span> Asistente Liados</div>
    <button class="icon-btn" id="chatClose"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
  </div>
  <div class="chat-body" id="chatBody"></div>
  <div class="chat-suggest" id="chatSuggest"></div>
  <div class="chat-input">
    <input id="chatText" type="text" placeholder="Pregúntame sobre ventas, facturas, productos…" autocomplete="off">
    <button id="chatSend"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
  </div>
</div>

<!-- ── Modal: búsqueda global ── -->
<div class="modal-overlay" id="searchModal">
  <div class="modal modal-search" role="dialog" aria-label="Búsqueda">
    <div class="modal-search-bar">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
      <input id="searchInput" type="text" placeholder="Buscar proveedores, categorías, facturas…" autocomplete="off">
      <kbd class="esc-hint">Esc</kbd>
    </div>
    <div class="modal-search-results" id="searchResults"></div>
  </div>
</div>

<!-- ── Modal: drill-down ── -->
<div class="modal-overlay" id="drillModal">
  <div class="modal" role="dialog" aria-label="Detalle">
    <div class="modal-head">
      <h3 id="drillTitle">Detalle</h3>
      <button class="icon-btn" data-close="drillModal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
    </div>
    <div class="modal-body" id="drillBody"></div>
  </div>
</div>

<!-- ── Modal: ayuda atajos ── -->
<div class="modal-overlay" id="helpModal">
  <div class="modal" role="dialog" aria-label="Atajos">
    <div class="modal-head"><h3>⌨️ Atajos de teclado</h3><button class="icon-btn" data-close="helpModal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>
    <div class="modal-body">
      <table class="kbd-table">
        <tr><td><kbd>⌘K</kbd> / <kbd>Ctrl+K</kbd></td><td>Command palette</td></tr>
        <tr><td><kbd>/</kbd></td><td>Buscar</td></tr>
        <tr><td><kbd>C</kbd></td><td>Abrir/cerrar asistente AI</td></tr>
        <tr><td><kbd>R</kbd></td><td>Refrescar datos</td></tr>
        <tr><td><kbd>T</kbd></td><td>Cambiar tema claro/oscuro</td></tr>
        <tr><td><kbd>G</kbd> + <kbd>D/V/G/A/B/C</kbd></td><td>Ir a Dashboard/Ventas/Gastos/Alertas/<b>Desglose</b>/Config</td></tr>
        <tr><td><kbd>?</kbd></td><td>Esta ayuda</td></tr>
        <tr><td><kbd>Esc</kbd></td><td>Cerrar ventana activa</td></tr>
      </table>
    </div>
  </div>
</div>

<!-- ── Modal: detalle de factura (gastos) ── -->
<div class="modal-overlay" id="facturaModal">
  <div class="modal modal-factura" role="dialog" aria-label="Detalle de factura">
    <div class="modal-head">
      <h3 id="factura-title">Factura</h3>
      <button class="icon-btn" data-close="facturaModal" aria-label="Cerrar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
    </div>
    <div class="modal-body" id="factura-body">Cargando…</div>
  </div>
</div>

<!-- ── Toast notifications ── -->
<div class="toast-container" id="toastContainer" aria-live="polite" aria-atomic="true"></div>

<!-- ── Modal: command palette (⌘K) ── -->
<div class="modal-overlay" id="paletteModal">
  <div class="modal modal-palette" role="dialog" aria-label="Command palette">
    <div class="palette-bar">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
      <input id="paletteInput" type="text" placeholder="Buscar vista, acción o comando…" autocomplete="off">
      <kbd class="esc-hint">Esc</kbd>
    </div>
    <div class="palette-results" id="paletteResults"></div>
  </div>
</div>

<script src="/static/app.js"></script>
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js').catch(() => {});
  });
}
</script>
</body>
</html>"""



@app.get("/api/invoices/last-invoice")
def last_invoice(account: str = "", user: str = Depends(get_current_user)):
    """Última factura extraída. ?account=principal filtra por cuenta.
    200 con {last_invoice: null} si no hay facturas.
    B3: usa created_at (timestamp with time zone) como received_at fallback.
    Campos reales del esquema: invoice_number, vendor_name, raw_file_url, total_amount."""
    where = ""
    params = []
    if account:
        where = "WHERE source_account = %s"
        params.append(account)
    rows = q(f"""
        SELECT id, invoice_number, source, source_account,
               to_char(invoice_date, 'YYYY-MM-DD') as date,
               to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as received_at,
               raw_file_url as filename,
               vendor_name as vendor,
               total_amount,
               currency
        FROM invoices
        {where}
        ORDER BY created_at DESC
        LIMIT 1
    """, tuple(params))
    if not rows:
        return {"last_invoice": None, "as_of": q("SELECT NOW() as now")[0]["now"].isoformat()}
    r = rows[0]
    return {
        "last_invoice": {
            "id": str(r["id"]),
            "invoice_number": r["invoice_number"],
            "source": r["source"],
            "source_account": r["source_account"],
            "date": r["date"],
            "received_at": r["received_at"],
            "filename": r["filename"],
            "vendor": r["vendor"],
            "total_amount": float(r["total_amount"]) if r["total_amount"] is not None else None,
            "currency": r["currency"],
        },
        "as_of": q("SELECT NOW() as now")[0]["now"].isoformat(),
    }


@app.get("/api/invoices/by-date-range")
def invoices_by_date_range(
    from_: str = Query("", alias="from"),   # URL usa ?from= pero Python keyword = from_
    to: str = "",
    source: str = "",
    user: str = Depends(get_current_user),
):
    """Facturas agrupadas por fecha en un rango. ?source=gmail|lastapp filtra.
    Parametros: ?from=YYYY-MM-DD, &to=YYYY-MM-DD, &source=gmail|lastapp.
    422 si invalido, from>to, o rango fuera de [hoy-1y, hoy]."""
    # Validacion
    from datetime import datetime
    if not from_:
        raise HTTPException(status_code=422, detail="from es obligatorio (YYYY-MM-DD)")
    try:
        dt_from = datetime.strptime(from_, "%Y-%m-%d")
        dt_to = datetime.strptime(to, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="from/to deben ser YYYY-MM-DD")
    if dt_from > dt_to:
        raise HTTPException(status_code=422, detail="from no puede ser mayor que to")
    today = datetime.utcnow().date()
    if dt_from.date() < (today.replace(year=today.year - 1)) or dt_to.date() > today:
        raise HTTPException(status_code=422, detail="rango fuera de [today-1y, today]")

    where = "WHERE invoice_date BETWEEN %s AND %s"
    params = [from_, to]
    if source:
        where += " AND source = %s"
        params.append(source)
    rows = q(f"""
        SELECT to_char(invoice_date, 'YYYY-MM-DD') as d,
               count(*) as count,
               coalesce(sum(total_amount), 0) as total
        FROM invoices
        {where}
        GROUP BY 1
        ORDER BY 1
    """, tuple(params))
    return [{"date": r["d"], "count": int(r["count"]),
             "total_amount": float(r["total"])} for r in rows]

@app.get("/api/invoices/last-invoice-card", response_class=HTMLResponse)
def last_invoice_card(account: str = "", user: str = Depends(get_current_user)):
    """Fragmento HTML server-rendered con la última factura extraída.
    Usado por la card UI del dashboard (B3). Patron: server-side render
    para que funcione aunque app.js este deshabilitado."""
    payload = last_invoice(account=account, user=user)
    li = payload.get("last_invoice")
    if not li:
        html = (
            '<div class="card last-invoice empty">'
            '<h3>Última factura extraída</h3>'
            '<p>Aún no hay facturas extraídas.</p>'
            '</div>'
        )
        return HTMLResponse(html)
    currency = li.get("currency") or ""
    amount = li.get("total_amount")
    amount_str = f"{amount:.2f} {currency}" if amount is not None else "-"
    from html import escape as _h
    # v7.1 PRO: escape de TODO dato externo (vendor, invoice_number, etc.) para
    # evitar XSS almacenado si una factura trae payload con HTML/JS.
    html = (
        '<div class="card last-invoice">'
        '<h3>Última factura extraída</h3>'
        f'<div class="li-row"><span class="li-label">Numero</span><b>{_h(str(li["invoice_number"]))}</b></div>'
        f'<div class="li-row"><span class="li-label">Vendor</span><b>{_h(str(li["vendor"] or "-"))}</b></div>'
        f'<div class="li-row"><span class="li-label">Importe</span><b>{_h(amount_str)}</b></div>'
        f'<div class="li-row"><span class="li-label">Fecha factura</span><b>{_h(str(li["date"]))}</b></div>'
        f'<div class="li-row"><span class="li-label">Cuenta</span><b>{_h(str(li["source_account"] or "-"))} ({_h(str(li["source"]))})</b></div>'
        f'<div class="li-meta">Extraida: {_h(str(li["received_at"]))} · Endpoint: /api/invoices/last-invoice</div>'
        '</div>'
        '<style>.card.last-invoice{padding:1rem;background:var(--bg-1,#0e1426);border-radius:12px;margin:1rem 0}'
        '.card.last-invoice h3{margin:0 0 .5rem 0;font-size:1rem}'
        '.card.last-invoice .li-row{display:flex;justify-content:space-between;padding:.25rem 0;font-size:.9rem}'
        '.card.last-invoice .li-label{color:#7a8aa3}'
        '.card.last-invoice .li-meta{margin-top:.5rem;font-size:.75rem;color:#5a6378}'
        '.card.last-invoice.empty p{color:#7a8aa3;font-style:italic}</style>'
    )
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
def index(user: str = Depends(get_current_user)):
    return INDEX_HTML


# ── v7.1 PRO: Reclasificar v2 (seguro, solo categoria) ─────────────────
# Reemplazo al endpoint original que permitia modificar vendor/total/fecha
# (vectores de fraude y XSS). Solo categoria + nota, con UUID validado.

from pydantic import BaseModel as _BM, Field as _F
from typing import Optional as _Opt
import re as _re_v7

class _ReclasificarPayload(_BM):
    category_name: str = _F(..., min_length=1, max_length=80, strip_whitespace=True, description="Nombre canonico de la categoria (sin espacios al inicio/final)")
    reason: str = _F(..., min_length=1, max_length=500, strip_whitespace=True, description="Motivo del cambio (auditable, sin espacios al inicio/final)")


@app.post("/api/gastos/{factura_id}/reclasificar-v2")
def api_gastos_reclasificar_v2(factura_id: str, payload: _ReclasificarPayload, user: str = Depends(get_current_user)):
    """v7.1: Reclasificacion SEGURA. Solo permite cambiar categoria.

    Cambios vs v7:
    - Validacion UUID regex (anti path-injection en la URL)
    - Pydantic valida category_name y reason (no pueden ser vacios ni > 80/500 chars)
    - Solo se actualiza category_id + category_raw + audit fields
    - NO se permite cambiar vendor/total/fecha/descripcion (reduccion de superficie)
    """
    # 1. Validar UUID
    if not _re_v7.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', factura_id, _re_v7.I):
        raise HTTPException(status_code=400, detail="ID de factura invalido (debe ser UUID)")

    # 2. Verificar factura existe
    rows = q("SELECT id, category_raw FROM invoices WHERE id = %s::uuid AND type = 'expense'", (factura_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    old = dict(rows[0])

    # 3. Buscar categoria por nombre (case-insensitive). Auto-crear si no existe.
    cat_rows = q("SELECT id, name FROM categories WHERE LOWER(name) = LOWER(%s)", (payload.category_name.strip(),))
    if cat_rows:
        category_id = cat_rows[0]['id']
        category_db_name = cat_rows[0]['name']
    else:
        new_cat = q_exec_returning(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id, name",
            (payload.category_name.strip(),)
        )
        if not new_cat or 'id' not in new_cat:
            raise HTTPException(status_code=500, detail="No se pudo crear/encontrar la categoria")
        category_id = new_cat['id']
        category_db_name = new_cat['name']

    # 4. UPDATE SOLO de categoria (no tocar otros campos)
    try:
        q_exec(
            "UPDATE invoices SET category_id = %s, category_raw = %s, "
            "verified_by = %s, verified_at = NOW(), updated_at = NOW() WHERE id = %s::uuid",
            (category_id, category_db_name, user, factura_id)
        )
    except Exception as e:
        logger.exception(f"reclasificar v2 UPDATE fallo: {e!r}")
        raise HTTPException(status_code=500, detail="Error actualizando la factura")

    # 5. Auditoria (best-effort, no rompe si falla)
    try:
        from datetime import date as _Ad, datetime as _Adt
        from decimal import Decimal as _Ad_dec
        import json as _Aj
        class _AdEncoder(_Aj.JSONEncoder):
            def default(self, o):
                if isinstance(o, (_Ad_dec, _Ad, _Adt)): return str(o)
                return super().default(o)
        q_exec("""
            INSERT INTO invoice_corrections
                (invoice_id, user_id, reason, before_json, after_json, created_at)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW())
        """, (
            factura_id, user, payload.reason,
            _Aj.dumps({k: str(v) for k, v in old.items()}, cls=_AdEncoder),
            _Aj.dumps({"category_raw": category_db_name, "category_id": str(category_id)}, cls=_AdEncoder),
        ))
    except Exception as _ae:
        logger.warning(f"reclasificar v2: auditoria no insertada ({_ae!r})")

    return {
        "ok": True,
        "factura_id": factura_id,
        "category_id": str(category_id),
        "category_name": category_db_name,
        "verified_by": user,
    }


# ── v8.0 PRO: Desglose "Excel-style" con 3 espacios y 6 vistas ──────────
# - Espacio 1: Resumen (kpis globales)
# - Espacio 2: Análisis (matrices 2D: Mes×Cat, Vendor×Mes, Cat×Vendor)
# - Espacio 3: Tendencias (Top N + Heatmap Anual Mes×Día + Comparador 2 periodos)
#
# Fixes integrados tras contradictores (security + perf + ux):
# - Whitelist estricto de dimensiones (anti SQLi/PII exfiltration)
# - GROUP BY en SQL (no en Python) -> rendimiento
# - Single query con array_agg para top-N (anti N+1)
# - Caché con key basada en filtros + role (anti multi-tenancy leak)
# - CSV sanitization contra formula injection (= + - @ \t \r)

import hashlib as _hl
from datetime import datetime as _dt
import json as _json


# Whitelist de dimensiones permitidas (CRÍTICO: anti SQLi en pivot dinámico)
DESGLOSE_ALLOWED_DIMS = {
    "vendor": "vendor_name",
    "category": "category_raw",  # o COALESCE(c.name, i.category_raw) si JOIN
    "cuenta": "source_account",
    "source": "source",
    "month": "_month",
    "quarter": "_quarter",
    "year": "_year",
    "week": "_week",
    "day": "_day",
    "status": "status",
}

DESGLOSE_ALLOWED_METRICS = {"count", "sum", "avg", "min", "max"}


def _desglose_sql_for(metric_alias: str, total_col: str = "total_amount") -> str:
    """Traduce la métrica pública a SQL real. count NO multiplica por importe."""
    return {
        "count": "count(*)",
        "sum": f"sum({total_col})",
        "avg": f"avg({total_col})",
        "min": f"min({total_col})",
        "max": f"max({total_col})",
    }[metric_alias]


def _sanitize_csv_value(v) -> str:
    """v8.0: CSV/Excel formula injection prevention.

    Si el valor empieza por =, +, -, @, \\t o \\r, Excel lo interpreta como formula
    (riesgo de DDE/exec de payloads). Prefijamos con apostrofo (que Excel trata como
    "literal text") o strip del caracter peligroso.
    """
    if v is None:
        return ""
    s = str(v)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s  # previene formula injection
    return s


def _sanitize_filename(s: str) -> str:
    """v8.0: Sanitiza un nombre de archivo contra path traversal en exports."""
    import re as _re_fn
    if not s:
        return "untitled"
    s = s.replace("/", "_").replace("\\", "_").replace("..", "_")
    s = _re_fn.sub(r"[^A-Za-z0-9_\-.]", "_", s)
    return s[:120] or "untitled"


def _desglose_safe_cache_key(namespace: str, dims, metric, date_from, date_to, cuenta, status, min_eur, max_eur, user, extra=""):
    """v8.0: Cache key con scope de usuario. Previene multi-tenant cache leak."""
    raw = _json.dumps({
        "ns": namespace,
        "dims": sorted(dims),
        "metric": metric,
        "from": date_from,
        "to": date_to,
        "cuenta": cuenta,
        "status": status,
        "min": min_eur,
        "max": max_eur,
        "user": user,
        "extra": extra,
    }, sort_keys=True, default=str)
    return "desglose:" + _hl.sha256(raw.encode()).hexdigest()[:16]


# Caché en memoria con TTL (sin Redis para mantener simple). TTL 5 min por defecto.
_DESGLOSE_CACHE = {}
_DESGLOSE_CACHE_TTL_S = 300


def _cache_get(key):
    e = _DESGLOSE_CACHE.get(key)
    if not e:
        return None
    if (_dt.now().timestamp() - e["ts"]) > _DESGLOSE_CACHE_TTL_S:
        _DESGLOSE_CACHE.pop(key, None)
        return None
    return e["data"]


def _cache_put(key, data):
    _DESGLOSE_CACHE[key] = {"ts": _dt.now().timestamp(), "data": data}
    # LRU simple: limitar tamaño para no crecer infinito
    if len(_DESGLOSE_CACHE) > 200:
        # borrar los 20 más antiguos
        sorted_keys = sorted(_DESGLOSE_CACHE.items(), key=lambda kv: kv[1]["ts"])
        for k, _ in sorted_keys[:20]:
            _DESGLOSE_CACHE.pop(k, None)


def _parse_period(date_from: str, date_to: str, period_key: str = "default"):
    """v8.0: Centraliza parseo de fechas yyyy-mm-dd (antes recalculado por endpoint)."""
    from datetime import datetime as _dtp
    df = None
    dt = None
    if date_from:
        try:
            df = _dtp.strptime(date_from, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="date_from debe ser YYYY-MM-DD")
    if date_to:
        try:
            dt = _dtp.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="date_to debe ser YYYY-MM-DD")
    if df and dt and df > dt:
        raise HTTPException(status_code=422, detail="date_from debe ser <= date_to")
    return df, dt


# ── ENDPOINT 1: Resumen (kpis globales del desglose) ──────────────────

@app.get("/api/gastos/desglose/resumen")
def api_desglose_resumen(
    date_from: str = Query(None, description="YYYY-MM-DD"),
    date_to: str = Query(None, description="YYYY-MM-DD"),
    cuenta: str = Query(None, description="Filtrar por source_account"),
    user: str = Depends(get_current_user),
):
    """v8.0: KPIs del desglose (total facturas, total €, ticket medio, top proveedor, top categoría).

    1 sola query (subquerys) -> no N+1.
    """
    df, dt = _parse_period(date_from, date_to)
    cache_key = _desglose_safe_cache_key(
        "resumen", [], "sum", date_from, date_to, cuenta, None, None, None, user,
        extra=f"{df or ''}|{dt or ''}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    where_parts = [expense_filter()]
    params = []
    if df:
        where_parts.append("i.invoice_date >= %s")
        params.append(df)
    if dt:
        where_parts.append("i.invoice_date <= %s")
        params.append(dt)
    if cuenta:
        where_parts.append("i.source_account = %s")
        params.append(cuenta)
    where_sql = " AND ".join(where_parts)

    row = q(f"""
        WITH base AS (
          SELECT i.vendor_name as vendor_name,
                 COALESCE(c.name, i.category_raw) as category,
                 i.total_amount as total_amount,
                 i.invoice_date as invoice_date
          FROM invoices i
          LEFT JOIN categories c ON c.id = i.category_id
          WHERE {where_sql}
        )
        SELECT
          count(*) as total_facturas,
          coalesce(sum(total_amount), 0) as total_eur,
          coalesce(avg(total_amount), 0) as ticket_medio,
          coalesce(max(total_amount), 0) as maximo,
          coalesce(min(total_amount), 0) as minimo,
          count(DISTINCT vendor_name) as n_vendors,
          count(DISTINCT category) as n_categories,
          (SELECT vendor_name FROM base WHERE vendor_name IS NOT NULL GROUP BY vendor_name ORDER BY sum(total_amount) DESC NULLS LAST LIMIT 1) as top_vendor,
          COALESCE((SELECT sum(total_amount) FROM base WHERE vendor_name IS NOT NULL GROUP BY vendor_name ORDER BY sum(total_amount) DESC NULLS LAST LIMIT 1), 0) as top_vendor_eur,
          (SELECT category FROM base WHERE category IS NOT NULL GROUP BY category ORDER BY sum(total_amount) DESC LIMIT 1) as top_category,
          COALESCE((SELECT sum(total_amount) FROM base WHERE category IS NOT NULL GROUP BY category ORDER BY sum(total_amount) DESC LIMIT 1), 0) as top_category_eur,
          (SELECT count(*) FROM base WHERE invoice_date >= date_trunc('month', now())) as facturas_mes_actual,
          (SELECT coalesce(sum(total_amount),0) FROM base WHERE invoice_date >= date_trunc('month', now())) as eur_mes_actual
        FROM base
    """, tuple(params))[0]

    out = {
        "total_facturas": int(row["total_facturas"]),
        "total_eur": float(row["total_eur"]),
        "ticket_medio_eur": float(row["ticket_medio"]),
        "maximo_eur": float(row["maximo"]),
        "minimo_eur": float(row["minimo"]),
        "n_vendors": int(row["n_vendors"]),
        "n_categories": int(row["n_categories"]),
        "top_vendor": row["top_vendor"],
        "top_vendor_eur": float(row["top_vendor_eur"] or 0),
        "top_category": row["top_category"],
        "top_category_eur": float(row["top_category_eur"] or 0),
        "facturas_mes_actual": int(row["facturas_mes_actual"] or 0),
        "eur_mes_actual": float(row["eur_mes_actual"] or 0),
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }
    _cache_put(cache_key, out)
    return out


# ── ENDPOINT 2: Análisis (matrices 2D con drill-down de top-N) ─────────

@app.get("/api/gastos/desglose/matrix")
def api_desglose_matrix(
    rows: str = Query(..., description="Dimension filas (whitelist). ej: month|category|vendor"),
    cols: str = Query(..., description="Dimension columnas. ej: category|month|vendor"),
    metric: str = Query("sum", description="count|sum|avg|min|max"),
    date_from: str = Query(None, description="YYYY-MM-DD"),
    date_to: str = Query(None, description="YYYY-MM-DD"),
    cuenta: str = Query(None, description="Filtrar por source_account"),
    top_per_cell: int = Query(0, ge=0, le=5, description="Top-N facturas por celda (0=desactivado)"),
    min_eur: float = Query(None, ge=0),
    max_eur: float = Query(None, ge=0),
    user: str = Depends(get_current_user),
):
    """v8.0: Matriz 2D estilo Excel (filas × columnas) con métrica aplicada.

    Devuelve: {row_dims, col_dims, cells: [{row, col, value, count, top_invoices?}]}

    Performance:
    - 1 query principal (GROUP BY ambos dims)
    - Si top_per_cell>0: 1 query extra con array_agg para devolver las top-N
      facturas por celda (no N+1).
    """
    if metric not in DESGLOSE_ALLOWED_METRICS:
        raise HTTPException(status_code=422, detail=f"metric inválida: {metric}")
    if rows not in DESGLOSE_ALLOWED_DIMS or cols not in DESGLOSE_ALLOWED_DIMS:
        raise HTTPException(status_code=400, detail=f"Dimensión no permitida: rows={rows} cols={cols}")

    df, dt = _parse_period(date_from, date_to)

    row_alias = DESGLOSE_ALLOWED_DIMS[rows]
    col_alias = DESGLOSE_ALLOWED_DIMS[cols]
    metric_sql = _desglose_sql_for(metric)

    where_parts = [expense_filter()]
    params = []
    if df:
        where_parts.append("invoice_date >= %s")
        params.append(df)
    if dt:
        where_parts.append("invoice_date <= %s")
        params.append(dt)
    if cuenta:
        where_parts.append("source_account = %s")
        params.append(cuenta)
    if min_eur is not None:
        where_parts.append("total_amount >= %s")
        params.append(min_eur)
    if max_eur is not None:
        where_parts.append("total_amount <= %s")
        params.append(max_eur)
    where_sql = " AND ".join(where_parts)

    # SELECT segun dims
    def _select_expr(dim_alias):
        # _month, _quarter, _year, _week, _day son derivados de invoice_date
        if dim_alias.startswith("_"):
            base = "invoice_date"
            if dim_alias == "_month":  return f"to_char({base}, \'YYYY-MM\')"
            if dim_alias == "_quarter": return f"to_char({base}, \'YYYY\') || \'-Q\' || to_char(extract(quarter from {base}))"
            if dim_alias == "_year":   return f"to_char({base}, \'YYYY\')"
            if dim_alias == "_week":   return f"to_char({base}, \'YYYY\') || \'-W\' || to_char(extract(week from {base}))"
            if dim_alias == "_day":    return f"to_char({base}, \'YYYY-MM-DD\')"
        return dim_alias

    row_sel = _select_expr(row_alias)
    col_sel = _select_expr(col_alias)

    # v8.0: cache key
    cache_key = _desglose_safe_cache_key(
        "matrix", [rows, cols], metric, date_from, date_to, cuenta, None, min_eur, max_eur, user,
        extra=f"top={top_per_cell}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # 1 sola query: GROUP BY row + col
    sql = f"""
        SELECT {row_sel} as r_key, {col_sel} as c_key,
               {metric_sql} as value,
               count(*) as cnt
        FROM invoices i
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE {where_sql}
        GROUP BY r_key, c_key
        ORDER BY value DESC NULLS LAST
        LIMIT 5000
    """
    rows_data = q(sql, tuple(params))

    cells = []
    for r in rows_data:
        cell = {
            "row": r["r_key"],
            "col": r["c_key"],
            "value": float(r["value"]) if r["value"] is not None else 0,
            "count": int(r["cnt"]),
        }
        cells.append(cell)

    # v8.0: Top-N por celda (1 sola query con array_agg, no N+1)
    top_invoices_by_cell = {}
    if top_per_cell > 0 and cells:
        # Construir lista de pares (row_val, col_val) para WHERE
        # Limitar al top-100 cells por memoria
        seen = set()
        pairs = []
        for c in cells:
            k = (c["row"], c["col"])
            if k in seen:
                continue
            seen.add(k)
            pairs.append(k)
            if len(pairs) >= 100:
                break
        # array_agg de las top-N por (row, col)
        agg_sql = f"""
            WITH ranked AS (
              SELECT i.vendor_name as r_key, COALESCE(c.name, i.category_raw) as c_key,
                     i.id::text as fact_id, i.invoice_number, i.total_amount, i.invoice_date,
                     row_number() OVER (PARTITION BY {row_sel}, {col_sel} ORDER BY i.total_amount DESC) AS rn
              FROM invoices i
              LEFT JOIN categories c ON c.id = i.category_id
              WHERE {where_sql}
            )
            SELECT {row_sel} as r_key, {col_sel} as c_key,
                   jsonb_agg(jsonb_build_object(
                     'id', fact_id, 'invoice_number', invoice_number,
                     'total_amount', total_amount, 'date', invoice_date
                   ) ORDER BY rn) FILTER (WHERE rn <= %s) as top
            FROM ranked
            WHERE rn <= %s
            GROUP BY r_key, c_key
        """
        pairs_params = []
        for r_key, c_key in pairs:
            if row_alias.startswith("_"):
                # Para dims derivadas (_month etc) hay que calcular el valor
                pass
            # Es mas seguro pasar como string y comparar
            pairs_params.append(str(r_key))
            pairs_params.append(str(c_key))
        # Construir WHERE con IN tuples. Para simplificar hacemos un bucle.
        if pairs:
            top_rows = []
            for r_key, c_key in pairs:
                top_rows.extend([str(r_key), str(c_key)])
            placeholders = ",".join(["(%s,%s)"] * len(pairs))
            full_sql = f"""
                SELECT r_key::text, c_key::text, top
                FROM (
                  SELECT {row_sel} as r_key, {col_sel} as c_key,
                         jsonb_agg(jsonb_build_object(
                           'id', id, 'invoice_number', invoice_number,
                           'total_amount', total_amount, 'date', invoice_date
                         ) ORDER BY total_amount DESC) FILTER (WHERE rn <= %s) as top
                  FROM (
                    SELECT {row_sel}, {col_sel}, id, invoice_number, total_amount, invoice_date,
                           row_number() OVER (PARTITION BY {row_sel}, {col_sel} ORDER BY total_amount DESC) as rn
                    FROM invoices i
                    LEFT JOIN categories c ON c.id = i.category_id
                    WHERE {where_sql}
                  ) t
                  GROUP BY r_key, c_key
                ) agg
                WHERE (r_key::text, c_key::text) IN ({placeholders})
            """
            full_params = tuple([top_per_cell] + pairs_params)
            try:
                top_data = q(full_sql, full_params)
                for tr in top_data:
                    key = (tr["r_key"], tr["c_key"])
                    top_invoices_by_cell[key] = tr["top"] if tr["top"] else []
            except Exception as _te:
                logger.warning(f"top_per_cell query fallo: {_te!r}")

    # Asociar top_invoices a cells
    for cell in cells:
        key = (cell["row"], cell["col"])
        if key in top_invoices_by_cell:
            cell["top_invoices"] = top_invoices_by_cell[key]

    # Calcular totales
    grand_total_value = sum(c["value"] for c in cells)
    row_totals = {}
    col_totals = {}
    for c in cells:
        row_totals[c["row"]] = row_totals.get(c["row"], 0) + c["value"]
        col_totals[c["col"]] = col_totals.get(c["col"], 0) + c["value"]

    out = {
        "row_dim": rows,
        "col_dim": cols,
        "metric": metric,
        "cells": cells,
        "row_totals": row_totals,
        "col_totals": col_totals,
        "grand_total": grand_total_value,
        "n_cells": len(cells),
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }
    _cache_put(cache_key, out)
    return out


# ── ENDPOINT 3: Top N (lista ordenada con sparkline opcional) ─────────────

@app.get("/api/gastos/desglose/top")
def api_desglose_top(
    by: str = Query("vendor", description="Dimension: vendor|category|cuenta|source"),
    metric: str = Query("sum", description="count|sum|avg|min|max"),
    limit: int = Query(20, ge=1, le=200),
    date_from: str = Query(None, description="YYYY-MM-DD"),
    date_to: str = Query(None, description="YYYY-MM-DD"),
    cuenta: str = Query(None, description="Filtrar por source_account"),
    with_sparkline: bool = Query(False, description="Incluir serie 6m (1 query extra)"),
    min_eur: float = Query(None, ge=0),
    max_eur: float = Query(None, ge=0),
    user: str = Depends(get_current_user),
):
    """v8.0: Top N elementos ordenados por métrica. Opcional sparkline 6m por elemento."""
    if metric not in DESGLOSE_ALLOWED_METRICS:
        raise HTTPException(status_code=422, detail=f"metric inválida: {metric}")
    if by not in DESGLOSE_ALLOWED_DIMS:
        raise HTTPException(status_code=400, detail="by debe ser vendor|category|cuenta|source")

    df, dt = _parse_period(date_from, date_to)
    by_alias = DESGLOSE_ALLOWED_DIMS[by]
    metric_sql = _desglose_sql_for(metric)

    where_parts = [expense_filter()]
    params = []
    if df:
        where_parts.append("invoice_date >= %s")
        params.append(df)
    if dt:
        where_parts.append("invoice_date <= %s")
        params.append(dt)
    if cuenta:
        where_parts.append("source_account = %s")
        params.append(cuenta)
    if min_eur is not None:
        where_parts.append("total_amount >= %s")
        params.append(min_eur)
    if max_eur is not None:
        where_parts.append("total_amount <= %s")
        params.append(max_eur)
    where_sql = " AND ".join(where_parts)

    # SELECT expr: category necesita JOIN
    if by == "category":
        dim_expr = "COALESCE(c.name, i.category_raw)"
        join = "LEFT JOIN categories c ON c.id = i.category_id"
    elif by_alias.startswith("_"):
        # dims derivadas de invoice_date
        if by_alias == "_month": dim_expr = "to_char(invoice_date, 'YYYY-MM')"
        elif by_alias == "_quarter": dim_expr = "to_char(invoice_date, 'YYYY') || '-Q' || to_char(extract(quarter from invoice_date))"
        elif by_alias == "_year": dim_expr = "to_char(invoice_date, 'YYYY')"
        else: dim_expr = by_alias.lstrip("_")
        join = ""
    else:
        dim_expr = f"i.{by_alias}"
        join = ""

    sql = f"""
        SELECT {dim_expr} as dim, {metric_sql} as value, count(*) as cnt
        FROM invoices i
        {join}
        WHERE {where_sql}
        GROUP BY dim
        ORDER BY value DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)
    top_data = q(sql, tuple(params))

    items = []
    for r in top_data:
        v = r["value"]
        try:
            v_float = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            v_float = 0.0
        cnt = int(r["cnt"]) if r["cnt"] is not None else 0
        items.append({"dim": r["dim"], "value": v_float, "count": cnt})

    # Sparkline opcional: 1 query aggregate por mes
    if with_sparkline and items:
        spark_sql = f"""
            SELECT {dim_expr} as dim,
                   to_char(invoice_date, 'YYYY-MM') as month,
                   sum(total_amount) as eur
            FROM invoices i
            {join}
            WHERE {where_sql}
              AND to_char(invoice_date, 'YYYY-MM') >= to_char(now() - interval '6 months', 'YYYY-MM')
            GROUP BY dim, month
            ORDER BY month
            LIMIT 600
        """
        spark_data = q(spark_sql, tuple(params))
        # pivot por dim
        spark_by_dim = {}
        for s in spark_data:
            eur = s["eur"]
            try:
                eur_v = float(eur) if eur is not None else 0.0
            except (TypeError, ValueError):
                eur_v = 0.0
            spark_by_dim.setdefault(s["dim"], []).append({"month": s["month"], "eur": eur_v})
        for it in items:
            it["sparkline_6m"] = spark_by_dim.get(it["dim"], [])

    return {
        "by": by,
        "metric": metric,
        "items": items,
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }


# ── ENDPOINT 4: Heatmap Anual Mes×Día (12m reales, no semanas inventadas) ─

@app.get("/api/gastos/desglose/calendar")
def api_desglose_calendar(
    year: int = Query(None, description="Año (default = año actual)"),
    cuenta: str = Query(None, description="Filtrar por source_account"),
    min_eur: float = Query(None, ge=0),
    max_eur: float = Query(None, ge=0),
    user: str = Depends(get_current_user),
):
    """v8.0: Heatmap calendario Mes×Día del año especificado. 1 sola query con grouping completo."""
    from datetime import date as _date
    if not year:
        year = _date.today().year
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=400, detail="year fuera de rango")

    where_parts = [expense_filter(),
                   f"to_char(invoice_date, 'YYYY') = %s"]
    params = [str(year)]
    if cuenta:
        where_parts.append("source_account = %s")
        params.append(cuenta)
    if min_eur is not None:
        where_parts.append("total_amount >= %s")
        params.append(min_eur)
    if max_eur is not None:
        where_parts.append("total_amount <= %s")
        params.append(max_eur)
    where_sql = " AND ".join(where_parts)

    sql = f"""
        SELECT to_char(invoice_date, 'MM') as month,
               to_char(invoice_date, 'DD') as day,
               count(*) as cnt,
               sum(total_amount) as eur
        FROM invoices i
        WHERE {where_sql}
        GROUP BY month, day
        ORDER BY month, day
    """
    data = q(sql, tuple(params))

    # Transformar a grid mes×día[1-31]
    grid = {}
    for r in data:
        m = r["month"]
        d = r["day"]
        grid.setdefault(m, {})[d] = {"count": int(r["cnt"]) if r["cnt"] else 0, "eur": float(r["eur"] or 0)}

    # Calcular max para escala de color
    max_eur = max((d.get("eur", 0) for month in grid.values() for d in month.values()), default=0)
    total_eur = sum(d.get("eur", 0) for month in grid.values() for d in month.values())

    # v8.0: k-anonymity: ocultar celdas con count<3 (privacidad)
    censuradas = 0
    for month in grid.values():
        for d, val in list(month.items()):
            if val["count"] < 3:
                # mantener count pero ocultar eur exacto (en vez de borrar)
                month[d] = {"count": val["count"], "eur": None, "censored": True}
                censuradas += 1

    return {
        "year": year,
        "grid": grid,
        "max_eur": max_eur,
        "total_eur": total_eur,
        "total_count": sum(d.get("count", 0) for month in grid.values() for d in month.values() if d),
        "censored_cells": censuradas,
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }


# ── ENDPOINT 5: Comparador 2 periodos (1 sola query con FILTER WHERE) ─────

@app.get("/api/gastos/desglose/compare")
def api_desglose_compare(
    by: str = Query("vendor", description="vendor|category|cuenta"),
    p1_from: str = Query(..., description="YYYY-MM-DD"),
    p1_to: str = Query(..., description="YYYY-MM-DD"),
    p2_from: str = Query(..., description="YYYY-MM-DD"),
    p2_to: str = Query(..., description="YYYY-MM-DD"),
    cuenta: str = Query(None, description="Filtrar por source_account"),
    user: str = Depends(get_current_user),
):
    """v8.0: Compara 2 períodos en 1 sola query con FILTER WHERE."""
    if by not in DESGLOSE_ALLOWED_DIMS:
        raise HTTPException(status_code=400, detail="by debe ser vendor|category|cuenta")
    p1df, p1dt = _parse_period(p1_from, p1_to)
    p2df, p2dt = _parse_period(p2_from, p2_to)

    if by == "category":
        dim_expr = "COALESCE(c.name, i.category_raw)"
        join = "LEFT JOIN categories c ON c.id = i.category_id"
    elif DESGLOSE_ALLOWED_DIMS[by].startswith("_"):
        if DESGLOSE_ALLOWED_DIMS[by] == "_month": dim_expr = "to_char(invoice_date, 'YYYY-MM')"
        else: dim_expr = "invoice_date::text"
        join = ""
    else:
        dim_expr = f"i.{DESGLOSE_ALLOWED_DIMS[by]}"
        join = ""

    where_parts = [expense_filter()]
    params = []
    if cuenta:
        where_parts.append("i.source_account = %s")
        params.append(cuenta)
    where_sql = " AND ".join(where_parts)

    # v8.0: 1 sola query con FILTER (no 2 scans)
    # v8.0.1: fix precedencia SQL — WHERE x AND p1 OR p2 != WHERE x AND (p1 OR p2)
    # Sin parentesis, Postgres interpreta como (x AND p1) OR p2. Añadir parentesis.
    sql = f"""
        WITH base AS (
          SELECT {dim_expr} as dim, invoice_date, total_amount
          FROM invoices i
          {join}
          WHERE {where_sql}
            AND (invoice_date BETWEEN %s AND %s
              OR invoice_date BETWEEN %s AND %s)
        )
        SELECT dim,
               sum(total_amount) FILTER (WHERE invoice_date BETWEEN %s AND %s) AS p1,
               sum(total_amount) FILTER (WHERE invoice_date BETWEEN %s AND %s) AS p2,
               count(*) FILTER (WHERE invoice_date BETWEEN %s AND %s) AS p1_count,
               count(*) FILTER (WHERE invoice_date BETWEEN %s AND %s) AS p2_count
        FROM base
        WHERE dim IS NOT NULL
        GROUP BY dim
        ORDER BY p1 DESC NULLS LAST
        LIMIT 200
    """
    sql_params = tuple(params) + (p1df, p1dt, p2df, p2dt, p1df, p1dt, p2df, p2dt, p1df, p1dt, p2df, p2dt)
    rows = q(sql, sql_params)

    items = []
    for r in rows:
        p1 = float(r["p1"] or 0)
        p2 = float(r["p2"] or 0)
        delta = p1 - p2
        delta_pct = ((p1 - p2) / p2 * 100) if p2 > 0 else None
        items.append({
            "dim": r["dim"],
            "p1_total": p1,
            "p2_total": p2,
            "p1_count": int(r["p1_count"] or 0),
            "p2_count": int(r["p2_count"] or 0),
            "delta": delta,
            "delta_pct": delta_pct,
        })

    return {
        "by": by,
        "p1_from": p1_from, "p1_to": p1_to,
        "p2_from": p2_from, "p2_to": p2_to,
        "items": items,
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }


# ── ENDPOINT 6: Export CSV sanitizado (anti formula injection) ───────────

@app.get("/api/gastos/desglose/export.csv")
def api_desglose_export_csv(
    by: str = Query("vendor", description="vendor|category|cuenta|source|month"),
    date_from: str = Query(None, description="YYYY-MM-DD"),
    date_to: str = Query(None, description="YYYY-MM-DD"),
    cuenta: str = Query(None, description="Filtrar por source_account"),
    user: str = Depends(get_current_user),
):
    """v8.0: Exporta el desglose a CSV con sanitización contra formula injection."""
    if by not in DESGLOSE_ALLOWED_DIMS:
        raise HTTPException(status_code=400, detail="by debe ser vendor|category|cuenta|source|month")
    df, dt = _parse_period(date_from, date_to)

    if by == "category":
        dim_expr = "COALESCE(c.name, i.category_raw)"
        join = "LEFT JOIN categories c ON c.id = i.category_id"
    elif DESGLOSE_ALLOWED_DIMS[by] == "_month":
        dim_expr = "to_char(invoice_date, 'YYYY-MM')"
        join = ""
    else:
        dim_expr = f"i.{DESGLOSE_ALLOWED_DIMS[by]}"
        join = ""

    where_parts = [expense_filter()]
    params = []
    if df:
        where_parts.append("invoice_date >= %s")
        params.append(df)
    if dt:
        where_parts.append("invoice_date <= %s")
        params.append(dt)
    if cuenta:
        where_parts.append("source_account = %s")
        params.append(cuenta)
    where_sql = " AND ".join(where_parts)

    sql = f"""
        SELECT {dim_expr} as dim, count(*) as cnt, sum(total_amount) as eur
        FROM invoices i
        {join}
        WHERE {where_sql}
        GROUP BY dim
        ORDER BY eur DESC NULLS LAST
    """
    rows = q(sql, tuple(params))

    # v8.0: CSV sanitization (anti formula injection + delimiter safe)
    out = _sanitize_filename(f"desglose_{by}") + ".csv"
    import csv as _csv, io as _io
    buf = _io.StringIO()
    buf.write("\ufeff")  # BOM UTF-8 para Excel
    # v8.0.1: usar QUOTE_MINIMAL con quoting automatico para proteger ; y "
    w = _csv.writer(buf, delimiter=";", quoting=_csv.QUOTE_MINIMAL)
    w.writerow([by, "n_facturas", "total_eur", "ticket_medio_eur"])
    for r in rows:
        dim = r["dim"]
        cnt = int(r["cnt"])
        eur = float(r["eur"] or 0)
        medio = eur / cnt if cnt else 0
        w.writerow([
            _sanitize_csv_value(dim),
            cnt,
            f"{eur:.2f}",
            f"{medio:.2f}",
        ])

    from fastapi.responses import Response as _Resp
    return _Resp(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{out}"'},
    )


# ── v8.3 PRO: Endpoints de Productos (consume MCP Last.app) ───────────
# Lee catalogo de productos via lastapp_server.list_products.
# Cache en memoria 5 min para no martillear el MCP.

import threading as _th_prod

_PRODUCTOS_CACHE = {}
_PRODUCTOS_CACHE_TTL_S = 300
_PRODUCTOS_LOCK = _th_prod.Lock()


def _productos_cache_get(key):
    e = _PRODUCTOS_CACHE.get(key)
    if not e:
        return None
    if (_dt.now().timestamp() - e["ts"]) > _PRODUCTOS_CACHE_TTL_S:
        _PRODUCTOS_CACHE.pop(key, None)
        return None
    return e["data"]


def _productos_cache_put(key, data):
    _PRODUCTOS_CACHE[key] = {"ts": _dt.now().timestamp(), "data": data}


def _llamar_mcp_tool(tool_name: str, args: dict, timeout_s: int = 30):
    """Llama a una tool del MCP Last.app via dashboard.chat.execute_tool.

    Devuelve dict parseado del MCP. Si falla, loguea y devuelve dict con 'error'.
    """
    try:
        from dashboard.chat import execute_tool as _chat_exec_tool
        import json as _jsonp
        result = _chat_exec_tool(tool_name, args)
        if not result:
            return {"error": "MCP devolvio vacio", "items": []}
        # El MCP devuelve un JSON stringificado dentro de content[0].text
        try:
            outer = _jsonp.loads(result)
            if isinstance(outer, dict) and "content" in outer:
                return _jsonp.loads(outer["content"][0]["text"])
            return outer
        except (_jsonp.JSONDecodeError, KeyError, IndexError, TypeError):
            return {"raw": result, "items": []}
    except Exception as e:
        logger.warning(f"MCP call {tool_name} fallo: {e!r}")
        return {"error": str(e), "items": []}


@app.get("/api/productos/catalogo")
def api_productos_catalogo(
    available_only: bool = Query(False, description="Solo productos disponibles"),
    limit: int = Query(100, ge=1, le=50, description="Maximo 50 (limite del MCP)"),
    search: str = Query("", description="Filtro por nombre (case-insensitive)"),
    user: str = Depends(get_current_user),
):
    """v8.3: Lista productos del catalogo desde Last.app via MCP."""
    cache_key = f"catalogo:{available_only}:{limit}:{search.lower()}"
    cached = _productos_cache_get(cache_key)
    if cached is not None:
        return cached

    raw = _llamar_mcp_tool("list_products", {"limit": min(limit, 50), "available_only": available_only})  # MCP limita a max=50

    products = raw.get("products") or raw.get("items") or raw.get("data") or []
    if not isinstance(products, list):
        products = []

    # Enriquecer con campos normalizados
    enriched = []
    for p in products:
        if not isinstance(p, dict):
            continue
        enriched.append({
            "id": p.get("id") or p.get("_id"),
            "name": p.get("name") or p.get("title") or "",
            "price": p.get("price"),
            "enabled": p.get("enabled", True),
            "available": p.get("available", p.get("enabled", True)),
            "category": p.get("category") or p.get("categoryName") or "",
            "description": p.get("description") or "",
        })

    # Filtrar por busqueda en cliente
    if search:
        s = search.lower()
        enriched = [p for p in enriched if s in (p["name"] or "").lower() or s in (p["category"] or "").lower()]

    out = {
        "items": enriched,
        "total": len(enriched),
        "totalCount": raw.get("totalCount", len(enriched)),
        "hasMore": raw.get("hasMore", False),
        "source": "lastapp_mcp" if enriched else "empty",
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }
    # Solo cachear si tenemos datos (evitar cachear respuestas vacias)
    if enriched:
        _productos_cache_put(cache_key, out)
    return out


@app.get("/api/productos/{product_id}")
def api_productos_detalle(product_id: str, user: str = Depends(get_current_user)):
    """v8.3: Detalle completo de un producto (precio, disponibilidad)."""
    import re as _re_p
    if not _re_p.match(r'^[0-9a-f-]{8,}$', product_id, _re_p.I):
        raise HTTPException(status_code=400, detail="product_id invalido (debe ser UUID)")

    cache_key = f"detail:{product_id}"
    cached = _productos_cache_get(cache_key)
    if cached is not None:
        return cached

    raw = _llamar_mcp_tool("get_product", {"product_id": product_id})
    # Si la respuesta viene envuelta en {"products": [...]}, sacar el primero
    if isinstance(raw, dict) and "products" in raw and isinstance(raw["products"], list) and raw["products"]:
        raw = raw["products"][0]
    # Normalizar respuesta
    out = {
        "id": raw.get("id") or product_id,
        "name": raw.get("name") or "",
        "price": raw.get("price"),
        "enabled": raw.get("enabled", True),
        "available": raw.get("available", raw.get("enabled", True)),
        "category": raw.get("category") or "",
        "description": raw.get("description") or "",
        "raw": {k: v for k, v in raw.items() if k not in ("id","name","price","enabled","available","category","description")},
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }
    _productos_cache_put(cache_key, out)
    return out


@app.get("/api/productos/stats/resumen")
def api_productos_stats(user: str = Depends(get_current_user)):
    """v8.3: Estadisticas del catalogo (total, disponibles, rango de precios)."""
    cache_key = "stats:resumen"
    cached = _productos_cache_get(cache_key)
    if cached is not None:
        return cached

    raw = _llamar_mcp_tool("list_products", {"limit": 50})  # MCP Last.app limita a max=50
    if "error" in raw and not raw.get("products"):
        # Si fallo el MCP, devolver error explicito (sin cachear)
        raise HTTPException(status_code=503, detail=f"MCP Last.app no disponible: {raw.get('error')}")
    products = raw.get("products") or raw.get("items") or raw.get("data") or []

    total = len(products)
    disponibles = sum(1 for p in products if p.get("enabled", True))
    no_disponibles = total - disponibles
    precios = [p.get("price") for p in products if isinstance(p.get("price"), (int, float)) and p.get("price") > 0]
    precio_min = min(precios) if precios else 0
    precio_max = max(precios) if precios else 0
    precio_medio = sum(precios) / len(precios) if precios else 0

    # Top 5 mas baratos y mas caros
    sorted_by_price = sorted([p for p in products if isinstance(p.get("price"), (int, float)) and p.get("price") > 0], key=lambda x: x["price"])
    mas_baratos = [{"id": p.get("id"), "name": p.get("name"), "price": p.get("price")} for p in sorted_by_price[:5]]
    mas_caros = [{"id": p.get("id"), "name": p.get("name"), "price": p.get("price")} for p in sorted_by_price[-5:][::-1]]

    out = {
        "total": total,
        "disponibles": disponibles,
        "no_disponibles": no_disponibles,
        "precio_min": precio_min,
        "precio_max": precio_max,
        "precio_medio": round(precio_medio, 2),
        "mas_baratos": mas_baratos,
        "mas_caros": mas_caros,
        "source": "lastapp_mcp",
        "generated_at": _dt.utcnow().isoformat() + "Z",
    }
    _productos_cache_put(cache_key, out)
    return out


@app.post("/api/productos/{product_id}/disponibilidad")
def api_productos_set_disponibilidad(
    product_id: str,
    payload: dict,
    user: str = Depends(get_current_user),
):
    """v8.3: Cambia la disponibilidad de un producto (via chat AI MCP tool).

    Body: {"available": true|false, "reason": "..."}
    Requiere confirmacion previa via chat AI (devuelve confirmation_token).
    Por seguridad, este endpoint requiere user=jefe y confirmation_token.
    """
    import re as _re_d
    if not _re_d.match(r'^[0-9a-f-]{8,}$', product_id, _re_d.I):
        raise HTTPException(status_code=400, detail="product_id invalido (debe ser UUID)")

    available = payload.get("available")
    if not isinstance(available, bool):
        raise HTTPException(status_code=422, detail="'available' debe ser true o false")

    # Por seguridad, solo el user jefe puede cambiar disponibilidad
    if user != "jefe":
        raise HTTPException(status_code=403, detail="Solo el usuario 'jefe' puede cambiar disponibilidad")

    # Llamar al MCP tool (que requiere confirmation)
    tool_name = "set_product_available" if available else "set_product_unavailable"
    raw = _llamar_mcp_tool(tool_name, {
        "product_id": product_id,
        "location_id": "",
    })
    return {
        "ok": "error" not in raw,
        "product_id": product_id,
        "available": available,
        "tool_used": tool_name,
        "mcp_response": raw,
        "by": user,
        "at": _dt.utcnow().isoformat() + "Z",
    }
