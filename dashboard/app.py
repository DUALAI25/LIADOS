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
import secrets
from datetime import date, datetime
from decimal import Decimal
from fastapi import Query, FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Optional, List
import psycopg2
from psycopg2.extras import RealDictCursor

# Chat conversacional (wrapper sobre agent.py, sin modificarlo).
from dashboard import chat as chat_engine

app = FastAPI(title="Liados Dashboard", version="5.1.0")
security = HTTPBasic()

# Servir assets estaticos (fuentes, css, js) sin auth (son publicos, sin secretos).
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


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


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "desliado"),
        user=os.getenv("DB_USER", "desliado"),
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
    )


def q(sql, params=()):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


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
    return {"status": "ok", "version": "5.1.0"}


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
def api_chat(req: ChatRequest, user: str = Depends(get_current_user)):
    """Chat conversacional contra el agente (OpenCode Go + MCP)."""
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
def api_chat_stream(req: ChatRequest, user: str = Depends(get_current_user)):
    """Chat conversacional STREAMING via Server-Sent Events.

    Emite eventos SSE:
      event: token  data: {"text": "..."}        (tokens de la respuesta final)
      event: tool   data: {"name": "..."}        (inicio de ejecucion de tool)
      event: done   data: {"reply","pending_confirmation","tools_used","history"}
      event: error  data: {"message": "..."}
    """
    import json as _json

    def gen():
        try:
            for ev in chat_engine.chat_stream(req.message, req.history):
                yield f"event: {ev['type']}\ndata: {_json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {_json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

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


# ── HTML Dashboard ─────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="es" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🍻</text></svg>">
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
      <a class="nav-item active"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg><span class="nav-label">Dashboard</span></a>
      <a class="nav-item"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg><span class="nav-label">Ventas</span></a>
      <a class="nav-item"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg><span class="nav-label">Gastos</span></a>
      <div class="nav-section-label">Restaurante</div>
      <a class="nav-item"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/></svg><span class="nav-label">Productos</span></a>
      <a class="nav-item"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg><span class="nav-label">Reservas</span></a>
      <div class="nav-section-label">Sistema</div>
      <a class="nav-item"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg><span class="nav-label">Configuración</span></a>
    </nav>
    <div class="sidebar-foot">
      <span class="live-dot"></span>
      <div class="foot-text">Datos en vivo<br><b id="syncTime">cargando…</b></div>
    </div>
  </aside>

  <!-- ── Header ── -->
  <header class="header">
    <button class="icon-btn" id="sidebarToggle" title="Menú"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>
    <div class="crumbs"><b>Dashboard</b></div>
    <div class="header-spacer"></div>
    <span id="clock" style="color:var(--fg-2);font-size:var(--fz-sm);padding-right:var(--s-3)"></span>
    <label class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg><input type="text" placeholder="Buscar…"><kbd>/</kbd></label>
    <button class="icon-btn" id="themeToggle" title="Cambiar tema"></button>
  </header>

  <!-- ── Main ── -->
  <main class="main">
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
        <tr><td><kbd>/</kbd></td><td>Buscar</td></tr>
        <tr><td><kbd>C</kbd></td><td>Abrir/cerrar asistente AI</td></tr>
        <tr><td><kbd>R</kbd></td><td>Refrescar datos</td></tr>
        <tr><td><kbd>T</kbd></td><td>Cambiar tema claro/oscuro</td></tr>
        <tr><td><kbd>?</kbd></td><td>Esta ayuda</td></tr>
        <tr><td><kbd>Esc</kbd></td><td>Cerrar ventana activa</td></tr>
      </table>
    </div>
  </div>
</div>

<script src="/static/app.js"></script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index(user: str = Depends(get_current_user)):
    return INDEX_HTML
