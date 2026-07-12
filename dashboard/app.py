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

# Chat conversacional (wrapper sobre agent.py, sin modificarlo).
from dashboard import chat as chat_engine

app = FastAPI(title="Liados Dashboard", version="6.0.0")
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
        f"AND COALESCE({p('category_raw')}, '') NOT IN ('nomina', 'administrativo', 'basura')"
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
    out = {"status": "ok", "version": "6.0.0", "checks": {}}
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

    # Validar metric
    if metric not in ("count", "sum", "avg", "min", "max"):
        raise HTTPException(status_code=422, detail=f"metric inválida: {metric}")

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
        params.append(int(min_eur * 100))
    if max_eur is not None:
        where_parts.append("total_amount <= %s")
        params.append(int(max_eur * 100))

    where_sql = " AND ".join(where_parts)

    # SELECT campos necesarios para todas las dimensiones posibles
    rows = q(f"""
        SELECT vendor_name, category_raw, source_account, source, status,
               invoice_date, total_amount
        FROM invoices
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
        "category_raw": "category_raw",
        "total_amount_cents": None,  # especial
        "invoice_date": "invoice_date",
        "description": "description",
    }
    for key, col in field_map.items():
        if key in payload:
            if key == "total_amount_cents":
                # convertir euros a céntimos
                update_parts.append(f"{col or 'total_amount'} = %s")
                update_params.append(int(payload[key] * 100))
            elif col:
                update_parts.append(f"{col} = %s")
                update_params.append(payload[key])
    # Alias: total_amount (euros) -> total_amount (cents)
    if "total_amount" in payload:
        update_parts.append("total_amount = %s")
        update_params.append(int(float(payload["total_amount"]) * 100))

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
    try:
        q_exec("""
            INSERT INTO invoice_corrections
                (invoice_id, user_id, reason, before_json, after_json, created_at)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW())
        """, (
            factura_id,
            user,
            payload.get("reason", ""),
            # No tenemos jsonb adapter nativo en psycopg2 -> usamos json.dumps
            __import__("json").dumps({k: str(v) for k, v in old.items()}),
            __import__("json").dumps({k: payload.get(k, old.get(k)) for k in ["vendor_name","category_raw","total_amount","invoice_date","description"]}),
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
            __import__("json").dumps({k: str(v) for k, v in old.items()}),
            __import__("json").dumps({k: payload.get(k, old.get(k)) for k in ["vendor_name","category_raw","total_amount","invoice_date","description"]}),
        ))
    except Exception:
        pass  # auditoría best-effort

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
    """Descarga el PDF de una factura (raw_file_url). Solo lectura del archivo."""
    from fastapi.responses import FileResponse
    rows = q("SELECT raw_file_url, invoice_number, vendor_name FROM invoices WHERE id = %s AND type = 'expense'", (factura_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    r = rows[0]
    pdf_path = r["raw_file_url"]
    if not pdf_path:
        raise HTTPException(status_code=404, detail="Esta factura no tiene PDF asociado")
    import os as _os
    if not _os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail=f"PDF no encontrado en disco: {pdf_path}")
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
    except Exception:
        pass

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
    except Exception:
        pass

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
    except Exception:
        pass

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
    except Exception:
        pass

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
    except Exception:
        pass

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
    except Exception:
        pass

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
    except Exception:
        pass

    # 8. duplicado_potencial: facturas con mismo vendor+total±3d
    try:
        dups = q("""
            SELECT count(*) as n FROM (
                SELECT a.id
                FROM invoices a JOIN invoices b ON a.id < b.id
                WHERE a.type = 'expense' AND b.type = 'expense'
                  AND a.status != 'rejected' AND b.status != 'rejected'
                  AND a.is_invoice = true AND b.is_invoice = true
                  AND a.vendor_name = b.vendor_name
                  AND a.total_amount = b.total_amount
                  AND abs(a.invoice_date - b.invoice_date) <= 3
                  AND a.status != 'duplicate' AND b.status != 'duplicate'
            ) s
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
    except Exception:
        pass

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
    except Exception:
        pass

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
        import traceback as _tb
        print('[api_alertas_ack_list] ERROR:', repr(e))
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
      <div class="nav-section-label">Restaurante</div>
      <a class="nav-item" data-view="productos"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/></svg><span class="nav-label">Productos</span></a>
      <a class="nav-item" data-view="reservas"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg><span class="nav-label">Reservas</span></a>
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
  <div id="last-invoice-card" data-loading="1">Cargando ultima factura extraida...</div>
  <script>
    // B3: Cargar la card server-rendered. Fallback silencioso si falla.
    fetch("/api/invoices/last-invoice-card", {credentials:"include"})
      .then(r => r.text())
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
          <label class="gd-field"><span>Status</span><select id="gd-status"><option value="">Todos</option><option value="verified">verified</option><option value="classified">classified</option><option value="pending">pending</option><option value="paid">paid</option></select></label>
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
        <div class="al-resumen" id="al-resumen"></div>
      </div>
      <div id="al-list" class="al-list">
        <div class="skeleton-card" aria-hidden="true"></div>
        <div class="skeleton-card" aria-hidden="true"></div>
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

    <!-- ═══ Vista: Reservas (próximamente) ═══ -->
    <section class="view" data-view="reservas">
      <div class="coming-soon">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
        <h2>Reservas</h2>
        <p>Próximamente: calendario de reservas, patrones de ocupación y cancelaciones. El <b>asistente AI</b> 💬 ya puede consultar tus reservas de mañana.</p>
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
        <tr><td><kbd>G</kbd> + <kbd>D/V/G/A/C</kbd></td><td>Ir a Dashboard/Ventas/Gastos/Alertas/Config</td></tr>
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
    """Ultima factura extraida. ?account=principal filtra por cuenta.
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
    """Fragmento HTML server-rendered con la ultima factura extraida.
    Usado por la card UI del dashboard (B3). Patron: server-side render
    para que funcione aunque app.js este deshabilitado."""
    payload = last_invoice(account=account, user=user)
    li = payload.get("last_invoice")
    if not li:
        html = (
            '<div class="card last-invoice empty">'
            '<h3>Ultima factura extraida</h3>'
            '<p>Aun no hay facturas extraidas.</p>'
            '</div>'
        )
        return HTMLResponse(html)
    currency = li.get("currency") or ""
    amount = li.get("total_amount")
    amount_str = f"{amount:.2f} {currency}" if amount is not None else "-"
    html = (
        '<div class="card last-invoice">'
        '<h3>Ultima factura extraida</h3>'
        f'<div class="li-row"><span class="li-label">Numero</span><b>{li["invoice_number"]}</b></div>'
        f'<div class="li-row"><span class="li-label">Vendor</span><b>{li["vendor"] or "-"}</b></div>'
        f'<div class="li-row"><span class="li-label">Importe</span><b>{amount_str}</b></div>'
        f'<div class="li-row"><span class="li-label">Fecha factura</span><b>{li["date"]}</b></div>'
        f'<div class="li-row"><span class="li-label">Cuenta</span><b>{li["source_account"] or "-"} ({li["source"]})</b></div>'
        f'<div class="li-meta">Extraida: {li["received_at"]} · Endpoint: /api/invoices/last-invoice</div>'
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
