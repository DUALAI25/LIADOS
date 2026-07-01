"""
Liados Dashboard v4 - FastAPI + HTML plano + Chart.js.
Datos REALES desde lastapp_bills + lastapp_payments (canales) + invoices (gastos).

Novedades v4:
- KPIs con comparativa MoM (mes vs mes anterior).
- Desglose por local (location_id).
- Tendencia diaria (30 dias).
- Graficos con Chart.js (tooltips, hover, leyenda).
- Chat AI end-to-end (agent.py + MCP Last.app) con confirmacion de acciones.
"""
import os
import secrets
from datetime import date, datetime
from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Optional, List
import psycopg2
from psycopg2.extras import RealDictCursor

# Chat conversacional (wrapper sobre agent.py, sin modificarlo).
from dashboard import chat as chat_engine

app = FastAPI(title="Liados Dashboard", version="4.0.0")
security = HTTPBasic()


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
def api_gastos_por_proveedor(limit: int = 10, user: str = Depends(get_current_user)):
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
def api_facturas_recientes(limit: int = 15, user: str = Depends(get_current_user)):
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
    return {"status": "ok", "version": "4.0.0"}


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
def api_ventas_por_dia(days: int = 30, user: str = Depends(get_current_user)):
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


# ── HTML Dashboard ─────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🍻</text></svg>">
<title>Liados · Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.header{background:linear-gradient(135deg,#1e293b,#334155);padding:20px 32px;border-bottom:1px solid #334155;display:flex;align-items:center;gap:16px}
.header h1{font-size:1.5rem;font-weight:700;color:#f1f5f9}
.header .badge{background:#22c55e22;color:#22c55e;padding:4px 12px;border-radius:12px;font-size:.8rem}
.header .clock{margin-left:auto;font-size:.8rem;color:#94a3b8}
.container{max-width:1400px;margin:0 auto;padding:24px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:28px}
.kpi{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155;position:relative;overflow:hidden}
.kpi .label{font-size:.8rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
.kpi .value{font-size:1.8rem;font-weight:700;margin:4px 0}
.kpi .sub{font-size:.75rem;color:#64748b}
.kpi .delta{font-size:.8rem;font-weight:600;margin-top:2px}
.kpi .delta.up{color:#22c55e}.kpi .delta.down{color:#ef4444}.kpi .delta.flat{color:#64748b}
.kpi canvas.spark{position:absolute;right:0;bottom:0;width:90px;height:38px;opacity:.85}
.green{color:#22c55e}.red{color:#ef4444}.blue{color:#3b82f6}.yellow{color:#eab308}.purple{color:#a855f7}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}
.grid-full{grid-column:1/-1}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}
.card h2{font-size:1.1rem;margin-bottom:16px;color:#f1f5f9;display:flex;align-items:center;gap:8px}
.bars{display:flex;flex-direction:column;gap:10px}
.bar-row{display:flex;align-items:center;gap:12px}
.bar-label{min-width:110px;font-size:.85rem;color:#cbd5e1;text-align:right}
.bar-track{flex:1;height:28px;background:#0f172a;border-radius:6px;overflow:hidden;position:relative}
.bar-fill{height:100%;border-radius:6px;display:flex;align-items:center;padding-left:10px;font-size:.75rem;font-weight:600;color:#fff;min-width:fit-content;transition:width .6s ease}
.bar-value{min-width:90px;font-size:.85rem;color:#94a3b8;text-align:right}
.chart-wrap{position:relative;height:260px}
.chart-wrap.tall{height:300px}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;padding:8px 12px;border-bottom:1px solid #334155}
td{padding:10px 12px;font-size:.85rem;border-bottom:1px solid #1e293b55}
tr:hover td{background:#1e293b88}
.tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:.7rem;font-weight:600;margin:1px}
.tag-card{background:#3b82f622;color:#60a5fa}.tag-cash{background:#22c55e22;color:#4ade80}
.tag-uber{background:#f9731622;color:#fb923c}.tag-glovo{background:#eab30822;color:#facc15}
.tag-shop{background:#a855f722;color:#c084fc}.tag-justeat{background:#ef444422;color:#f87171}
.footer{text-align:center;padding:20px;color:#475569;font-size:.75rem}
.skel{background:linear-gradient(90deg,#1e293b,#334155,#1e293b);background-size:200% 100%;animation:shimmer 1.4s infinite;border-radius:8px;height:20px}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}

/* Chat flotante */
.chat-fab{position:fixed;bottom:24px;right:24px;width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#8b5cf6);border:none;color:#fff;font-size:1.6rem;cursor:pointer;box-shadow:0 8px 24px rgba(59,130,246,.4);z-index:1000;transition:transform .2s}
.chat-fab:hover{transform:scale(1.08)}
.chat-panel{position:fixed;bottom:96px;right:24px;width:380px;max-width:calc(100vw - 32px);height:540px;max-height:calc(100vh - 120px);background:#1e293b;border:1px solid #334155;border-radius:16px;display:none;flex-direction:column;z-index:1000;box-shadow:0 16px 48px rgba(0,0,0,.5)}
.chat-panel.open{display:flex}
.chat-head{padding:14px 18px;border-bottom:1px solid #334155;display:flex;align-items:center;justify-content:space-between}
.chat-head .title{font-weight:700;color:#f1f5f9;display:flex;align-items:center;gap:8px}
.chat-head .close{background:none;border:none;color:#94a3b8;font-size:1.3rem;cursor:pointer}
.chat-body{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:85%;padding:10px 14px;border-radius:12px;font-size:.85rem;line-height:1.4;white-space:pre-wrap;word-wrap:break-word}
.msg.user{align-self:flex-end;background:#3b82f6;color:#fff;border-bottom-right-radius:4px}
.msg.bot{align-self:flex-start;background:#0f172a;border:1px solid #334155;color:#e2e8f0;border-bottom-left-radius:4px}
.msg.error{align-self:center;background:#ef444422;color:#fca5a5;font-size:.75rem}
.msg .tools{font-size:.7rem;color:#64748b;margin-top:6px;border-top:1px solid #33415555;padding-top:4px}
.confirm-box{align-self:flex-start;background:#7c2d1222;border:1px solid #f97316;border-radius:12px;padding:12px;font-size:.8rem;color:#fed7aa;display:flex;flex-direction:column;gap:8px}
.confirm-box .btns{display:flex;gap:8px}
.confirm-box button{padding:6px 14px;border:none;border-radius:6px;font-weight:600;cursor:pointer;font-size:.8rem}
.confirm-box .yes{background:#ef4444;color:#fff}.confirm-box .no{background:#475569;color:#e2e8f0}
.chat-input{padding:12px;border-top:1px solid #334155;display:flex;gap:8px}
.chat-input input{flex:1;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px 12px;color:#e2e8f0;font-size:.85rem;outline:none}
.chat-input input:focus{border-color:#3b82f6}
.chat-input button{background:#3b82f6;border:none;color:#fff;border-radius:8px;padding:0 16px;cursor:pointer;font-weight:600}
.chat-input button:disabled{opacity:.5;cursor:wait}
.typing{align-self:flex-start;color:#64748b;font-size:.75rem;font-style:italic}
.chat-suggest{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px 8px}
.chat-suggest button{background:#334155;border:none;color:#cbd5e1;border-radius:12px;padding:4px 10px;font-size:.72rem;cursor:pointer}
.chat-suggest button:hover{background:#475569}
</style>
</head>
<body>
<div class="header">
  <h1>🍻 Liados Dashboard</h1>
  <span class="badge">v4 · Chat AI</span>
  <span class="clock" id="clock"></span>
</div>
<div class="container">
  <div class="kpis" id="kpis"></div>
  <div class="grid">
    <div class="card grid-full">
      <h2>📊 Ventas por canal (últimos 6 meses)</h2>
      <div class="chart-wrap tall"><canvas id="chart-canales"></canvas></div>
    </div>
    <div class="card grid-full">
      <h2>📈 Tendencia diaria (30 días)</h2>
      <div class="chart-wrap"><canvas id="chart-diario"></canvas></div>
    </div>
    <div class="card">
      <h2>💳 Canales este mes</h2>
      <div id="canal-mes" class="bars"></div>
    </div>
    <div class="card">
      <h2>📍 Ventas por local este mes</h2>
      <div id="local-mes" class="bars"></div>
    </div>
    <div class="card">
      <h2>📈 Margen por mes</h2>
      <div id="margen" class="bars"></div>
    </div>
    <div class="card">
      <h2>💰 Ingresos por mes</h2>
      <div id="ingresos"></div>
    </div>
    <div class="card">
      <h2>🧾 Gastos por proveedor</h2>
      <div id="proveedores"></div>
    </div>
    <div class="card">
      <h2>📦 Gastos por categoría</h2>
      <div id="categorias"></div>
    </div>
    <div class="card grid-full">
      <h2>📋 Últimas facturas</h2>
      <div id="facturas"></div>
    </div>
  </div>
</div>
<div class="footer">Liados · Vamos al lío S.L. · B22774590</div>

<button class="chat-fab" id="chat-fab" title="Asistente AI">💬</button>
<div class="chat-panel" id="chat-panel">
  <div class="chat-head">
    <div class="title">🤖 Asistente Liados</div>
    <button class="close" id="chat-close">✕</button>
  </div>
  <div class="chat-body" id="chat-body"></div>
  <div class="chat-suggest" id="chat-suggest"></div>
  <div class="chat-input">
    <input id="chat-text" type="text" placeholder="Pregúntame sobre ventas, facturas, productos..." autocomplete="off">
    <button id="chat-send">Enviar</button>
  </div>
</div>

<script>
const COLORS={card:'#3b82f6',cash:'#22c55e',uber:'#f97316',glovo:'#eab308',shop:'#a855f7',justeat:'#ef4444'};
const LABELS={card:'💳 Tarjeta',cash:'💵 Efectivo',uber:'🚗 Uber Eats',glovo:'🟡 Glovo',shop:'🛒 Shop',justeat:'🛵 Just Eat'};
const fmt=n=>n>=1000?(n/1000).toFixed(1).replace('.0','')+'k':n.toFixed(0);
const eur=n=>n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€';
const eur0=n=>n.toLocaleString('es-ES',{maximumFractionDigits:0})+'€';
const deltaHtml=(d)=>{if(d==null)return '<span class="delta flat">— vs mes ant.</span>';const u=d>=0;const arrow=u?'▲':'▼';return `<span class="delta ${u?'up':'down'}">${arrow} ${Math.abs(d).toFixed(1)}% vs mes ant.</span>`;};

// Reloj
function tick(){const d=new Date();document.getElementById('clock').textContent=d.toLocaleString('es-ES',{weekday:'short',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});}
tick();setInterval(tick,30000);

Chart.defaults.color='#94a3b8';Chart.defaults.borderColor='#334155';Chart.defaults.font.family='-apple-system,sans-serif';

const charts={};

async function load(){
  const f=async(url)=>{const r=await fetch(url);if(!r.ok)throw new Error(url+' '+r.status);return r.json();};
  const [kpis,comp,canalMes,canalMeses,margen,ingresos,proveedores,facturas,categorias,locales,dia,spark6m]=await Promise.all([
    f('/api/kpis'),f('/api/kpis-comparativa'),f('/api/ventas-por-canal'),f('/api/canal-por-mes'),
    f('/api/margen-por-mes'),f('/api/ingresos-por-mes'),f('/api/gastos-por-proveedor'),
    f('/api/facturas-recientes'),f('/api/gastos-por-categoria'),f('/api/ventas-por-local'),
    f('/api/ventas-por-dia?days=30'),f('/api/ingresos-6m')
  ]);

  // KPIs con sparklines + MoM
  const sparkData=spark6m.map(r=>r.total_eur);
  const sparkLabels=spark6m.map(r=>r.mes.slice(5));
  function spark(vals,color){return {type:'line',data:{labels:vals.map((_,i)=>i),datasets:[{data:vals,borderColor:color,backgroundColor:color+'22',fill:true,tension:.4,pointRadius:0,borderWidth:2}]},options:{responsive:false,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{enabled:false}},scales:{x:{display:false},y:{display:false}}}};}
  document.getElementById('kpis').innerHTML=`
    <div class="kpi"><div class="label">Ventas mes</div><div class="value green">${eur(kpis.ventas_mes)}</div><div class="sub">${kpis.facturas_ventas} facturas</div>${deltaHtml(comp.ventas.delta_pct)}<canvas class="spark" id="sp1"></canvas></div>
    <div class="kpi"><div class="label">Gastos mes</div><div class="value red">${eur(kpis.gastos_mes)}</div><div class="sub">${kpis.facturas_gastos} facturas</div>${deltaHtml(comp.gastos.delta_pct)}<canvas class="spark" id="sp2"></canvas></div>
    <div class="kpi"><div class="label">Margen mes</div><div class="value ${kpis.margen_mes>=0?'green':'red'}">${eur(kpis.margen_mes)}</div><div class="sub">${kpis.ventas_mes?(kpis.margen_mes/kpis.ventas_mes*100).toFixed(1):'0'}% sobre ventas</div>${deltaHtml(comp.margen.delta_pct)}</div>
    <div class="kpi"><div class="label">IVA mes</div><div class="value blue">${eur(kpis.iva_mes)}</div><div class="sub">Repercutido</div></div>
    <div class="kpi"><div class="label">Delivery</div><div class="value yellow">${eur(kpis.delivery_mes)}</div><div class="sub">Comisiones delivery</div></div>
  `;
  if(document.getElementById('sp1'))new Chart(document.getElementById('sp1'),spark(sparkData,'#22c55e'));
  if(document.getElementById('sp2'))new Chart(document.getElementById('sp2'),spark(sparkData,'#ef4444'));

  // Stacked chart Chart.js (canales x mes)
  const meses=[...new Set(canalMeses.map(r=>r.mes))].sort();
  const canales=[...new Set(canalMeses.map(r=>r.canal))];
  const dataByMes={};canalMeses.forEach(r=>{if(!dataByMes[r.mes])dataByMes[r.mes]={};dataByMes[r.mes][r.canal]=r.total_eur;});
  const ds=canales.map(c=>({label:LABELS[c]||c,data:meses.map(m=>dataByMes[m]?.[c]||0),backgroundColor:COLORS[c]||'#64748b',stack:'s',borderRadius:4}));
  charts.canales&&charts.canales.destroy();
  charts.canales=new Chart(document.getElementById('chart-canales'),{type:'bar',data:{labels:meses.map(m=>m.slice(5)),datasets:ds},options:{responsive:true,maintainAspectRatio:false,plugins:{tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${eur(c.raw)}`}}},scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,ticks:{callback:v=>fmt(v)}}}}});

  // Tendencia diaria (line)
  charts.diario&&charts.diario.destroy();
  charts.diario=new Chart(document.getElementById('chart-diario'),{type:'line',data:{labels:dia.map(r=>r.dia.slice(5)),datasets:[{label:'Ingresos/día',data:dia.map(r=>r.total_eur),borderColor:'#3b82f6',backgroundColor:'#3b82f622',fill:true,tension:.3,pointRadius:2,borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>eur(c.raw)}}},scales:{x:{grid:{display:false},ticks:{maxTicksLimit:10}},y:{ticks:{callback:v=>fmt(v)}}}}});

  // Canal este mes (bars)
  const maxCanal=Math.max(...canalMes.map(c=>c.total_eur),1);
  document.getElementById('canal-mes').innerHTML=canalMes.map(c=>`
    <div class="bar-row">
      <div class="bar-label">${LABELS[c.canal]||c.canal}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(c.total_eur/maxCanal*100).toFixed(1)}%;background:${COLORS[c.canal]||'#64748b'}">${eur(c.total_eur)}</div></div>
      <div class="bar-value">${c.pagos} pagos</div>
    </div>`).join('');

  // Por local
  const maxLoc=Math.max(...locales.map(l=>l.total_eur),1);
  document.getElementById('local-mes').innerHTML=locales.map(l=>`
    <div class="bar-row">
      <div class="bar-label">${(l.nombre||'Local').slice(0,18)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(l.total_eur/maxLoc*100).toFixed(1)}%;background:#06b6d4">${eur(l.total_eur)}</div></div>
      <div class="bar-value">${l.facturas} fact.</div>
    </div>`).join('');

  // Margen por mes
  const maxMargen=Math.max(...margen.map(m=>Math.max(m.ingresos,m.gastos)),1);
  document.getElementById('margen').innerHTML=margen.map(m=>`
    <div style="margin-bottom:12px">
      <div style="font-size:.8rem;color:#94a3b8;margin-bottom:4px">${m.mes} — <span class="${m.margen>=0?'green':'red'}">Margen: ${eur(m.margen)}</span></div>
      <div class="bar-row">
        <div class="bar-label" style="min-width:60px;font-size:.75rem">Ingresos</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(m.ingresos/maxMargen*100).toFixed(1)}%;background:#22c55e">${eur(m.ingresos)}</div></div>
      </div>
      <div class="bar-row">
        <div class="bar-label" style="min-width:60px;font-size:.75rem">Gastos</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(m.gastos/maxMargen*100).toFixed(1)}%;background:#ef4444">${eur(m.gastos)}</div></div>
      </div>
    </div>`).join('');

  // Ingresos por mes (table)
  document.getElementById('ingresos').innerHTML=`<table>
    <tr><th>Mes</th><th>Fact.</th><th>Total</th><th>Base</th><th>IVA</th><th>Deliv.</th><th>Dto.</th></tr>
    ${ingresos.map(r=>`<tr><td>${r.mes}</td><td>${r.facturas}</td><td><b>${eur(r.total_eur)}</b></td><td>${eur(r.base_eur)}</td><td>${eur(r.iva_eur)}</td><td>${eur(r.delivery_eur)}</td><td>${eur(r.descuentos_eur)}</td></tr>`).join('')}
  </table>`;

  // Proveedores
  const maxProv=Math.max(...proveedores.map(p=>p.total_eur),1);
  document.getElementById('proveedores').innerHTML=proveedores.map(p=>`
    <div class="bar-row">
      <div class="bar-label" style="min-width:140px">${(p.proveedor||'').slice(0,20)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(p.total_eur/maxProv*100).toFixed(1)}%;background:#8b5cf6">${eur(p.total_eur)}</div></div>
      <div class="bar-value">${p.facturas} fc.</div>
    </div>`).join('');

  // Categorias
  const maxCat=Math.max(...categorias.map(c=>c.total_eur),1);
  document.getElementById('categorias').innerHTML=categorias.map(c=>`
    <div class="bar-row">
      <div class="bar-label" style="min-width:110px">${(c.categoria||'').slice(0,15)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(c.total_eur/maxCat*100).toFixed(1)}%;background:${c.color||'#6b7280'}">${eur(c.total_eur)}</div></div>
      <div class="bar-value">${c.facturas} fc.</div>
    </div>`).join('');

  // Facturas recientes
  document.getElementById('facturas').innerHTML=`<table>
    <tr><th>Nº</th><th>Fecha</th><th>Cliente</th><th>Canales</th><th>Total</th></tr>
    ${facturas.map(f=>{const tags=(f.canales||'').split(',').map(c=>c.trim()).filter(Boolean).map(c=>`<span class="tag tag-${c}">${c}</span>`).join(' ');return `<tr><td>${f.number}</td><td>${f.fecha}</td><td>${f.cliente}</td><td>${tags}</td><td><b>${eur(f.total_eur)}</b></td></tr>`;}).join('')}
  </table>`;
}
load().catch(e=>document.querySelector('.container').innerHTML='<p style="color:#ef4444">Error cargando datos: '+e.message+'</p>');

// ── Chat ──────────────────────────────────────────────────────
const SUGGEST=['¿Cuánto he vendido este mes?','Top 5 productos de la semana','Facturas pendientes de pago','¿Qué reservas tengo mañana?','Resumen de gastos por categoría'];
let chatHistory=JSON.parse(localStorage.getItem('liados_chat_hist')||'[]');
let pendingToken=null;

const fab=document.getElementById('chat-fab'),panel=document.getElementById('chat-panel');
const body=document.getElementById('chat-body'),txt=document.getElementById('chat-text');
const send=document.getElementById('chat-send'),suggest=document.getElementById('chat-suggest');

function renderSuggest(){suggest.innerHTML=SUGGEST.map(s=>`<button>${s}</button>`).join('');suggest.querySelectorAll('button').forEach(b=>b.onclick=()=>{txt.value=b.textContent;sendMsg();});}
function saveHist(){try{localStorage.setItem('liados_chat_hist',JSON.stringify(chatHistory.slice(-20)));}catch(e){}}
function addMsg(text,cls,extra){const d=document.createElement('div');d.className='msg '+cls;d.innerHTML=text+(extra||'');body.appendChild(d);body.scrollTop=body.scrollHeight;return d;}
function renderHistory(){body.innerHTML='';chatHistory.forEach(m=>addMsg(escapeHtml(m.content),m.role==='user'?'user':'bot'));}
function escapeHtml(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

fab.onclick=()=>{panel.classList.toggle('open');if(panel.classList.contains('open')&&body.children.length===0){renderHistory();renderSuggest();}txt.focus();};
document.getElementById('chat-close').onclick=()=>panel.classList.remove('open');
txt.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}};
send.onclick=sendMsg;

async function sendMsg(){
  const msg=txt.value.trim();if(!msg)return;
  txt.value='';send.disabled=true;
  addMsg(escapeHtml(msg),'user');
  const typing=addMsg('escribiendo…','bot');
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg,history:chatHistory})});
    const data=await r.json();
    typing.remove();
    const tools=data.tools_used&&data.tools_used.length?`<div class="tools">🔧 ${data.tools_used.join(', ')}</div>`:'';
    addMsg(escapeHtml(data.reply||'(sin respuesta)','bot'),'',tools);
    chatHistory=[...chatHistory,{role:'user',content:msg},{role:'assistant',content:data.reply||''}].slice(-20);
    saveHist();
    if(data.pending_confirmation&&data.pending_confirmation.token){
      pendingToken=data.pending_confirmation.token;
      showConfirm(data.pending_confirmation);
    }
  }catch(e){typing.remove();addMsg('Error de conexión: '+e.message,'error');}
  send.disabled=false;txt.focus();
}

function showConfirm(p){
  const box=document.createElement('div');box.className='confirm-box';
  box.innerHTML=`<div><b>⚠️ ${escapeHtml(p.action)}</b><br>${escapeHtml(p.message||'Esta acción requiere confirmación.')}</div>
    <div class="btns"><button class="yes">Confirmar</button><button class="no">Cancelar</button></div>`;
  body.appendChild(box);body.scrollTop=body.scrollHeight;
  box.querySelector('.yes').onclick=async()=>{box.innerHTML='Ejecutando…';const r=await fetch('/api/chat/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation_token:pendingToken})});const d=await r.json();box.remove();addMsg(escapeHtml(JSON.stringify(d,null,1)),'bot');pendingToken=null;};
  box.querySelector('.no').onclick=async()=>{await fetch('/api/chat/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation_token:pendingToken})});box.remove();addMsg('Acción cancelada.','bot');pendingToken=null;};
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index(user: str = Depends(get_current_user)):
    return INDEX_HTML
