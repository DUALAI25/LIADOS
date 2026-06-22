"""
Liados Dashboard v3 — FastAPI + HTML plano.
Datos REALES desde lastapp_bills + lastapp_payments (canales) + invoices (gastos).
"""
import os
import secrets
from datetime import date, datetime
from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import psycopg2
from psycopg2.extras import RealDictCursor

# Agente de chat con OpenCode Go + MCP Last.app
from dashboard.agent import ask as agent_ask

app = FastAPI(title="Liados Dashboard", version="3.0.0")
security = HTTPBasic()


def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    expected_user = os.environ["DASHBOARD_USER"]  # fail-fast si no está en .env
    expected_pass = os.environ["DASHBOARD_PASSWORD"]  # fail-fast si no está en .env
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


# ── API Endpoints ──────────────────────────────────────────────

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

    gastos = q("""
        SELECT count(*) as facturas,
               coalesce(sum(total_amount), 0) as total
        FROM invoices
        WHERE type = 'expense' AND status != 'rejected'
          AND COALESCE(category_raw, '') NOT IN ('nomina', 'administrativo', 'basura')
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
    """Ventas por canal y mes (últimos 6 meses). Para gráfico apilado."""
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
    """Ingresos mensuales desde lastapp_bills (últimos 6 meses)."""
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
    return [to_dict(r) for r in q("""
        SELECT coalesce(vendor_name, 'Sin nombre') as proveedor,
               count(*) as facturas,
               coalesce(sum(total_amount), 0) as total_eur,
               coalesce(category_raw, 'sin categoría') as categoria
        FROM invoices
        WHERE type = 'expense' AND status != 'rejected'
          AND COALESCE(category_raw, '') NOT IN ('nomina', 'administrativo', 'basura')
          AND vendor_name IS NOT NULL
        GROUP BY vendor_name, category_raw
        ORDER BY total_eur DESC
        LIMIT %s
    """, (limit,))]


@app.get("/api/gastos-por-categoria")
def api_gastos_por_categoria(user: str = Depends(get_current_user)):
    """Gastos agrupados por categoría."""
    return [to_dict(r) for r in q("""
        SELECT coalesce(c.name, i.category_raw, 'Sin categoría') as categoria,
               coalesce(c.color, '#6B7280') as color,
               count(*) as facturas,
               coalesce(sum(i.total_amount), 0) as total_eur
        FROM invoices i
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE i.type = 'expense'
          AND COALESCE(i.category_raw, '') NOT IN ('nomina', 'administrativo', 'basura')
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

    gastos_raw = q("""
        SELECT to_char(invoice_date, 'YYYY-MM') as mes,
               coalesce(sum(total_amount), 0) as total_eur
        FROM invoices
        WHERE type = 'expense' AND status != 'rejected'
          AND COALESCE(category_raw, '') NOT IN ('nomina', 'administrativo', 'basura')
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
    """Últimas facturas de Last.app con su canal de pago."""
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
    return {"status": "ok", "version": "3.0.0"}


# ── HTML Dashboard ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(user: str = Depends(get_current_user)):
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🍻</text></svg>">
<title>Liados · Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.header{background:linear-gradient(135deg,#1e293b,#334155);padding:20px 32px;border-bottom:1px solid #334155;display:flex;align-items:center;gap:16px}
.header h1{font-size:1.5rem;font-weight:700;color:#f1f5f9}
.header .badge{background:#22c55e22;color:#22c55e;padding:4px 12px;border-radius:12px;font-size:.8rem}
.container{max-width:1400px;margin:0 auto;padding:24px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:28px}
.kpi{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}
.kpi .label{font-size:.8rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
.kpi .value{font-size:1.8rem;font-weight:700;margin:4px 0}
.kpi .sub{font-size:.75rem;color:#64748b}
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
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;padding:8px 12px;border-bottom:1px solid #334155}
td{padding:10px 12px;font-size:.85rem;border-bottom:1px solid #1e293b55}
tr:hover td{background:#1e293b88}
.tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:.7rem;font-weight:600}
.tag-card{background:#3b82f622;color:#60a5fa}
.tag-cash{background:#22c55e22;color:#4ade80}
.tag-uber{background:#f9731622;color:#fb923c}
.tag-glovo{background:#eab30822;color:#facc15}
.tag-shop{background:#a855f722;color:#c084fc}
.tag-justeat{background:#ef444422;color:#f87171}
.stacked-chart{display:flex;height:200px;align-items:flex-end;gap:4px;padding-top:10px}
.stacked-bar{display:flex;flex-direction:column;flex:1;justify-content:flex-end;height:100%}
.stacked-seg{width:100%;min-height:2px;position:relative}
.stacked-seg:hover{opacity:.85}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px}
.legend-item{display:flex;align-items:center;gap:6px;font-size:.75rem;color:#94a3b8}
.legend-dot{width:10px;height:10px;border-radius:3px}
.footer{text-align:center;padding:20px;color:#475569;font-size:.75rem}
</style>
</head>
<body>
<div class="header">
  <h1>🍻 Liados Dashboard</h1>
  <span class="badge">v3 · Datos en vivo</span>
</div>
<div class="container">
  <div class="kpis" id="kpis"></div>
  <div class="grid">
    <div class="card grid-full">
      <h2>📊 Ventas por canal (últimos 6 meses)</h2>
      <div id="stacked-chart" class="stacked-chart"></div>
      <div id="stacked-legend" class="legend"></div>
    </div>
    <div class="card">
      <h2>💳 Canales este mes</h2>
      <div id="canal-mes" class="bars"></div>
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
<script>
const COLORS={card:'#3b82f6',cash:'#22c55e',uber:'#f97316',glovo:'#eab308',shop:'#a855f7',justeat:'#ef4444'};
const LABELS={card:'💳 Tarjeta',cash:'💵 Efectivo',uber:'🚗 Uber Eats',glovo:'🟡 Glovo',shop:'🛒 Shop',justeat:'🛵 Just Eat'};
const fmt=n=>n>=1000?(n/1000).toFixed(1).replace('.0','')+'k':n.toFixed(0);
const eur=n=>n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€';

async function load(){
  const auth=btoa(document.cookie.split('auth=')[1]||'');
  // Use fetch with credentials (browser will send Basic auth from the login prompt)
  const f=async(url)=>{const r=await fetch(url);if(!r.ok)throw new Error(r.status);return r.json()};

  const [kpis,canalMes,canalMeses,margen,ingresos,proveedores,facturas,categorias]=await Promise.all([
    f('/api/kpis'),f('/api/ventas-por-canal'),f('/api/canal-por-mes'),
    f('/api/margen-por-mes'),f('/api/ingresos-por-mes'),f('/api/gastos-por-proveedor'),f('/api/facturas-recientes'),f('/api/gastos-por-categoria')
  ]);

  // KPIs
  document.getElementById('kpis').innerHTML=`
    <div class="kpi"><div class="label">Ventas mes</div><div class="value green">${eur(kpis.ventas_mes)}</div><div class="sub">${kpis.facturas_ventas} facturas</div></div>
    <div class="kpi"><div class="label">Gastos mes</div><div class="value red">${eur(kpis.gastos_mes)}</div><div class="sub">${kpis.facturas_gastos} facturas</div></div>
    <div class="kpi"><div class="label">Margen mes</div><div class="value ${kpis.margen_mes>=0?'green':'red'}">${eur(kpis.margen_mes)}</div></div>
    <div class="kpi"><div class="label">IVA mes</div><div class="value blue">${eur(kpis.iva_mes)}</div></div>
    <div class="kpi"><div class="label">Delivery</div><div class="value yellow">${eur(kpis.delivery_mes)}</div></div>
  `;

  // Canal este mes (bars)
  const maxCanal=Math.max(...canalMes.map(c=>c.total_eur),1);
  document.getElementById('canal-mes').innerHTML=canalMes.map(c=>`
    <div class="bar-row">
      <div class="bar-label">${LABELS[c.canal]||c.canal}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(c.total_eur/maxCanal*100).toFixed(1)}%;background:${COLORS[c.canal]||'#64748b'}">${eur(c.total_eur)}</div></div>
      <div class="bar-value">${c.pagos} pagos</div>
    </div>
  `).join('');

  // Stacked chart (6 meses × canales)
  const meses=[...new Set(canalMeses.map(r=>r.mes))].sort();
  const canales=[...new Set(canalMeses.map(r=>r.canal))];
  const dataByMes={};
  canalMeses.forEach(r=>{if(!dataByMes[r.mes])dataByMes[r.mes]={};dataByMes[r.mes][r.canal]=r.total_eur});
  const maxMes=Math.max(...meses.map(m=>canales.reduce((s,c)=>s+(dataByMes[m]?.[c]||0),0)),1);
  document.getElementById('stacked-chart').innerHTML=meses.map(m=>{
    let cumHeight=0;
    const segs=canales.map(c=>{
      const v=dataByMes[m]?.[c]||0;
      const h=v/maxMes*100;
      cumHeight+=h;
      return `<div class="stacked-seg" style="height:${h.toFixed(1)}%;background:${COLORS[c]||'#64748b'}" title="${LABELS[c]||c}: ${eur(v)}"></div>`;
    }).reverse().join('');
    const total=canales.reduce((s,c)=>s+(dataByMes[m]?.[c]||0),0);
    return `<div class="stacked-bar">${segs}<div style="text-align:center;font-size:.65rem;color:#64748b;padding-top:4px">${m.slice(5)}<br>${fmt(total)}</div></div>`;
  }).join('');
  document.getElementById('stacked-legend').innerHTML=canales.map(c=>`<div class="legend-item"><div class="legend-dot" style="background:${COLORS[c]||'#64748b'}"></div>${LABELS[c]||c}</div>`).join('');

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
    </div>
  `).join('');

  // Ingresos por mes (table)
  document.getElementById('ingresos').innerHTML=`<table>
    <tr><th>Mes</th><th>Facturas</th><th>Total</th><th>Base</th><th>IVA</th><th>Delivery</th><th>Dto.</th></tr>
    ${ingresos.map(r=>`<tr><td>${r.mes}</td><td>${r.facturas}</td><td><b>${eur(r.total_eur)}</b></td><td>${eur(r.base_eur)}</td><td>${eur(r.iva_eur)}</td><td>${eur(r.delivery_eur)}</td><td>${eur(r.descuentos_eur)}</td></tr>`).join('')}
  </table>`;

  // Proveedores
  const maxProv=Math.max(...proveedores.map(p=>p.total_eur),1);
  document.getElementById('proveedores').innerHTML=proveedores.map(p=>`
    <div class="bar-row">
      <div class="bar-label" style="min-width:140px">${p.proveedor.slice(0,20)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(p.total_eur/maxProv*100).toFixed(1)}%;background:#8b5cf6">${eur(p.total_eur)}</div></div>
      <div class="bar-value">${p.facturas} fc.</div>
    </div>
  `).join('');

  // Categorias
  const maxCat=Math.max(...categorias.map(c=>c.total_eur),1);
  document.getElementById('categorias').innerHTML=categorias.map(c=>`
    <div class="bar-row">
      <div class="bar-label" style="min-width:110px">${c.categoria.slice(0,15)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(c.total_eur/maxCat*100).toFixed(1)}%;background:${c.color||'#6b7280'}">${eur(c.total_eur)}</div></div>
      <div class="bar-value">${c.facturas} fc.</div>
    </div>
  `).join('');

  // Facturas recientes
  document.getElementById('facturas').innerHTML=`<table>
    <tr><th>Nº</th><th>Fecha</th><th>Cliente</th><th>Canales</th><th>Total</th></tr>
    ${facturas.map(f=>{
      const tags=(f.canales||'').split(',').map(c=>c.trim()).filter(Boolean).map(c=>`<span class="tag tag-${c}">${c}</span>`).join(' ');
      return `<tr><td>${f.number}</td><td>${f.fecha}</td><td>${f.cliente}</td><td>${tags}</td><td><b>${eur(f.total_eur)}</b></td></tr>`;
    }).join('')}
  </table>`;
}
load().catch(e=>document.querySelector('.container').innerHTML='<p style="color:#ef4444">Error cargando datos: '+e.message+'</p>');
</script>
</body>
</html>"""
