/* =========================================================================
   Liados Dashboard · app.js (v5 premium)
   Depende de Chart.js (CDN)
   ========================================================================= */

// ── Constantes ───────────────────────────────────────────────────────────
const COLORS = { card:'#3b82f6', cash:'#22c55e', uber:'#f97316', glovo:'#eab308', shop:'#a855f7', justeat:'#ef4444' };
const LABELS = { card:'Tarjeta', cash:'Efectivo', uber:'Uber Eats', glovo:'Glovo', shop:'Shop', justeat:'Just Eat' };
const ICONS  = { card:'💳', cash:'💵', uber:'🚗', glovo:'🟡', shop:'🛒', justeat:'🛵' };

const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => [...r.querySelectorAll(s)];
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const eur = n => Number(n||0).toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2}) + '€';
const eur0 = n => Number(n||0).toLocaleString('es-ES', {maximumFractionDigits:0}) + '€';
const fmt = n => Math.abs(n)>=1000 ? (n/1000).toFixed(1).replace('.0','')+'k' : Math.round(n).toString();
const pct = (cur, prev) => { if (!prev) return null; return (cur-prev)/Math.abs(prev)*100; };
const esc = s => (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

// ── Markdown renderer (minimal, seguro: escapa primero) ──────────────────
function mdToHtml(md) {
  if (!md) return '';
  // 1. Extraer bloques de codigo ``` ... ```
  const blocks = [];
  let text = md.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    blocks.push(`<pre class="md-code"><code>${esc(code.replace(/\n$/,''))}</code></pre>`);
    return `\u0000BLOCK${blocks.length-1}\u0000`;
  });
  // 2. Escapar el resto
  text = esc(text);
  // 3. Tablas: | a | b |\n| --- | --- |\n...
  text = text.replace(/^(\|.+\|)\n(\|[\s\-:|]+\|)\n((?:\|.+\|\n?)+)/gm, (m, hdr, sep, body) => {
    const cols = hdr.split('|').filter((_,i,a)=>i>0&&i<a.length-1).map(c=>c.trim());
    const rows = body.trim().split('\n').map(r => r.split('|').filter((_,i,a)=>i>0&&i<a.length-1).map(c=>c.trim()));
    const thead = '<tr>' + cols.map(c=>`<th>${c}</th>`).join('') + '</tr>';
    const tbody = rows.map(r => '<tr>' + r.map((c,i)=>`<td${i===0?' class="num"':''}>${c}</td>`).join('') + '</tr>').join('');
    return `<div class="table-wrap"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`;
  });
  // 4. Inline: bold, codigo, separadores de linea en listas
  const lines = text.split('\n');
  let out = '', inUl = false, inOl = false;
  const closeLists = () => { if(inUl){out+='</ul>';inUl=false;} if(inOl){out+='</ol>';inOl=false;} };
  for (let line of lines) {
    if (/^\s*[-•]\s+/.test(line)) { if(!inUl){closeLists();out+='<ul class="md-ul">';inUl=true;} out += '<li>'+inlineMd(line.replace(/^\s*[-•]\s+/,''))+'</li>'; }
    else if (/^\s*\d+\.\s+/.test(line)) { if(!inOl){closeLists();out+='<ol class="md-ol">';inOl=true;} out += '<li>'+inlineMd(line.replace(/^\s*\d+\.\s+/,''))+'</li>'; }
    else if (line.trim()==='') { closeLists(); out += ''; }
    else { closeLists(); out += '<p>'+inlineMd(line)+'</p>'; }
  }
  closeLists();
  out = out.replace(/<\/p><p>/g, '<br>');
  // 5. Restaurar bloques de codigo
  out = out.replace(/\u0000BLOCK(\d+)\u0000/g, (m,i) => blocks[+i]);
  return out;
}
function inlineMd(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code class="md-code-i">$1</code>')
    .replace(/(^|\s)(\d[\d.\u00a0]*\s?€)/g, '$1<span class="md-amt">$2</span>');
}

// ── Theme ────────────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('liados_theme');
  const theme = saved || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  document.documentElement.setAttribute('data-theme', theme);
  updateThemeBtn(theme);
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('liados_theme', next);
  updateThemeBtn(next);
  // Re-tematizar charts
  applyChartTheme();
  chartsRefreshColors();
}
function updateThemeBtn(theme) {
  const btn = $('#themeToggle');
  if (!btn) return;
  btn.innerHTML = theme === 'dark'
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
}

// ── Sidebar toggle ───────────────────────────────────────────────────────
function initSidebar() {
  const app = $('#app');
  $('#sidebarToggle').onclick = () => {
    if (matchMedia('(max-width: 900px)').matches) {
      $('#sidebar').classList.add('open');
      $('#backdrop').classList.add('show');
    } else {
      app.classList.toggle('collapsed');
      localStorage.setItem('liados_sidebar', app.classList.contains('collapsed') ? '1' : '0');
      // charts necesitan resize tras transición
      setTimeout(() => Object.values(charts).forEach(c => c && c.resize()), 320);
    }
  };
  $('#backdrop').onclick = () => { $('#sidebar').classList.remove('open'); $('#backdrop').classList.remove('show'); };
  if (localStorage.getItem('liados_sidebar') === '1') app.classList.add('collapsed');
}

// ── Navegación entre vistas (pestañas de la sidebar) ─────────────────────
const VIEWS_RENDERED = new Set();
function initNav() {
  $$('.nav-item').forEach(item => {
    item.onclick = (e) => {
      e.preventDefault();
      const v = item.getAttribute('data-view');
      if (!v) return;
      $$('.nav-item').forEach(n => n.classList.remove('active'));
      item.classList.add('active');
      $$('.view').forEach(s => s.classList.toggle('active', s.getAttribute('data-view') === v));
      const label = item.querySelector('.nav-label');
      if (label) $('#crumbView').textContent = label.textContent;
      // Render lazy de la vista si no se ha hecho aún
      if (!VIEWS_RENDERED.has(v)) {
        if (v === 'ventas') renderVentas();
        if (v === 'gastos') renderGastos();
        VIEWS_RENDERED.add(v);
      }
      // Resize charts al volver a mostrar una vista (corrige tamaños tras display:none)
      setTimeout(() => Object.values(charts).forEach(c => c && c.resize()), 80);
      // Cerrar drawer en mobile
      if (matchMedia('(max-width: 900px)').matches) {
        $('#sidebar').classList.remove('open');
        $('#backdrop').classList.remove('show');
      }
    };
  });
}

async function renderVentas() {
  const c = chartColors();
  const tip = { enabled:false, external: externalTooltip() };
  // Chart 90 días (lazy load)
  try {
    const dia90 = await getJSON('/api/ventas-por-dia?days=90');
    charts.ventas90 && charts.ventas90.destroy();
    charts.ventas90 = new Chart($('#ventas-chart-90'), {
      type:'line',
      data:{ labels: dia90.map(r=>r.dia.slice(5)), datasets:[{
        label:'Ingresos/día', data: dia90.map(r=>r.total_eur),
        borderColor: css('--green'), backgroundColor:'rgba(34,197,94,.14)', fill:true,
        tension:.35, pointRadius:0, pointHoverRadius:5, borderWidth:2.5
      }]},
      options:{ responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display:false}, tooltip: tip },
        interaction:{ mode:'index', intersect:false },
        scales:{ x:{ grid:{display:false}, ticks:{color:c.ticks, maxTicksLimit:12} }, y:{ grid:{color:c.grid}, border:{display:false}, ticks:{color:c.ticks, callback:v=>fmt(v)} } } }
    });
  } catch(e) {}
  // Canales histórico (agregado 6m por canal)
  const agg = {};
  (DATA.canalMeses||[]).forEach(r => { agg[r.canal] = (agg[r.canal]||0) + r.total_eur; });
  const rows = Object.entries(agg).sort((a,b)=>b[1]-a[1]).map(([canal,total])=>({canal,total}));
  renderBars('#ventas-canales-hist', rows, r=>COLORS[r.canal]||css('--cyan'), r=>ICONS[r.canal]+' '+LABELS[r.canal], r=>r.total, r=>{
    const p = (DATA.canalMes||[]).find(x=>x.canal===r.canal); return p ? p.pagos+' pagos mes' : '';
  });
  // Resumen mensual (tabla)
  $('#ventas-resumen').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Mes</th><th class="num">Fact.</th><th class="num">Total</th><th class="num">Base</th><th class="num">IVA</th><th class="num">Delivery</th></tr></thead>
    <tbody>${(DATA.ingresos||[]).map(r=>`<tr><td>${r.mes}</td><td class="num">${r.facturas}</td><td class="num"><b>${eur(r.total_eur)}</b></td><td class="num">${eur(r.base_eur)}</td><td class="num">${eur(r.iva_eur)}</td><td class="num">${eur(r.delivery_eur)}</td></tr>`).join('')}</tbody>
  </table></div>`;
}

async function renderGastos() {
  // Tabla de proveedores (más amplia: 50)
  try {
    const prov = await getJSON('/api/gastos-por-proveedor?limit=50');
    const max = Math.max(...prov.map(p=>p.total_eur), 1);
    $('#gastos-tabla').innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Proveedor</th><th>Facturas</th><th class="num">Total</th><th style="width:30%">Volumen</th></tr></thead>
      <tbody>${prov.map(p=>`<tr class="row-drill" data-name="${esc(p.proveedor)}" style="cursor:pointer"><td>${esc(p.proveedor)}</td><td>${p.facturas}</td><td class="num"><b>${eur(p.total_eur)}</b></td><td><div class="bar-track" style="height:8px"><div class="bar-fill" style="width:${(p.total_eur/max*100).toFixed(1)}%;background:#8b5cf6;padding:0;border-radius:4px"></div></div></td></tr>`).join('')}</tbody>
    </table></div>`;
    // Drill-down al clickar fila
    $$('#gastos-tabla .row-drill').forEach(tr => tr.onclick = () => openDrill('proveedor', tr.getAttribute('data-name')));
  } catch(e) { $('#gastos-tabla').innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">'+esc(e.message)+'</div></div>'; }
  // Categorías (drill-down)
  renderBars('#gastos-categorias', DATA.categorias||[], r=>r.color||'#6b7280', r=>(r.categoria||'').slice(0,16), r=>r.total_eur, r=>`${r.facturas} fc.`);
  $$('#gastos-categorias .bar-row').forEach(row => {
    row.style.cursor = 'pointer';
    const name = row.querySelector('.bar-label')?.textContent?.trim();
    row.onclick = () => name && openDrill('categoria', name);
  });
  // Margen
  const mmax = Math.max(...(DATA.margen||[]).map(m=>Math.max(m.ingresos,m.gastos)), 1);
  $('#gastos-margen').innerHTML = (DATA.margen||[]).map(m => `
    <div style="margin-bottom:var(--s-3)">
      <div style="font-size:var(--fz-sm);color:var(--fg-3);margin-bottom:4px;display:flex;justify-content:space-between"><span>${m.mes}</span><span class="${m.margen>=0?'delta good':'delta bad'}" style="padding:1px 7px">Margen ${eur(m.margen)}</span></div>
      <div class="bar-row"><div class="bar-label" style="min-width:64px;font-size:var(--fz-sm)">Ingresos</div><div class="bar-track"><div class="bar-fill" style="width:${(m.ingresos/mmax*100).toFixed(1)}%;background:var(--green)">${eur(m.ingresos)}</div></div></div>
      <div class="bar-row" style="margin-top:4px"><div class="bar-label" style="min-width:64px;font-size:var(--fz-sm)">Gastos</div><div class="bar-track"><div class="bar-fill" style="width:${(m.gastos/mmax*100).toFixed(1)}%;background:var(--red)">${eur(m.gastos)}</div></div></div>
    </div>`).join('');
}

// ── Counter animation ────────────────────────────────────────────────────
function animateCount(el, to, opts={}) {
  const { dur=900, decimals=2, suffix='€', prefix='' } = opts;
  const from = 0;
  const start = performance.now();
  const ease = t => 1 - Math.pow(1 - t, 3);
  function frame(now) {
    const p = Math.min((now - start) / dur, 1);
    const v = from + (to - from) * ease(p);
    el.textContent = prefix + v.toLocaleString('es-ES', {minimumFractionDigits:decimals, maximumFractionDigits:decimals}) + suffix;
    if (p < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

// ── Chart.js theme ───────────────────────────────────────────────────────
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.font.size = 12;

function chartColors() {
  const dark = document.documentElement.getAttribute('data-theme') !== 'light';
  return {
    grid: dark ? 'rgba(148,163,184,.08)' : 'rgba(15,23,42,.07)',
    ticks: dark ? '#94a3b8' : '#475569',
    fg: dark ? '#f1f5f9' : '#0f172a',
    fg2: dark ? '#cbd5e1' : '#1e293b',
    fg3: dark ? '#64748b' : '#94a3b8',
    tipBg: dark ? '#243044' : '#ffffff',
    tipBorder: dark ? '#3b4a63' : '#e6ebf3',
  };
}

// Tooltip custom HTML
function externalTooltip(handler) {
  return (ctx) => {
    const { chart, tooltip } = ctx;
    let el = chart.canvas.parentNode.querySelector('.chart-tip');
    if (!el) {
      el = document.createElement('div');
      el.className = 'chart-tip';
      el.style.cssText = 'position:absolute;background:var(--bg-3);border:1px solid var(--border-strong);border-radius:10px;padding:10px 12px;pointer-events:none;opacity:0;transition:opacity .12s;box-shadow:var(--shadow-3);z-index:50;font-size:12px;min-width:160px;transform:translate(-50%,-100%)';
      chart.canvas.parentNode.appendChild(el);
    }
    if (tooltip.opacity === 0) { el.style.opacity = 0; return; }
    const c = chartColors();
    const title = tooltip.title[0] || '';
    const items = tooltip.dataPoints.map(p => {
      const label = p.dataset.label || p.label;
      const val = p.raw;
      const color = p.dataset.backgroundColor || p.dataset.borderColor;
      return `<div style="display:flex;align-items:center;gap:6px;margin-top:4px"><span style="width:8px;height:8px;border-radius:2px;background:${color}"></span><span style="color:${c.fg2};flex:1">${label}</span><b style="font-family:var(--font-mono);color:${c.fg}">${eur(val)}</b></div>`;
    }).join('');
    const total = tooltip.dataPoints.reduce((s,p) => s + (p.raw||0), 0);
    const totalRow = tooltip.dataPoints.length > 1 ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border);display:flex;justify-content:space-between"><span style="color:${c.fg3}">Total</span><b style="font-family:var(--font-mono);color:${c.fg}">${eur(total)}</b></div>` : '';
    el.innerHTML = `<div style="font-weight:600;color:${c.fg};font-size:13px">${title}</div>${items}${totalRow}`;
    const pos = chart.canvas.getBoundingClientRect();
    el.style.opacity = 1;
    el.style.left = tooltip.caretX + 'px';
    el.style.top = (tooltip.caretY - 8) + 'px';
  };
}

function applyChartTheme() {
  const c = chartColors();
  Chart.defaults.color = c.ticks;
  Chart.defaults.borderColor = c.grid;
}

function chartsRefreshColors() {
  // Recrear para que adopten el nuevo tema (sencillo y robusto).
  // Importante: primero limpiamos tooltips huerfanos del DOM.
  $$('.chart-tip').forEach(t => t.remove());
  Object.values(charts).forEach(ch => ch && ch.destroy());
  charts = {};
  renderCharts();
}

// ── Estado global ────────────────────────────────────────────────────────
let DATA = {};
let charts = {};
let canalFilter = 'all';
let showMom = false;

// ── Auth helpers ─────────────────────────────────────────────────────────
// HTTP Basic Auth: el navegador abre un popup nativo (más seguro que prompt()
// y compatible con todos los browsers). Cacheamos credenciales codificadas en
// sessionStorage para no spammear al usuario.
function _getAuth() {
  let auth = sessionStorage.getItem('liados_basic');
  if (auth) return auth;
  // El browser pedira usuario/contrasena via popup nativo en el primer 401.
  return null;
}

function _setAuth(user, pass) {
  const auth = btoa(user + ':' + pass);
  sessionStorage.setItem('liados_basic', auth);
  return auth;
}

function _clearAuth() {
  sessionStorage.removeItem('liados_basic');
}

function _authHeader() {
  const auth = _getAuth();
  return auth ? { 'Authorization': 'Basic ' + auth } : {};
}

async function _fetchOnce(url, opts = {}) {
  const headers = { ...(opts.headers || {}), ..._authHeader() };
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  return fetch(url, { ...opts, headers, cache: 'no-store' });
}

async function _fetchAuth(url, opts = {}) {
  let r = await _fetchOnce(url, opts);
  if (r.status === 401) {
    // Credenciales invalidas o expiradas -> limpiamos para forzar re-prompt.
    _clearAuth();
    r = await _fetchOnce(url, opts);
  }
  return r;
}

async function getJSON(url) {
  const r = await _fetchAuth(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function _getAuthHeaders() { return _authHeader(); }  // compat: usado por stream y otros


// ── Render ───────────────────────────────────────────────────────────────
function renderHero() {
  const k = DATA.kpis, comp = DATA.comp, sp = DATA.spark6m;
  const margin = k.margen_mes;
  const dp = comp.margen.delta_pct;
  const dpU = dp != null && dp >= 0;
  $('#heroValue').className = 'hero-value ' + (margin >= 0 ? 'pos' : 'neg');
  animateCount($('#heroValue'), margin, {decimals:2});
  // delta (margen: subir = bueno)
  $('#heroDelta').className = 'delta ' + (dp==null ? 'flat' : (dpU ? 'up' : 'down'));
  $('#heroDelta').innerHTML = deltaInner(comp.margen.delta_pct);
  const margenPct = k.ventas_mes ? (margin/k.ventas_mes*100) : 0;
  $('#heroMeta').innerHTML = `
    <div class="meta">Ventas <b>${eur(k.ventas_mes)}</b></div>
    <div class="meta">Gastos <b>${eur(k.gastos_mes)}</b></div>
    <div class="meta">Margen s/ventas <b>${margenPct.toFixed(1)}%</b></div>`;
  // sparkline hero
  const ctx = $('#heroSpark');
  if (charts.hero) charts.hero.destroy();
  charts.hero = new Chart(ctx, {
    type:'line',
    data:{ labels: sp.map(r=>r.mes.slice(5)), datasets:[{
      data: sp.map(r=>r.total_eur), borderColor: css('--blue'),
      backgroundColor: 'rgba(59,130,246,.12)', fill:true, tension:.4,
      pointRadius:0, borderWidth:2.5
    }]},
    options:{ responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{ enabled:false } },
      scales:{ x:{display:false}, y:{display:false} } }
  });
}

function deltaInner(d) {
  if (d == null) return '— sin dato anterior';
  const arrow = d >= 0 ? '▲' : '▼';
  return `${arrow} ${Math.abs(d).toFixed(1)}% <span style="opacity:.7;font-weight:500">vs mes ant.</span>`;
}

function renderKpis() {
  const k = DATA.kpis, comp = DATA.comp;
  const cards = [
    { label:'Ventas mes', value:k.ventas_mes, color:'green', sub:`${k.facturas_ventas} facturas`, delta:comp.ventas.delta_pct, deltaGood: v=>v>=0 },
    { label:'Gastos mes', value:k.gastos_mes, color:'red', sub:`${k.facturas_gastos} facturas`, delta:comp.gastos.delta_pct, deltaGood: v=>v<0 },
    { label:'IVA repercutido', value:k.iva_mes, color:'blue', sub:'Soportado sobre ventas', delta:null },
    { label:'Delivery', value:k.delivery_mes, color:'yellow', sub:'Comisiones reparto', delta:null },
  ];
  $('#kpis').innerHTML = cards.map((c,i) => {
    let dhtml = '';
    if (c.delta != null) {
      const good = c.deltaGood(c.delta);
      dhtml = `<span class="delta ${good?'good':'bad'}">${c.delta>=0?'▲':'▼'} ${Math.abs(c.delta).toFixed(1)}%</span>`;
    }
    return `<div class="kpi">
      <div class="accent-bar" style="background:var(--${c.color})"></div>
      <div class="label">${c.label}</div>
      <div class="value ${c.color}" id="kpi-${i}" style="color:var(--${c.color}-fg)">0€</div>
      <div class="sub">${c.sub} ${dhtml}</div>
    </div>`;
  }).join('');
  cards.forEach((c,i) => animateCount($(`#kpi-${i}`), c.value, {decimals:2}));
}

function renderBars(target, rows, colorFn, labelFn, valueFn, extraFn) {
  const max = Math.max(...rows.map(valueFn), 1);
  $(target).innerHTML = rows.map(r => {
    const color = colorFn(r);
    return `<div class="bar-row">
      <div class="bar-label">${labelFn(r)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(valueFn(r)/max*100).toFixed(1)}%;background:${color}">${eur(valueFn(r))}</div></div>
      <div class="bar-value">${extraFn(r)}</div>
    </div>`;
  }).join('') || emptyState('Sin datos este mes', 'Aún no se han registrado movimientos en el periodo actual.');
}

function emptyState(title, desc, err=false) {
  const ico = err
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 3 5-6"/></svg>';
  return `<div class="state ${err?'error':''}">${ico}<div class="title">${title}</div><div class="desc">${desc}</div></div>`;
}

function renderCharts() {
  const c = chartColors();
  const tip = { enabled:false, external: externalTooltip() };

  // 1. Stacked canales x mes (con filtro)
  let canalMeses = DATA.canalMeses;
  if (canalFilter !== 'all') canalMeses = canalMeses.filter(r => r.canal === canalFilter);
  const meses = [...new Set(canalMeses.map(r=>r.mes))].sort();
  const canales = canalFilter !== 'all' ? [canalFilter] : [...new Set(canalMeses.map(r=>r.canal))];
  const byMes = {}; canalMeses.forEach(r => { (byMes[r.mes] = byMes[r.mes]||{})[r.canal] = r.total_eur; });
  const ds = canales.map(cn => ({
    label: ICONS[cn]+' '+LABELS[cn], icon: ICONS[cn],
    data: meses.map(m => byMes[m]?.[cn]||0),
    backgroundColor: COLORS[cn]||'#64748b', stack:'s', borderRadius:4, borderSkipped:false,
  }));
  if (charts.canales) charts.canales.destroy();
  charts.canales = new Chart($('#chart-canales'), {
    type:'bar', data:{ labels: meses.map(m=>m.slice(5)), datasets: ds },
    options:{ responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ display:true, position:'bottom', labels:{ boxWidth:10, boxHeight:10, padding:14, font:{size:11}, color:c.ticks } }, tooltip: tip },
      scales:{ x:{ stacked:true, grid:{display:false}, ticks:{color:c.ticks} }, y:{ stacked:true, grid:{color:c.grid}, border:{display:false}, ticks:{color:c.ticks, callback:v=>fmt(v)} } } }
  });

  // 2. Tendencia diaria (+ MoM opcional)
  const dia = DATA.dia;
  const labels = dia.map(r=>r.dia.slice(5));
  const datasets = [{
    label:'Ingresos/día', data: dia.map(r=>r.total_eur),
    borderColor: css('--blue'), backgroundColor:'rgba(59,130,246,.14)', fill:true,
    tension:.35, pointRadius:0, pointHoverRadius:5, borderWidth:2.5
  }];
  if (showMom && DATA.diaMom) {
    datasets.push({
      label:'Mes anterior', data: DATA.diaMom.map(r=>r.total_eur),
      borderColor: css('--fg-3'), backgroundColor:'transparent', fill:false,
      tension:.35, pointRadius:0, borderWidth:1.5, borderDash:[5,4]
    });
  }
  if (charts.diario) charts.diario.destroy();
  charts.diario = new Chart($('#chart-diario'), {
    type:'line', data:{ labels, datasets },
    options:{ responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ display: showMom, position:'bottom', labels:{boxWidth:18, padding:12, color:c.ticks} }, tooltip: tip },
      interaction:{ mode:'index', intersect:false },
      scales:{ x:{ grid:{display:false}, ticks:{color:c.ticks, maxTicksLimit:10} }, y:{ grid:{color:c.grid}, border:{display:false}, ticks:{color:c.ticks, callback:v=>fmt(v)} } } }
  });
}

function renderRest() {
  // Canal este mes
  renderBars('#canal-mes', DATA.canalMes, r=>COLORS[r.canal]||css('--cyan'), r=>ICONS[r.canal]+' '+LABELS[r.canal], r=>r.total_eur, r=>`${r.pagos} pagos`);
  // Por local
  renderBars('#local-mes', DATA.localesMes, r=>css('--cyan'), r=>(r.nombre||'Local').slice(0,16), r=>r.total_eur, r=>`${r.facturas} fact.`);
  // Margen por mes
  const mmax = Math.max(...DATA.margen.map(m=>Math.max(m.ingresos,m.gastos)), 1);
  $('#margen').innerHTML = DATA.margen.map(m => `
    <div style="margin-bottom:var(--s-3)">
      <div style="font-size:var(--fz-sm);color:var(--fg-3);margin-bottom:4px;display:flex;justify-content:space-between"><span>${m.mes}</span><span class="${m.margen>=0?'delta good':'delta bad'}" style="padding:1px 7px">Margen ${eur(m.margen)}</span></div>
      <div class="bar-row">
        <div class="bar-label" style="min-width:64px;font-size:var(--fz-sm)">Ingresos</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(m.ingresos/mmax*100).toFixed(1)}%;background:var(--green)">${eur(m.ingresos)}</div></div>
      </div>
      <div class="bar-row" style="margin-top:4px">
        <div class="bar-label" style="min-width:64px;font-size:var(--fz-sm)">Gastos</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(m.gastos/mmax*100).toFixed(1)}%;background:var(--red)">${eur(m.gastos)}</div></div>
      </div>
    </div>`).join('');

  // Ingresos por mes (tabla)
  $('#ingresos').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Mes</th><th class="num">Fact.</th><th class="num">Total</th><th class="num">Base</th><th class="num">IVA</th><th class="num">Deliv.</th><th class="num">Dto.</th></tr></thead>
    <tbody>${DATA.ingresos.map(r=>`<tr><td>${r.mes}</td><td class="num">${r.facturas}</td><td class="num"><b>${eur(r.total_eur)}</b></td><td class="num">${eur(r.base_eur)}</td><td class="num">${eur(r.iva_eur)}</td><td class="num">${eur(r.delivery_eur)}</td><td class="num">${eur(r.descuentos_eur)}</td></tr>`).join('')}</tbody>
  </table></div>`;

  // Proveedores
  renderBars('#proveedores', DATA.proveedores, r=>'#8b5cf6', r=>(r.proveedor||'').slice(0,18), r=>r.total_eur, r=>`${r.facturas} fc.`);
  // Categorías
  renderBars('#categorias', DATA.categorias, r=>r.color||'#6b7280', r=>(r.categoria||'').slice(0,15), r=>r.total_eur, r=>`${r.facturas} fc.`);
  // Facturas recientes
  $('#facturas').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Nº</th><th>Fecha</th><th>Cliente</th><th>Canales</th><th class="num">Total</th></tr></thead>
    <tbody>${DATA.facturas.map(f=>{const tags=(f.canales||'').split(',').map(x=>x.trim()).filter(Boolean).map(x=>`<span class="tag tag-${x}">${ICONS[x]||''} ${x}</span>`).join(' ');return `<tr><td>${f.number}</td><td>${f.fecha}</td><td>${esc(f.cliente)}</td><td>${tags}</td><td class="num"><b>${eur(f.total_eur)}</b></td></tr>`;}).join('')}</tbody>
  </table></div>`;
}

function buildCanalFilter() {
  const sel = $('#canalFilter');
  const opts = ['all', ...Object.keys(LABELS)];
  sel.innerHTML = opts.map(o => `<option value="${o}">${o==='all'?'Todos los canales':ICONS[o]+' '+LABELS[o]}</option>`).join('');
  sel.value = canalFilter;
  sel.onchange = () => { canalFilter = sel.value; renderCharts(); };
}

// ── Carga principal ──────────────────────────────────────────────────────
async function loadAll() {
  const [kpis, comp, canalMes, canalMeses, margen, ingresos, proveedores, facturas, categorias, localesMes, dia, spark6m] = await Promise.all([
    getJSON('/api/kpis'), getJSON('/api/kpis-comparativa'),
    getJSON('/api/ventas-por-canal'), getJSON('/api/canal-por-mes'),
    getJSON('/api/margen-por-mes'), getJSON('/api/ingresos-por-mes'),
    getJSON('/api/gastos-por-proveedor'), getJSON('/api/facturas-recientes'),
    getJSON('/api/gastos-por-categoria'), getJSON('/api/ventas-por-local'),
    getJSON('/api/ventas-por-dia?days=30'), getJSON('/api/ingresos-6m'),
  ]);
  DATA = { kpis, comp, canalMes, canalMeses, margen, ingresos, proveedores, facturas, categorias, localesMes, dia, spark6m };
  // Mostrar "última sync"
  $('#syncTime').textContent = 'hace unos segundos';
  renderHero();
  renderKpis();
  buildCanalFilter();
  renderCharts();
  renderRest();
  wireBarDrillDown();
}

// ── MoM toggle (chart diario) ────────────────────────────────────────────
async function toggleMom(on) {
  showMom = on;
  if (on && !DATA.diaMom) {
    DATA.diaMom = await getJSON('/api/ventas-por-dia?days=60').then(rows => rows.slice(0,30));
  }
  renderCharts();
}

// ── Chat ─────────────────────────────────────────────────────────────────
const SUGGEST = ['¿Cuánto he vendido este mes?','Top 5 productos de la semana','Facturas pendientes de pago','¿Qué reservas tengo mañana?','Resumen de gastos por categoría'];
let chatHistory = JSON.parse(localStorage.getItem('liados_chat_hist')||'[]');
let pendingToken = null;

function initChat() {
  const fab=$('#chatFab'), panel=$('#chatPanel');
  fab.onclick = () => { panel.classList.toggle('open'); if (panel.classList.contains('open')) { renderHistory(); renderSuggest(); $('#chatText').focus(); } };
  $('#chatClose').onclick = () => panel.classList.remove('open');
  const txt=$('#chatText');
  txt.onkeydown = e => { if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); } };
  $('#chatSend').onclick = sendMsg;
  $('#momToggle').onclick = (e) => { const on=!e.currentTarget.classList.contains('active'); e.currentTarget.classList.toggle('active',on); toggleMom(on); };
}
function renderSuggest() { $('#chatSuggest').innerHTML = SUGGEST.map(s=>`<button>${s}</button>`).join(''); $$('#chatSuggest button').forEach(b=>b.onclick=()=>{$('#chatText').value=b.textContent;sendMsg();}); }
function saveHist(){ try{ localStorage.setItem('liados_chat_hist',JSON.stringify(chatHistory.slice(-20))); }catch(e){} }
function addMsg(text,cls,extra){ const d=document.createElement('div'); d.className='msg '+cls; d.innerHTML=text+(extra||''); $('#chatBody').appendChild(d); d.scrollIntoView({behavior:'smooth'}); return d; }
function renderHistory(){ $('#chatBody').innerHTML=''; if(chatHistory.length===0){$('#chatBody').innerHTML='<div class="msg bot">¡Hola! 👋 Soy el asistente de Liados. Pregúntame sobre ventas, gastos, productos o reservas.</div>';} else chatHistory.forEach(m=>addMsg(m.role==='user'?esc(m.content):mdToHtml(m.content), m.role==='user'?'user':'bot')); }

async function sendMsg(){
  const txt=$('#chatText'); const msg=txt.value.trim(); if(!msg) return;
  txt.value=''; $('#chatSend').disabled=true;
  addMsg(esc(msg),'user');

  // Indicador "pensando" (se reemplaza al llegar el primer token/tool)
  const typing=document.createElement('div'); typing.className='typing'; typing.innerHTML='<span></span><span></span><span></span>'; $('#chatBody').appendChild(typing); typing.scrollIntoView();

  let botMsg = null;          // burbuja del bot (se crea con el primer token)
  let fullReply = '';
  let toolsUsed = [];
  let pending = null;
  let toolsChip = null;       // contenedor de chips de tools (live)

  try {
    const r = await _fetchAuth('/api/chat/stream', { method:'POST', json:{message:msg, history:chatHistory} });
    if (!r.ok) throw new Error('HTTP '+r.status);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream:true});
      const events = buffer.split('\n\n');
      buffer = events.pop();  // conserva el incompleto
      for (const ev of events) {
        const lines = ev.split('\n');
        let type='', data='';
        for (const l of lines) { if (l.startsWith('event: ')) type=l.slice(7); else if (l.startsWith('data: ')) data=l.slice(6); }
        if (!type) continue;
        const payload = data ? JSON.parse(data) : {};

        if (type === 'tool') {
          if (typing.parentNode) typing.remove();
          toolsUsed.push(payload.name);
          // Crear/actualizar chips de tools en la burbuja bot (si ya existe) o en una provisional
          if (!toolsChip) { toolsChip = document.createElement('div'); toolsChip.className='msg bot'; toolsChip.style.background='transparent'; toolsChip.style.border='none'; toolsChip.style.padding='0'; toolsChip.style.alignSelf='flex-start'; toolsChip.innerHTML='<div class="tools" style="border:none;padding:0;margin:0"></div>'; $('#chatBody').appendChild(toolsChip); }
          toolsChip.querySelector('.tools').innerHTML += `<span class="tchip">🔧 ${esc(payload.name)}</span>`;
          toolsChip.scrollIntoView({behavior:'smooth'});
        } else if (type === 'token') {
          if (typing.parentNode) typing.remove();
          if (!botMsg) { botMsg = addMsg('', 'bot'); }
          fullReply += payload.text || '';
          botMsg.innerHTML = mdToHtml(fullReply);
          botMsg.scrollIntoView({behavior:'smooth'});
        } else if (type === 'done') {
          if (typing.parentNode) typing.remove();
          fullReply = payload.reply !== undefined ? payload.reply : fullReply;
          pending = payload.pending_confirmation;
          // Adjuntar chips de tools a la burbuja final si existen
          if (toolsUsed.length) {
            const chips = `<div class="tools">${toolsUsed.map(t=>`<span class="tchip">🔧 ${esc(t)}</span>`).join('')}</div>`;
            if (botMsg) botMsg.innerHTML = mdToHtml(fullReply) + chips;
            if (toolsChip) toolsChip.remove();
          }
          chatHistory = [...chatHistory, {role:'user',content:msg}, {role:'assistant',content:fullReply}].slice(-20);
          saveHist();
          if (pending && pending.token) { pendingToken = pending.token; showConfirm(pending); }
        } else if (type === 'error') {
          if (typing.parentNode) typing.remove();
          if (toolsChip) toolsChip.remove();
          addMsg('⚠️ '+(payload.message||'Error desconocido'),'error');
          return;
        }
      }
    }
    // Si no llegó evento done (caída de conexión)
    if (!botMsg && fullReply === '') { if (typing.parentNode) typing.remove(); addMsg('Sin respuesta del servidor.','error'); }
  } catch(e) {
    if (typing.parentNode) typing.remove();
    if (toolsChip) toolsChip.remove();
    addMsg('Error de conexión: '+e.message,'error');
  }
  $('#chatSend').disabled=false; $('#chatText').focus();
}

function showConfirm(p){
  const box=document.createElement('div'); box.className='confirm-box';
  box.innerHTML=`<div><b>⚠️ ${esc(p.action)}</b><br>${esc(p.message||'Esta acción requiere confirmación.')}</div><div class="btns"><button class="yes">Confirmar</button><button class="no">Cancelar</button></div>`;
  $('#chatBody').appendChild(box); box.scrollIntoView();
  box.querySelector('.yes').onclick=async()=>{box.innerHTML='Ejecutando…';try{const r=await _fetchAuth('/api/chat/confirm',{method:'POST',json:{confirmation_token:pendingToken}});const d=await r.json().catch(()=>({error:'Respuesta no es JSON valido'}));box.remove();addMsg('```json\n'+JSON.stringify(d,null,2)+'\n```','bot');pendingToken=null;}catch(e){box.remove();addMsg('Error al confirmar: '+esc(e.message),'error');pendingToken=null;}};
  box.querySelector('.no').onclick=async()=>{try{await _fetchAuth('/api/chat/cancel',{method:'POST',json:{confirmation_token:pendingToken}});box.remove();addMsg('Acción cancelada.','bot');}catch(e){box.remove();addMsg('No se pudo cancelar (la acción puede seguir pendiente en el servidor): '+esc(e.message),'error');}pendingToken=null;};
}

// ── Reloj ────────────────────────────────────────────────────────────────
function tick(){ const d=new Date(); $('#clock').textContent=d.toLocaleString('es-ES',{weekday:'short',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}); }

// ── Modales + búsqueda + drill-down + atajos (Capa 6) ────────────────────
function openModal(id){ $('#'+id).classList.add('open'); }
function closeModal(id){ $('#'+id).classList.remove('open'); }
function closeAllModals(){ $$('.modal-overlay').forEach(m=>m.classList.remove('open')); }

function highlight(text, q) {
  if (!q) return esc(text);
  const re = new RegExp('('+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig');
  return esc(text).replace(re,'<mark>$1</mark>');
}

let searchTimer = null;
function initSearch() {
  const input = $('#searchInput');
  // Click en la barra de búsqueda del header abre el modal
  const headerSearch = $('.header .search');
  if (headerSearch) headerSearch.onclick = (e) => { e.preventDefault(); openModal('searchModal'); input.focus(); };
  input.oninput = () => {
    clearTimeout(searchTimer);
    const q = input.value.trim();
    if (q.length < 2) { $('#searchResults').innerHTML = ''; return; }
    searchTimer = setTimeout(() => doSearch(q), 200);
  };
  input.onkeydown = (e) => { if (e.key === 'Enter') doSearch(input.value.trim()); };
}

async function doSearch(q) {
  $('#searchResults').innerHTML = '<div class="search-empty">Buscando…</div>';
  try {
    const data = await getJSON('/api/search?q=' + encodeURIComponent(q));
    let html = '';
    if (data.proveedores.length) {
      html += '<div class="search-group"><div class="sg-title">Proveedores</div>';
      html += data.proveedores.map(p => `
        <div class="search-item" data-drill="proveedor" data-name="${esc(p.proveedor)}">
          <div class="si-main"><div class="si-name">${highlight(p.proveedor,q)}</div><div class="si-sub">${p.facturas} facturas</div></div>
          <div class="si-amount">${eur(p.total_eur)}</div>
        </div>`).join('');
      html += '</div>';
    }
    if (data.facturas.length) {
      html += '<div class="search-group"><div class="sg-title">Facturas</div>';
      html += data.facturas.map(f => `
        <div class="search-item" data-drill="proveedor" data-name="${esc(f.vendor_name||'')}">
          <div class="si-main"><div class="si-name">${highlight(f.vendor_name||'Sin nombre',q)} ${f.invoice_number?'· '+esc(f.invoice_number):''}</div><div class="si-sub">${f.invoice_date||''} · ${esc(f.category_raw||'')}</div></div>
          <div class="si-amount">${eur(f.total_amount)}</div>
        </div>`).join('');
      html += '</div>';
    }
    if (!html) html = '<div class="search-empty">Sin resultados para "'+esc(q)+'"</div>';
    $('#searchResults').innerHTML = html;
    // Wire click → drill-down
    $$('#searchResults .search-item').forEach(item => item.onclick = () => {
      const name = item.getAttribute('data-name');
      if (name) { closeAllModals(); openDrill('proveedor', name); }
    });
  } catch(e) { $('#searchResults').innerHTML = '<div class="search-empty">Error: '+esc(e.message)+'</div>'; }
}

async function openDrill(type, name) {
  name = (name || '').trim();
  if (!name) return;
  openModal('drillModal');
  $('#drillTitle').textContent = (type==='proveedor' ? '🧾 ' : '📦 ') + name;
  $('#drillBody').innerHTML = '<div class="search-empty">Cargando…</div>';
  try {
    const url = type==='proveedor'
      ? '/api/proveedor/' + encodeURIComponent(name) + '/facturas'
      : '/api/categoria/' + encodeURIComponent(name) + '/facturas';
    const data = await getJSON(url);
    let html = '';
    if (data.stats) {
      html += '<div class="drill-stats">' +
        `<div class="drill-stat"><div class="ds-label">Facturas</div><div class="ds-value">${data.stats.total_facturas}</div></div>` +
        `<div class="drill-stat"><div class="ds-label">Total</div><div class="ds-value">${eur(data.stats.total_eur)}</div></div>` +
        `<div class="drill-stat"><div class="ds-label">Ticket medio</div><div class="ds-value">${eur(data.stats.ticket_medio)}</div></div>` +
        `<div class="drill-stat"><div class="ds-label">Periodo</div><div class="ds-value" style="font-size:var(--fz-sm)">${esc(data.stats.primera||'—')} → ${esc(data.stats.ultima||'—')}</div></div>` +
        '</div>';
    }
    const rows = data.facturas || [];
    html += `<div class="table-wrap"><table><thead><tr><th>Fecha</th><th>${type==='proveedor'?'Nº':'Proveedor'}</th><th>Categoría</th><th class="num">Total</th></tr></thead><tbody>` +
      rows.map(r => `<tr><td>${esc(r.invoice_date||'—')}</td><td>${esc(type==='proveedor'?(r.invoice_number||''):(r.proveedor||''))}</td><td>${esc(r.category_raw||'')}</td><td class="num"><b>${eur(r.total_amount)}</b></td></tr>`).join('') +
      '</tbody></table></div>';
    $('#drillBody').innerHTML = html || '<div class="search-empty">Sin facturas.</div>';
  } catch(e) { $('#drillBody').innerHTML = '<div class="search-empty">Error: '+esc(e.message)+'</div>'; }
}

// Drill-down click en barras de proveedores/categorías
// Usa event delegation: 1 solo listener en el contenedor padre, no por fila.
function wireBarDrillDown() {
  const wire = (selector, type) => {
    const root = $(selector);
    if (!root) return;
    // Limpiamos listeners anteriores: reemplazamos el nodo (forma simple y
    // 100% segura de evitar duplicados)
    const clone = root.cloneNode(false);
    root.parentNode.replaceChild(clone, root);
    // Event delegation: 1 listener para todas las filas
    clone.addEventListener('click', (e) => {
      const row = e.target.closest('.bar-row');
      if (!row) return;
      const name = row.querySelector('.bar-label')?.textContent?.trim();
      if (name) openDrill(type, name);
    });
    clone.addEventListener('mouseenter', (e) => {
      const row = e.target.closest('.bar-row');
      if (row) row.style.filter = 'brightness(1.1)';
    }, true);
    clone.addEventListener('mouseleave', (e) => {
      const row = e.target.closest('.bar-row');
      if (row) row.style.filter = '';
    }, true);
  };
  wire('#proveedores', 'proveedor');
  wire('#categorias', 'categoria');
}

function initShortcuts() {
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea';
    // Esc cierra todo
    if (e.key === 'Escape') { closeAllModals(); $('#chatPanel').classList.remove('open'); return; }
    // En inputs: solo Esc (ya gestionado)
    if (typing) return;
    if (e.key === '/') { e.preventDefault(); openModal('searchModal'); $('#searchInput').focus(); }
    else if (e.key.toLowerCase() === 'c') { $('#chatFab').click(); }
    else if (e.key.toLowerCase() === 'r') { location.reload(); }
    else if (e.key.toLowerCase() === 't') { toggleTheme(); }
    else if (e.key === '?') { e.preventDefault(); openModal('helpModal'); }
  });
  // Botones data-close
  $$('[data-close]').forEach(b => b.onclick = () => closeModal(b.getAttribute('data-close')));
  // Click fuera del modal cierra
  $$('.modal-overlay').forEach(m => m.onclick = (e) => { if (e.target === m) m.classList.remove('open'); });
}

// ── Init ─────────────────────────────────────────────────────────────────
function init() {
  initTheme();
  initSidebar();
  initNav();
  initChat();
  initSearch();
  initShortcuts();
  applyChartTheme();
  $('#themeToggle').onclick = toggleTheme;
  tick(); setInterval(tick, 30000);
  // refresh sync label cada minuto
  let syncMin = 0;
  setInterval(() => { syncMin++; $('#syncTime').textContent = syncMin===1?'hace 1 min':`hace ${syncMin} min`; }, 60000);

  loadAll().catch(e => {
    $$('.card-body, .kpis, .hero').forEach(el => { el.style.opacity=1; });
    $('#kpis').innerHTML = `<div class="state error" style="grid-column:1/-1"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg><div class="title">Error cargando datos</div><div class="desc">${esc(e.message)}</div><button class="seg" onclick="location.reload()">Reintentar</button></div>`;
  });
}

document.addEventListener('DOMContentLoaded', init);
