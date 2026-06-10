"""
Mini-dashboard Liados — FastAPI + HTML plano.
Sirve un solo HTML con 4 paneles: KPIs, top vendors, facturas recientes, resumen mensual.
Datos en vivo desde Postgres.
"""
import os
from datetime import date, datetime
from decimal import Decimal
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Liados Dashboard", version="1.0.0")


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "desliado"),
        user=os.getenv("DB_USER", "desliado"),
        password=os.getenv("DB_PASSWORD", "desliado_pass_2026"),
        connect_timeout=5,
    )


def q(sql, params=()):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def to_dict(row):
    out = {}
    for k, v in row.items():
        if isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# --- API JSON ---
@app.get("/api/kpis")
def api_kpis():
    rows = q("""
        SELECT
            COALESCE(SUM(CASE WHEN type='income'  AND invoice_date >= date_trunc('month', CURRENT_DATE) THEN total_amount END), 0) AS ventas_mes,
            COALESCE(SUM(CASE WHEN type='expense' AND invoice_date >= date_trunc('month', CURRENT_DATE) THEN total_amount END), 0) AS gastos_mes,
            COUNT(*) FILTER (WHERE status='pending') AS facturas_pendientes,
            COUNT(*) FILTER (WHERE type='income') AS total_ventas,
            COUNT(*) FILTER (WHERE type='expense') AS total_gastos
        FROM invoices WHERE status NOT IN ('duplicate','rejected');
    """)
    r = rows[0]
    ventas = float(r["ventas_mes"])
    gastos = float(r["gastos_mes"])
    return {
        "ventas_mes": round(ventas, 2),
        "gastos_mes": round(gastos, 2),
        "margen_mes": round(ventas - gastos, 2),
        "facturas_pendientes": r["facturas_pendientes"],
        "total_ventas": r["total_ventas"],
        "total_gastos": r["total_gastos"],
    }


@app.get("/api/top-vendors")
def api_top_vendors(limit: int = 8):
    rows = q("""
        SELECT v.name AS vendor,
               COUNT(i.id) AS n_facturas,
               ROUND(SUM(i.total_amount)::numeric, 2) AS total_eur
        FROM invoices i JOIN vendors v ON v.id = i.vendor_id
        WHERE i.type='expense' AND i.status NOT IN ('duplicate','rejected')
        GROUP BY v.name ORDER BY total_eur DESC LIMIT %s;
    """, (limit,))
    return [to_dict(r) for r in rows]


@app.get("/api/recent-invoices")
def api_recent_invoices(limit: int = 12):
    rows = q("""
        SELECT invoice_number, invoice_date, type, status,
               COALESCE(vendor_name, '—') AS vendor,
               total_amount::float AS total, currency
        FROM invoices WHERE status NOT IN ('duplicate','rejected')
        ORDER BY created_at DESC LIMIT %s;
    """, (limit,))
    return [to_dict(r) for r in rows]


@app.get("/api/monthly")
def api_monthly():
    rows = q("""
        SELECT to_char(month, 'YYYY-MM') AS mes,
               ROUND(income::numeric, 2)  AS ingresos,
               ROUND(expense::numeric, 2) AS gastos,
               ROUND(net::numeric, 2)     AS neto
        FROM monthly_net ORDER BY month DESC LIMIT 6;
    """)
    return [to_dict(r) for r in rows]


# --- HTML ---
HTML = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<title>Liados · Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 24px; }
  h1 { font-size: 24px; margin-bottom: 4px; color: #f8fafc; }
  .sub { color: #94a3b8; font-size: 13px; margin-bottom: 24px; }
  .grid { display: grid; gap: 16px; }
  .kpis { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); margin-bottom: 24px; }
  .card { background: #1e293b; border-radius: 12px; padding: 20px;
          border: 1px solid #334155; }
  .kpi-label { color: #94a3b8; font-size: 12px; text-transform: uppercase;
               letter-spacing: 0.5px; margin-bottom: 8px; }
  .kpi-value { font-size: 28px; font-weight: 700; color: #f8fafc; }
  .kpi-sub { color: #64748b; font-size: 12px; margin-top: 4px; }
  .pos { color: #22c55e; }
  .neg { color: #ef4444; }
  .row2 { grid-template-columns: 1fr 1fr; }
  h2 { font-size: 15px; margin-bottom: 12px; color: #cbd5e1;
       text-transform: uppercase; letter-spacing: 0.5px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 8px 12px; color: #94a3b8;
       font-weight: 500; border-bottom: 1px solid #334155; }
  td { padding: 8px 12px; border-bottom: 1px solid #1e293b; }
  tr:hover td { background: #334155; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 11px; font-weight: 600; }
  .b-income { background: #064e3b; color: #6ee7b7; }
  .b-expense { background: #7c2d12; color: #fed7aa; }
  .b-paid { background: #064e3b; color: #6ee7b7; }
  .b-pending { background: #78350f; color: #fcd34d; }
  .b-verified { background: #1e3a8a; color: #93c5fd; }
  .b-classified { background: #581c87; color: #d8b4fe; }
  .right { text-align: right; font-variant-numeric: tabular-nums; }
  .footer { text-align: center; color: #475569; font-size: 12px;
            margin-top: 32px; padding-top: 16px; border-top: 1px solid #1e293b; }
  @media (max-width: 768px) { .row2 { grid-template-columns: 1fr; } }
</style>
</head><body>
<h1>🍻 Liados — Dashboard</h1>
<div class="sub">Demo · Datos sintéticos · <span id="ts"></span></div>

<div class="grid kpis" id="kpis"><div class="card"><div class="kpi-label">Cargando…</div></div></div>

<div class="grid row2" style="margin-bottom: 24px;">
  <div class="card">
    <h2>Top proveedores (gasto 90 días)</h2>
    <table><thead><tr><th>Proveedor</th><th class="right">Facturas</th><th class="right">Total €</th></tr></thead><tbody id="vendors"></tbody></table>
  </div>
  <div class="card">
    <h2>Resumen últimos 6 meses</h2>
    <table><thead><tr><th>Mes</th><th class="right">Ingresos</th><th class="right">Gastos</th><th class="right">Neto</th></tr></thead><tbody id="monthly"></tbody></table>
  </div>
</div>

<div class="card">
  <h2>Facturas recientes</h2>
  <table><thead><tr><th>Fecha</th><th>Nº</th><th>Tipo</th><th>Vendor</th><th>Status</th><th class="right">Total €</th></tr></thead><tbody id="recent"></tbody></table>
</div>

<div class="footer">Liados · Backend Python + Postgres · <span id="count"></span></div>

<script>
const fmt = n => new Intl.NumberFormat('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
const fmtDate = d => d ? new Date(d).toLocaleDateString('es-ES') : '—';
async function load() {
  document.getElementById('ts').textContent = new Date().toLocaleString('es-ES');

  const kpis = await (await fetch('/api/kpis')).json();
  document.getElementById('kpis').innerHTML =
    '<div class="card"><div class="kpi-label">Ventas mes</div><div class="kpi-value pos">' + fmt(kpis.ventas_mes) + ' €</div><div class="kpi-sub">' + kpis.total_ventas + ' facturas ingreso</div></div>' +
    '<div class="card"><div class="kpi-label">Gastos mes</div><div class="kpi-value neg">' + fmt(kpis.gastos_mes) + ' €</div><div class="kpi-sub">' + kpis.total_gastos + ' facturas gasto</div></div>' +
    '<div class="card"><div class="kpi-label">Margen mes</div><div class="kpi-value ' + (kpis.margen_mes>=0?'pos':'neg') + '">' + fmt(kpis.margen_mes) + ' €</div><div class="kpi-sub">ingresos − gastos</div></div>' +
    '<div class="card"><div class="kpi-label">Pendientes revisión</div><div class="kpi-value">' + kpis.facturas_pendientes + '</div><div class="kpi-sub">facturas status=pending</div></div>';
  document.getElementById('count').textContent = (kpis.total_ventas+kpis.total_gastos) + ' facturas en total';

  const vendors = await (await fetch('/api/top-vendors')).json();
  document.getElementById('vendors').innerHTML = vendors.map(v =>
    '<tr><td>' + v.vendor + '</td><td class="right">' + v.n_facturas + '</td><td class="right">' + fmt(v.total_eur) + '</td></tr>').join('') || '<tr><td colspan="3">Sin datos</td></tr>';

  const monthly = await (await fetch('/api/monthly')).json();
  document.getElementById('monthly').innerHTML = monthly.map(m =>
    '<tr><td>' + m.mes + '</td><td class="right pos">' + fmt(m.ingresos) + '</td><td class="right neg">' + fmt(m.gastos) + '</td><td class="right ' + (m.neto>=0?'pos':'neg') + '">' + fmt(m.neto) + '</td></tr>').join('') || '<tr><td colspan="4">Sin datos</td></tr>';

  const recent = await (await fetch('/api/recent-invoices')).json();
  document.getElementById('recent').innerHTML = recent.map(r =>
    '<tr><td>' + fmtDate(r.invoice_date) + '</td><td>' + (r.invoice_number||'—') + '</td>' +
    '<td><span class="badge b-' + r.type + '">' + r.type + '</span></td>' +
    '<td>' + r.vendor + '</td>' +
    '<td><span class="badge b-' + r.status + '">' + r.status + '</span></td>' +
    '<td class="right">' + fmt(r.total) + '</td></tr>').join('') || '<tr><td colspan="6">Sin datos</td></tr>';
}
load().catch(e => { document.body.innerHTML = '<h1>Error: '+e.message+'</h1>'; });
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


@app.get("/healthz")
def health():
    try:
        q("SELECT 1")
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return JSONResponse({"status": "error", "db": str(e)}, status_code=500)
