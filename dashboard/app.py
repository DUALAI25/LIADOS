"""
Mini-dashboard Liados — FastAPI + HTML plano.
Sirve un solo HTML con 4 paneles: KPIs, top vendors, facturas recientes, resumen mensual.
Datos en vivo desde Postgres.
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

# Agente de chat con OpenCode Go + MCP
from dashboard.agent import ask as agent_ask

app = FastAPI(title="Liados Dashboard", version="1.0.0")

security = HTTPBasic()


def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    expected_user = os.getenv("DASHBOARD_USER", "jefe")
    expected_pass = os.getenv("DASHBOARD_PASSWORD", "jefe2026")
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
def api_kpis(user: str = Depends(get_current_user)):
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
def api_top_vendors(limit: int = 8, user: str = Depends(get_current_user)):
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
def api_recent_invoices(limit: int = 12, user: str = Depends(get_current_user)):
    rows = q("""
        SELECT invoice_number, invoice_date, type, status,
               COALESCE(vendor_name, '—') AS vendor,
               total_amount::float AS total, currency
        FROM invoices WHERE status NOT IN ('duplicate','rejected')
        ORDER BY created_at DESC LIMIT %s;
    """, (limit,))
    return [to_dict(r) for r in rows]


@app.get("/api/monthly")
def api_monthly(user: str = Depends(get_current_user)):
    rows = q("""
        SELECT to_char(month, 'YYYY-MM') AS mes,
               ROUND(income::numeric, 2)  AS ingresos,
               ROUND(expense::numeric, 2) AS gastos,
               ROUND(net::numeric, 2)     AS neto
        FROM monthly_net ORDER BY month DESC LIMIT 6;
    """)
    return [to_dict(r) for r in rows]


# --- Agente de chat ---
@app.post("/api/chat")
def api_chat(payload: dict, user: str = Depends(get_current_user)):
    """Endpoint de chat con el agente financiero. Body: {"question": "..."}"""
    question = payload.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "Pregunta vacia"}, status_code=400)
    try:
        answer = agent_ask(question)
        return {"question": question, "answer": answer}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- HTML ---
HTML = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🍻</text></svg>">
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

<!-- ===== CHAT PANEL ===== -->
<style>
  .chat-fab {
    position: fixed; bottom: 24px; right: 24px;
    width: 56px; height: 56px; border-radius: 50%;
    background: #8b5cf6; color: white; border: none;
    font-size: 24px; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    z-index: 1000; transition: transform 0.2s;
  }
  .chat-fab:hover { transform: scale(1.1); }
  .chat-panel {
    position: fixed; bottom: 90px; right: 24px;
    width: 380px; height: 520px; max-height: 80vh;
    background: #1e293b; border: 1px solid #334155; border-radius: 12px;
    display: none; flex-direction: column;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5); z-index: 999;
    font-size: 14px;
  }
  .chat-panel.open { display: flex; }
  .chat-header {
    padding: 14px 16px; border-bottom: 1px solid #334155;
    display: flex; justify-content: space-between; align-items: center;
    background: #0f172a; border-radius: 12px 12px 0 0;
  }
  .chat-header h3 { font-size: 14px; color: #f8fafc; margin: 0; }
  .chat-header .close { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 20px; }
  .chat-header .close:hover { color: #f8fafc; }
  .chat-messages {
    flex: 1; overflow-y: auto; padding: 16px;
    display: flex; flex-direction: column; gap: 10px;
  }
  .chat-messages::-webkit-scrollbar { width: 6px; }
  .chat-messages::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
  .msg { padding: 10px 14px; border-radius: 12px; max-width: 85%; line-height: 1.4; word-wrap: break-word; }
  .msg.user {
    align-self: flex-end; background: #8b5cf6; color: white;
    border-bottom-right-radius: 4px;
  }
  .msg.bot {
    align-self: flex-start; background: #334155; color: #e2e8f0;
    border-bottom-left-radius: 4px;
  }
  .msg.error { background: #7c2d12; color: #fed7aa; align-self: flex-start; }
  .msg.thinking {
    align-self: flex-start; background: #334155; color: #94a3b8;
    font-style: italic; display: flex; align-items: center; gap: 8px;
  }
  .typing-dots { display: inline-flex; gap: 3px; }
  .typing-dots span {
    width: 6px; height: 6px; background: #94a3b8; border-radius: 50%;
    animation: typing 1.4s infinite ease-in-out;
  }
  .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
  .typing-dots span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes typing {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
    30% { transform: translateY(-4px); opacity: 1; }
  }
  .chat-input {
    display: flex; padding: 12px; border-top: 1px solid #334155; gap: 8px;
  }
  .chat-input input {
    flex: 1; padding: 10px 14px; border-radius: 8px;
    border: 1px solid #475569; background: #0f172a; color: #e2e8f0;
    font-size: 13px; outline: none;
  }
  .chat-input input:focus { border-color: #8b5cf6; }
  .chat-input input:disabled { opacity: 0.5; }
  .chat-input button {
    padding: 10px 16px; background: #8b5cf6; color: white;
    border: none; border-radius: 8px; cursor: pointer; font-size: 14px;
  }
  .chat-input button:disabled { background: #475569; cursor: not-allowed; }
  .chat-input button:hover:not(:disabled) { background: #7c3aed; }
  @media (max-width: 480px) {
    .chat-panel { width: calc(100vw - 32px); right: 16px; bottom: 80px; }
  }
</style>

<button class="chat-fab" id="chatFab" title="Abrir chat">💬</button>

<div class="chat-panel" id="chatPanel">
  <div class="chat-header">
    <h3>🤖 Asistente Liados</h3>
    <button class="close" id="chatClose" title="Cerrar">×</button>
  </div>
  <div class="chat-messages" id="chatMessages">
    <div class="msg bot">¡Hola! Pregúntame lo que quieras sobre tus facturas, gastos o ventas. Ej: <em>"¿Cuánto he gastado este mes?"</em></div>
  </div>
  <form class="chat-input" id="chatForm">
    <input type="text" id="chatInput" placeholder="Escribe tu pregunta…" autocomplete="off" maxlength="500" />
    <button type="submit" id="chatSend">Enviar</button>
  </form>
</div>

<script>
(function() {
  const fab = document.getElementById('chatFab');
  const panel = document.getElementById('chatPanel');
  const close = document.getElementById('chatClose');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatInput');
  const send = document.getElementById('chatSend');
  const messages = document.getElementById('chatMessages');

  fab.addEventListener('click', () => {
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) input.focus();
  });
  close.addEventListener('click', () => panel.classList.remove('open'));

  function addMsg(text, type) {
    const div = document.createElement('div');
    div.className = 'msg ' + type;
    div.innerHTML = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function addThinking() {
    const div = document.createElement('div');
    div.className = 'msg thinking';
    div.innerHTML = 'Pensando <span class="typing-dots"><span></span><span></span><span></span></span>';
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML.replace(/\\n/g, '<br>');
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;

    addMsg(esc(q), 'user');
    input.value = '';
    input.disabled = true;
    send.disabled = true;
    const thinking = addThinking();

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q })
      });
      thinking.remove();
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: 'Error desconocido' }));
        addMsg('⚠️ ' + esc(err.error || 'Error ' + resp.status), 'error');
      } else {
        const data = await resp.json();
        addMsg(esc(data.answer || '(sin respuesta)'), 'bot');
      }
    } catch (err) {
      thinking.remove();
      addMsg('⚠️ Error de conexión: ' + esc(err.message), 'error');
    } finally {
      input.disabled = false;
      send.disabled = false;
      input.focus();
    }
  });
})();
</script>

</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index(user: str = Depends(get_current_user)):
    return HTML


@app.get("/healthz")
def health(user: str = Depends(get_current_user)):
    try:
        q("SELECT 1")
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return JSONResponse({"status": "error", "db": str(e)}, status_code=500)
