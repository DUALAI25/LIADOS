/* =========================================================================
   Liados Dashboard · app.js (v5 premium)
   Depende de Chart.js (CDN)
   ========================================================================= */

// ── Constantes ───────────────────────────────────────────────────────────
const COLORS = { card:'#3b82f6', cash:'#22c55e', uber:'#f97316', glovo:'#eab308', shop:'#a855f7', justeat:'#ef4444' };
const LABELS = { card:'Tarjeta', cash:'Efectivo', uber:'Uber Eats', glovo:'Glovo', shop:'Shop', justeat:'Just Eat' };
const ICONS  = { card:'credit-card', cash:'banknote', uber:'car', glovo:'shopping-bag', shop:'shopping-cart', justeat:'bike' };

const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => [...r.querySelectorAll(s)];
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const eur = n => Number(n||0).toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2}) + '€';
const eur0 = n => Number(n||0).toLocaleString('es-ES', {maximumFractionDigits:0}) + '€';
const fmt = n => Math.abs(n)>=1000 ? (n/1000).toFixed(1).replace('.0','')+'k' : Math.round(n).toString();
const pct = (cur, prev) => { if (!prev) return null; return (cur-prev)/Math.abs(prev)*100; };
const esc = s => (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

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
      document.body.classList.toggle('cr-workbook-active', v === 'desglose' && DG.activeTab === 'pyg');
      $$('.nav-item').forEach(n => n.classList.remove('active'));
      item.classList.add('active');
      $$('.view').forEach(s => s.classList.toggle('active', s.getAttribute('data-view') === v));
      const label = item.querySelector('.nav-label');
      if (label) $('#crumbView').textContent = label.textContent;
      // Render lazy de la vista si no se ha hecho aún
      if (!VIEWS_RENDERED.has(v)) {
        if (v === 'ventas') renderVentas();
        if (v === 'gastos') renderGastos();
        if (v === 'gastos-detalle') renderGastosDetalle();
        if (v === 'alertas') renderAlertas();
        if (v === 'desglose') renderDesglose();
        if (v === 'productos') renderProductos();
        if (v === 'config') renderConfig();
        VIEWS_RENDERED.add(v);
      } else {
        // Re-render al volver a la vista si necesita refresh (alertas se autorrefrescan)
        if (v === 'gastos-detalle') refreshGastosDetalle();
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
    const rowsHtml = prov.map(p => {
      const safeName = esc(p.proveedor);
      return `<tr class="row-drill"><td>${esc(p.proveedor)}</td><td>${p.facturas}</td><td class="num"><b>${eur(p.total_eur)}</b></td><td><div class="bar-track" style="height:8px"><div class="bar-fill" style="width:${(p.total_eur/max*100).toFixed(1)}%;background:#8b5cf6;padding:0;border-radius:4px"></div></div></td></tr>`;
    }).join('');
    $('#gastos-tabla').innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Proveedor</th><th>Facturas</th><th class="num">Total</th><th style="width:30%">Volumen</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table></div>`;
    // Drill-down via event delegation (lo hace wireBarDrillDown)
  } catch(e) { $('#gastos-tabla').innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">'+esc(e.message)+'</div></div>'; }
  // Categorías (drill-down)
  renderBars('#gastos-categorias', DATA.categorias||[], r=>r.color||'#6b7280', r=>(r.categoria||'').slice(0,16), r=>r.total_eur, r=>`${r.facturas} fc.`);
  // Margen
  const mmax = Math.max(...(DATA.margen||[]).map(m=>Math.max(m.ingresos,m.gastos)), 1);
  $('#gastos-margen').innerHTML = (DATA.margen||[]).map(m => `
    <div style="margin-bottom:var(--s-3)">
      <div style="font-size:var(--fz-sm);color:var(--fg-3);margin-bottom:4px;display:flex;justify-content:space-between"><span>${m.mes}</span><span class="${m.margen>=0?'delta good':'delta bad'}" style="padding:1px 7px">Margen ${eur(m.margen)}</span></div>
      <div class="bar-row"><div class="bar-label" style="min-width:64px;font-size:var(--fz-sm)">Ingresos</div><div class="bar-track"><div class="bar-fill" style="width:${(m.ingresos/mmax*100).toFixed(1)}%;background:var(--green)">${eur(m.ingresos)}</div></div></div>
      <div class="bar-row" style="margin-top:4px"><div class="bar-label" style="min-width:64px;font-size:var(--fz-sm)">Gastos</div><div class="bar-track"><div class="bar-fill" style="width:${(m.gastos/mmax*100).toFixed(1)}%;background:var(--red)">${eur(m.gastos)}</div></div></div>
    </div>`).join('');
}

// ── v6: Gastos Detalle (tabla paginada + filtros) ──────────────────────
const GD = { page: 1, pageSize: 25, sort: 'invoice_date', order: 'desc', filters: {} };

async function renderGastosDetalle() {
  // Cargar vendors para el datalist (top 30)
  try {
    const prov = await getJSON('/api/gastos-por-proveedor?limit=30');
    const dl = $('#gd-vendors-list');
    if (dl) dl.innerHTML = prov.map(p => `<option value="${esc(p.proveedor)}">`).join('');
  } catch(e) {}
  // Cargar stats globales
  try {
    const stats = await getJSON('/api/gastos/stats');
    $('#gd-stat-n').textContent = stats.total_facturas;
    $('#gd-stat-total').textContent = eur(stats.total_eur);
    $('#gd-stat-ticket').textContent = eur(stats.ticket_medio);
    $('#gd-stat-vendors').textContent = stats.vendors_unicos;
    const pdfPct = Math.round(stats.ratio_pdf_disponible * 100);
    $('#gd-stat-pdf').textContent = `${stats.facturas_con_pdf} (${pdfPct}%)`;
  } catch(e) { /* noop */ }
  // Wire filtros
  $('#gd-apply').onclick = () => { GD.page = 1; loadGastos(); };
  $('#gd-clear').onclick = () => {
    ['gd-q','gd-from','gd-to','gd-vendor','gd-cat','gd-min','gd-max'].forEach(id => $('#'+id).value = '');
    $('#gd-cuenta').value = ''; $('#gd-status').value = '';
    GD.page = 1; GD.filters = {}; loadGastos();
    toast('Filtros limpiados', 'info');
  };
  $('#gd-prev').onclick = () => {
    if (GD.page > 1) { GD.page--; loadGastos(); }
  };
  $('#gd-next').onclick = () => {
    // v7.1: clamp cliente para no pedir paginas vacias
    const _maxPages = parseInt($('#gd-page-info').dataset.pages || '0', 10);
    if (_maxPages && GD.page >= _maxPages) return;
    GD.page++;
    loadGastos();
  };
  // Submit on Enter en cualquier input de filtro
  ['gd-q','gd-from','gd-to','gd-vendor','gd-cat','gd-min','gd-max'].forEach(id => {
    const el = $('#'+id);
    if (el) el.onkeydown = (e) => { if (e.key === 'Enter') { GD.page = 1; loadGastos(); } };
  });
  // Wire desglose
  const desgloseBtn = $('#gd-desglose-apply');
  if (desgloseBtn && !desgloseBtn._wired) {
    desgloseBtn._wired = true;
    desgloseBtn.onclick = renderDesgloseLegacy;
  }
  loadGastos();
  // Auto-cargar desglose inicial
  if (desgloseBtn) renderDesgloseLegacy();
}

async function refreshGastosDetalle() {
  // Re-carga sin resetear paginación (para refresh manual)
  loadGastos();
}

// ── v7: Desglose multidimensional ──────────────────────────────────────
async function renderDesgloseLegacy() {
  const wrap = $('#gd-desglose-results');
  if (!wrap) return;
  const dims = $('#gd-desglose-dims')?.value || 'category';
  const metric = $('#gd-desglose-metric')?.value || 'sum';
  const minEur = $('#gd-desglose-min')?.value;
  wrap.innerHTML = '<div class="muted">⏳ Calculando desglose…</div>';
  try {
    const p = new URLSearchParams();
    p.set('group_by', dims);
    p.set('metric', metric);
    if (minEur) p.set('min_eur', minEur);
    const data = await getJSON('/api/gastos/desglose?' + p.toString());
    if (!data.rows || data.rows.length === 0) {
      wrap.innerHTML = '<div class="muted">Sin datos para esta agrupación</div>';
      return;
    }
    // Renderizar como tabla con barra visual
    const maxVal = Math.max(...data.rows.map(r => Number(r.value) || 0));
    const dimLabels = { category:'Categoría', vendor:'Proveedor', month:'Mes', quarter:'Trimestre', cuenta:'Cuenta', source:'Origen', status:'Estado' };
    const cols = dims.split(',').map(d => ({ key: d, label: dimLabels[d.trim()] || d }));
    const metricLabel = { sum:'Suma €', count:'Nº', avg:'Media €', max:'Máx €' }[metric] || metric;
    const isMoney = metric === 'sum' || metric === 'avg' || metric === 'max';
    const formatVal = (v) => isMoney ? eur(v).replace('€','€') : new Intl.NumberFormat('es-ES').format(v);

    // Cabecera: una columna por cada dimensión + métricas
    const headCols = cols.map(c => `<th>${esc(c.label)}</th>`).join('') +
      `<th class="num">Nº</th><th class="num">${esc(metricLabel)}</th><th style="width:40%">Distribución</th>`;
    const rows = data.rows.map(r => {
      const dimCells = cols.map(c => {
        const v = r[c.key];
        return `<td>${v == null ? '<span class="muted">—</span>' : esc(String(v))}</td>`;
      }).join('');
      const v = Number(r.value) || 0;
      const pct = maxVal > 0 ? (v / maxVal * 100) : 0;
      const barColor = '#06B6D4';
      return `<tr>${dimCells}<td class="num">${(r.count||0).toLocaleString('es-ES')}</td><td class="num"><b>${formatVal(v)}</b></td><td><div class="gd-bar" style="background:linear-gradient(90deg, ${barColor} 0%, ${barColor} ${pct.toFixed(1)}%, transparent ${pct.toFixed(1)}%);height:18px;border-radius:3px"></div></td></tr>`;
    }).join('');
    wrap.innerHTML = `<div class="table-wrap"><table class="gd-desglose-table"><thead><tr>${headCols}</tr></thead><tbody>${rows}</tbody></table></div>`;
  } catch(e) {
    wrap.innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">' + esc(e.message) + '</div></div>';
    toast('Error en desglose: ' + e.message, 'error');
  }
}

function buildGastosParams() {
  const p = new URLSearchParams();
  p.set('page', GD.page);
  p.set('page_size', GD.pageSize);
  p.set('sort', GD.sort);
  p.set('order', GD.order);
  const q = $('#gd-q')?.value?.trim();
  if (q) p.set('q', q);
  const from = $('#gd-from')?.value;
  if (from) p.set('from', from);
  const to = $('#gd-to')?.value;
  if (to) p.set('to', to);
  const vendor = $('#gd-vendor')?.value?.trim();
  if (vendor) p.set('vendor', vendor);
  const cat = $('#gd-cat')?.value?.trim();
  if (cat) p.set('categoria', cat);
  const cuenta = $('#gd-cuenta')?.value;
  if (cuenta) p.set('cuenta', cuenta);
  const status = $('#gd-status')?.value;
  if (status) p.set('status', status);
  const min = $('#gd-min')?.value;
  if (min) p.set('min_eur', min);
  const max = $('#gd-max')?.value;
  if (max) p.set('max_eur', max);
  return p;
}

async function loadGastos() {
  const wrap = $('#gd-table-wrap');
  if (wrap) wrap.innerHTML = '<div class="skeleton-table" aria-hidden="true"><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div></div>';
  try {
    const qs = buildGastosParams();
    const data = await getJSON('/api/gastos?' + qs.toString());
    if (!data.rows || data.rows.length === 0) {
      wrap.innerHTML = emptyState('Sin resultados', 'No hay facturas que coincidan con los filtros aplicados. Prueba a limpiar o ampliar el rango de fechas.');
      $('#gd-result-count').textContent = '0 resultados';
      $('#gd-page-info').textContent = '—';
      $('#gd-prev').disabled = true; $('#gd-next').disabled = true;
      return;
    }
    const sortArrow = (col) => GD.sort === col ? (GD.order === 'desc' ? ' ↓' : ' ↑') : '';
    wrap.innerHTML = `<div class="table-wrap gd-table"><table>
      <thead><tr>
        <th class="sortable" data-sort="invoice_date">Fecha${sortArrow('invoice_date')}</th>
        <th>Nº Factura</th>
        <th class="sortable" data-sort="vendor_name">Vendor${sortArrow('vendor_name')}</th>
        <th>Categoría</th>
        <th>Cuenta</th>
        <th>Status</th>
        <th class="num sortable" data-sort="total_amount">Importe${sortArrow('total_amount')}</th>
        <th>PDF</th>
      </tr></thead>
      <tbody>${data.rows.map(r => `
        <tr class="row-drill" data-id="${r.id}" tabindex="0" role="button" aria-label="Ver detalle de ${esc(r.vendor_name||'')}">
          <td>${esc(r.invoice_date||'-')}</td>
          <td><code>${esc(r.invoice_number||'-')}</code></td>
          <td><b>${esc(r.vendor_name||'Sin nombre')}</b></td>
          <td>${r.category_raw ? `<span class="pill">${esc(r.category_raw)}</span>` : '<span class="muted">—</span>'}</td>
          <td>${r.source_account ? esc(r.source_account) : '<span class="muted">—</span>'}</td>
          <td><span class="status status-${esc(r.status||'pending')}">${esc(statusLabel(r.status||'pending'))}</span></td>
          <td class="num"><b>${eur(r.total_amount||0)}</b></td>
          <td>${r.raw_file_url ? '<span class="pdf-yes" title="PDF disponible">' + icon('paperclip', 'ico ico-xs') + '</span>' : '<span class="muted" title="Sin PDF">—</span>'}</td>
        </tr>
      `).join('')}</tbody>
    </table></div>`;
    // Click handler: abre modal de detalle
    $$('#gd-table-wrap tr.row-drill').forEach(tr => {
      tr.onclick = () => openFacturaModal(tr.getAttribute('data-id'));
      tr.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openFacturaModal(tr.getAttribute('data-id')); } };
    });
    // Sort headers
    $$('#gd-table-wrap th.sortable').forEach(th => {
      th.onclick = () => {
        const col = th.getAttribute('data-sort');
        if (GD.sort === col) GD.order = GD.order === 'desc' ? 'asc' : 'desc';
        else { GD.sort = col; GD.order = 'desc'; }
        loadGastos();
      };
    });
    // Paginación
    $('#gd-result-count').textContent = `${data.total.toLocaleString('es-ES')} resultados`;
    $('#gd-page-info').textContent = `Página ${data.page} de ${data.pages}`;
    $('#gd-prev').disabled = data.page <= 1;
    $('#gd-next').disabled = data.page >= data.pages;
  } catch(e) {
    wrap.innerHTML = '<div class="state error"><div class="title">Error cargando gastos</div><div class="desc">' + esc(e.message) + '</div></div>';
    toast('Error al cargar gastos: ' + e.message, 'error');
  }
}

// ── v7: Reclasificar (modal) ───────────────────────────────────────────
const CATEGORIES = [
  'Suministros','Restauración y Hostelería','Servicios Profesionales',
  'Marketing y Publicidad','Alquiler','Impuestos y Tasas','Gastos Bancarios',
  'Software y SaaS','Oficina','Otros','Seguros','Telecomunicaciones','Viajes y Transporte'
];

async function openFacturaModal(id) {
  openModal('facturaModal');
  $('#factura-body').innerHTML = '<div class="skeleton-card"></div>';
  $('#factura-title').textContent = 'Cargando factura…';
  try {
    const f = await getJSON('/api/gastos/' + id);
    $('#factura-title').textContent = f.vendor_name || 'Factura';
    const cat = f.category_name
      ? `<span class="pill" style="background:${esc(f.category_color||'#6b7280')};color:#fff">${esc(f.category_name)}</span>`
      : (f.category_raw ? `<span class="pill">${esc(f.category_raw)}</span>` : '<span class="muted">sin categoría</span>');
    const catOptions = CATEGORIES.map(c =>
      `<option value="${esc(c)}" ${(f.category_name===c||f.category_raw===c)?'selected':''}>${esc(c)}</option>`
    ).join('');
    const pdfBlock = f.raw_file_url
      ? (f.pdf_exists
          ? `<a class="btn primary" href="/api/gastos/${id}/pdf" target="_blank" rel="noopener" download>${icon('file-text', 'ico ico-xs')} Ver/Descargar PDF (${(f.pdf_size_bytes/1024).toFixed(1)} KB)</a>`
          : `<span class="muted">PDF no disponible en disco (${esc(f.raw_file_url)})</span>`)
      : '<span class="muted">Esta factura no tiene PDF adjunto</span>';
    const pagosBlock = f.pagos && f.pagos.length > 0
      ? `<h4>Pagos (${f.pagos.length})</h4><div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Importe</th><th>Source</th><th>Ref</th></tr></thead><tbody>${f.pagos.map(p => `<tr><td>${esc(p.payment_date||'-')}</td><td class="num">${eur(p.amount||0)}</td><td>${esc(p.source||'-')}</td><td><code>${esc(p.reference||'-')}</code></td></tr>`).join('')}</tbody></table></div>`
      : '';
    $('#factura-body').innerHTML = `
      <div class="factura-grid">
        <div><span class="factura-label">Nº factura</span><b><code>${esc(f.invoice_number||'-')}</code></b></div>
        <div><span class="factura-label">Fecha factura</span><b>${esc(f.invoice_date||'-')}</b></div>
        <div><span class="factura-label">Vencimiento</span><b>${esc(f.due_date||'-')}</b></div>
        <div><span class="factura-label">Status</span><span class="status status-${esc(f.status||'pending')}">${esc(statusLabel(f.status||'pending'))}</span></div>
        <div><span class="factura-label">Categoría</span>${cat}</div>
        <div><span class="factura-label">Cuenta</span><b>${esc(f.source_account||'-')}</b> <span class="muted">(${esc(f.source||'-')})</span></div>
        <div><span class="factura-label">Vendor tax ID</span><b>${esc(f.vendor_tax_id||'-')}</b></div>
        <div><span class="factura-label">Confianza parser</span><b>${f.confidence_score != null ? (Number(f.confidence_score)*100).toFixed(0)+'%' : '-'}</b></div>
      </div>
      <h4>Importes</h4>
      <div class="factura-importes">
        <div><span>Base</span><b>${eur(f.base_amount||0)}</b></div>
        <div><span>IVA</span><b>${eur(f.tax_amount||0)}</b></div>
        <div class="total"><span>Total</span><b>${eur(f.total_amount||0)} ${esc(f.currency||'EUR')}</b></div>
      </div>
      ${f.description ? `<h4>Descripción</h4><p class="factura-desc">${esc(f.description)}</p>` : ''}
      <h4>Documento</h4>
      <div class="factura-pdf">${pdfBlock}</div>
      ${pagosBlock}
      <div class="factura-meta">
        <small>ID: <code>${esc(f.id)}</code></small>
        ${f.verified_at ? `<small>Verificada: ${esc(f.verified_at)}</small>` : ''}
        ${f.created_at ? `<small>Creada: ${esc(f.created_at)}</small>` : ''}
      </div>
      <div class="factura-actions">
        <button class="btn ghost" onclick="chatPrefill('Analiza la factura ${esc(f.invoice_number||id)} de ${esc((f.vendor_name||'').replace(/'/g, ''))}')">${icon('message-circle', 'ico ico-xs')} Abrir en chat AI</button>
        <button class="btn ghost" id="reclass-toggle-${esc(id)}" onclick="toggleReclassPanel('${esc(id)}')">${icon('file-text', 'ico ico-xs')} Reclasificar</button>
      </div>
      <div class="reclass-panel" id="reclass-panel-${esc(id)}" style="display:none">
        <h4>Reclasificar factura</h4>
        <div class="reclass-form">
          <label class="gd-field"><span>Nueva categoría</span>
            <select id="reclass-cat-${esc(id)}">${catOptions}</select>
          </label>
          <label class="gd-field"><span>Motivo (auditoría)</span>
            <input type="text" id="reclass-reason-${esc(id)}" placeholder="ej. era marketing, no oficina">
          </label>
          <div class="reclass-buttons">
            <button class="btn primary" onclick="submitReclass('${esc(id)}')">Guardar reclasificación</button>
            <button class="btn ghost" onclick="toggleReclassPanel('${esc(id)}')">Cancelar</button>
          </div>
        </div>
      </div>
    `;
  } catch(e) {
    $('#factura-body').innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">' + esc(e.message) + '</div></div>';
  }
}

function chatPrefill(text) {
  if ($('#chatPanel').classList.contains('open') === false) {
    $('#chatFab').click();
  }
  setTimeout(() => {
    $('#chatText').value = text;
    $('#chatText').focus();
  }, 200);
}

// ── v7: Reclasificar (handlers) ────────────────────────────────────────
function toggleReclassPanel(id) {
  const p = $('#reclass-panel-' + id);
  if (p) p.style.display = (p.style.display === 'none' ? 'block' : 'none');
}

async function submitReclass(id) {
  const cat = $('#reclass-cat-' + id)?.value;
  const reason = $('#reclass-reason-' + id)?.value?.trim();
  if (!cat) { toast('Selecciona una categoría', 'error'); return; }
  if (!reason) { toast('El motivo es obligatorio (auditoría)', 'error'); return; }
  try {
    const r = await _fetchAuth('/api/gastos/' + id + '/reclasificar', {
      method: 'POST',
      json: { category_raw: cat, reason: reason }
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || r.statusText);
    }
    const data = await r.json();
    toast(`✓ Reclasificada a «${cat}»`, 'ok');
    toggleReclassPanel(id);
    // Refrescar modal con nuevos datos
    openFacturaModal(id);
  } catch(e) {
    toast('Error reclasificando: ' + e.message, 'error');
  }
}

// ── v6: Alertas (detector de anomalías) ─────────────────────────────────
let _alertasTimer = null;
async function renderAlertas() {
  if (_alertasTimer) return; // ya refrescándose
  await loadAlertas();
  // Auto-refresh cada 60s
  _alertasTimer = setInterval(loadAlertas, 60_000);
}

async function loadAlertas() {
  const list = $('#al-list');
  if (!list) return;
  try {
    const data = await getJSON('/api/alertas');
    $('#al-generated').textContent = data.generated_at.replace('T', ' ').replace('Z', ' UTC');
    // Resumen
    const r = data.resumen || {};
    const resumenParts = [];
    if (r.high) resumenParts.push(`<span class="al-pill al-pill-high">${r.high} alta${r.high>1?'s':''}</span>`);
    if (r.medium) resumenParts.push(`<span class="al-pill al-pill-medium">${r.medium} media${r.medium>1?'s':''}</span>`);
    if (r.low) resumenParts.push(`<span class="al-pill al-pill-low">${r.low} baja${r.low>1?'s':''}</span>`);
    if (r.info) resumenParts.push(`<span class="al-pill al-pill-info">${r.info} info</span>`);
    if (resumenParts.length === 0) resumenParts.push('<span class="al-pill al-pill-ok">✓ Todo OK</span>');
    $('#al-resumen').innerHTML = resumenParts.join('');
    // v7.1: botón "Marcar todas como revisadas" (visible solo si hay alertas HIGH/MED pendientes)
    const acks = await _loadAcks();
    const ackedIds = new Set(acks.map(a => a.alert_id));
    const pendingHigh = data.items.filter(a => a.severity === 'high' && !ackedIds.has(a.id)).length;
    const pendingMed = data.items.filter(a => a.severity === 'medium' && !ackedIds.has(a.id)).length;
    const badge = $('#nav-alert-badge');
    if (badge) {
      const total = pendingHigh + pendingMed;
      badge.textContent = total > 0 ? total : '';
      badge.style.display = total > 0 ? 'inline-block' : 'none';
    }
    // Botón bulk-ack
    const bulkBtn = $('#al-bulk-ack');
    if (bulkBtn) {
      const pendingItems = data.items.filter(a => (a.severity === 'high' || a.severity === 'medium') && !ackedIds.has(a.id));
      bulkBtn.style.display = pendingItems.length > 1 ? 'inline-flex' : 'none';
      bulkBtn.onclick = async () => {
        if (!confirm(`Marcar ${pendingItems.length} alertas como revisadas? (accion irreversible, persiste en servidor)`)) return;
        bulkBtn.disabled = true;
        let ok = 0, fail = 0;
        for (const a of pendingItems) {
          try { await _postJSON('/api/alertas/ack', {alert_id: a.id, note: 'bulk-ack'}); ok++; }
          catch(e) { fail++; }
        }
        toast(`✓ ${ok} alertas marcadas${fail ? `, ${fail} fallaron` : ''}`, fail ? 'warn' : 'success');
        _acksCache = null;  // invalidar cache
        await loadAlertas();
        bulkBtn.disabled = false;
      };
    }
    if (data.items.length === 0) {
      list.innerHTML = `<div class="al-empty"><div class="al-empty-icon">✅</div><h3>Sin alertas activas</h3><p>Todos los indicadores están dentro de los rangos esperados.</p></div>`;
      return;
    }
    const dismissed = JSON.parse(localStorage.getItem('liados_alerts_dismissed') || '{}');
    const now = Date.now();
    list.innerHTML = data.items.map(a => {
      const isAcked = ackedIds.has(a.id);
      const ackInfo = acks.find(x => x.alert_id === a.id);
      const isDismissed = dismissed[a.id] && (now - dismissed[a.id] < 24*3600*1000);
      const dismissBtn = (isAcked || isDismissed) ? '' : `<button class="al-dismiss" data-id="${esc(a.id)}" aria-label="Descartar alerta">'×'</button>`;
      const ackBtn = isAcked
        ? `<span class="al-acked" title="Revisada por ${esc(ackInfo?.acked_by || '')} el ${esc((ackInfo?.acked_at || '').replace('T',' ').slice(0,16))}">✓ Revisada</span>`
        : `<button class="al-ack" data-id="${esc(a.id)}">✓ Marcar revisada</button>`;
      const cta = a.cta
        ? (a.cta.prefill
            ? `<button class="al-cta" data-prefill="${esc(a.cta.prefill)}">${esc(a.cta.label||'Abrir en chat')} →</button>`
            : `<button class="al-cta" data-prefill="${esc(a.titulo)}">${esc(a.cta.label||'Abrir en chat')} →</button>`)
        : '';
      const cardClass = isAcked ? 'al-card al-acked al-' + esc(a.severity) : `al-card al-${esc(a.severity)} ${isDismissed?'al-dismissed':''}`;
      return `<article class="${cardClass}" role="alert" aria-label="Alerta ${a.severity}: ${esc(a.titulo)}">
        <div class="al-stripe"></div>
        <div class="al-body">
          <div class="al-head">
            <span class="al-sev al-sev-${esc(a.severity)}">${sevLabel(a.severity)}</span>
            <span class="al-tipo">${esc(tipoLabel(a.tipo))}</span>
            <h3>${esc(a.titulo)}</h3>
            ${dismissBtn}
          </div>
          <p class="al-desc">${esc(a.descripcion)}</p>
          ${a.accion_sugerida ? `<p class="al-accion">${icon('info', 'ico ico-xs')} <b>Acción:</b> ${esc(a.accion_sugerida)}</p>` : ''}
          ${isAcked && ackInfo?.note ? `<p class="al-note"><b>${icon('file-text', 'ico ico-xs')} Nota:</b> ${esc(ackInfo.note)}</p>` : ''}
          <div class="al-foot">
            ${cta}
            ${ackBtn}
            <span class="al-ts">Detectada: ${esc(data.generated_at.replace('T',' ').replace('Z',' UTC'))}</span>
          </div>
        </div>
      </article>`;
    }).join('');
    // Wire dismiss (ocultar 24h local)
    $$('.al-dismiss').forEach(b => b.onclick = () => {
      const id = b.getAttribute('data-id');
      const d = JSON.parse(localStorage.getItem('liados_alerts_dismissed') || '{}');
      d[id] = Date.now();
      localStorage.setItem('liados_alerts_dismissed', JSON.stringify(d));
      const card = b.closest('.al-card');
      if (card) { card.style.transition = 'opacity .3s, transform .3s'; card.style.opacity = '0'; card.style.transform = 'translateX(20px)'; setTimeout(() => card.remove(), 300); }
      toast('Alerta descartada (24h)', 'info');
    });
    // Wire "Marcar revisada" -> POST /api/alertas/ack
    $$('.al-ack').forEach(b => b.onclick = async () => {
      const id = b.getAttribute('data-id');
      const note = prompt('Nota opcional sobre esta alerta (ej: "verificado en Last.app"):', '');
      // prompt cancelado = null, no guardamos
      try {
        b.disabled = true;
        b.textContent = 'Guardando...';
        await _postJSON('/api/alertas/ack', {alert_id: id, note: note || ''});
        toast('✓ Alerta marcada como revisada (persiste en servidor)', 'success');
        await loadAlertas();  // re-render para mostrar el cambio
      } catch(e) {
        toast('Error al marcar: ' + e.message, 'error');
        b.disabled = false;
        b.textContent = '✓ Marcar revisada';
      }
    });
    // Wire CTA
    $$('.al-cta').forEach(b => b.onclick = () => chatPrefill(b.getAttribute('data-prefill')));
  } catch(e) {
    list.innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">' + esc(e.message) + '</div></div>';
  }
}

// Carga la lista de acks desde el backend (cache simple para evitar golpear en cada render)
let _acksCache = null;
let _acksCacheTime = 0;
async function _loadAcks() {
  const now = Date.now();
  if (_acksCache && (now - _acksCacheTime) < 30_000) return _acksCache;
  try {
    const data = await getJSON('/api/alertas/ack');
    _acksCache = data.acks || [];
    _acksCacheTime = now;
    return _acksCache;
  } catch(e) {
    return _acksCache || [];
  }
}

async function _postJSON(url, body) {
  const r = await _fetchAuth(url, {method: 'POST', json: body});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

const STATUS_LABELS = {
  'pending': 'Pendiente',
  'classified': 'Clasificada',
  'verified': 'Verificada',
  'paid': 'Pagada',
  'rejected': 'Rechazada',
  'duplicate': 'Duplicada',
};
function statusLabel(s) { return STATUS_LABELS[s] || s; }

const SEV_LABELS = {
  high: '🔴 ALTA',
  medium: '🟡 MEDIA',
  low: '🔵 BAJA',
  info: '⚪ INFO',
};
function sevLabel(s) { return SEV_LABELS[s] || s; }

// ── v6: Configuración (vista real) ──────────────────────────────────────
async function renderConfig() {
  // Cargar info del sistema
  try {
    const h = await getJSON('/api/health');
    $('#cfg-version').textContent = h.version;
    $('#cfg-db').innerHTML = h.checks?.database === 'ok' ? '<span class="status status-verified">OK</span>' : `<span class="status status-rejected">${esc(h.checks?.database||'?')}</span>`;
    const pool = h.checks?.pool || {};
    $('#cfg-pool').textContent = pool.used != null ? `${pool.used} usadas / ${pool.free} libres` : '—';
  } catch(e) {}
  // Cargar fuentes
  try {
    const data = await getJSON('/api/admin/gmail-status');
    const html = (data.accounts || []).map(a => {
      const statusBadge = {
        'OK': '<span class="status status-verified">OK</span>',
        'STALE': '<span class="status status-pending">Stale</span>',
        'MISSING_TOKEN': '<span class="status status-rejected">MISSING_TOKEN</span>',
        'PARSE_ERROR': '<span class="status status-rejected">Parse error</span>',
      }[a.status] || `<span class="status status-pending">${esc(a.status)}</span>`;
      const ageStr = a.age_days != null ? `${a.age_days}d` : '—';
      const clientStr = a.client_id || '—';
      return `<div class="cfg-fuente">
        <div class="cfg-fuente-head">
          <b>${icon('mail', 'ico ico-xs')} ${esc(a.account)}</b>
          ${statusBadge}
        </div>
        <div class="cfg-fuente-grid">
          <div><span>Credentials</span><b>${a.credentials_file_exists ? '✓' : '×'}</b></div>
          <div><span>Token</span><b>${a.token_file_exists ? '✓' : '×'}</b></div>
          <div><span>Refresh</span><b>${a.has_refresh_token ? '✓' : '×'}</b></div>
          <div><span>Edad token</span><b>${ageStr}</b></div>
          <div><span>Client ID</span><b><code>${esc(clientStr)}</code></b></div>
          <div><span>Scope</span><b><code>${esc(a.scope||'—')}</code></b></div>
        </div>
        ${a.status === 'MISSING_TOKEN' || a.status === 'STALE' ? `<details class="cfg-reauth"><summary>${icon('refresh-cw', 'ico ico-xs')} Reautorizar esta cuenta</summary>
          <ol>
            <li>En tu máquina local, ejecuta:<br><code>python3 -m agente.scripts.gmail_auth --account ${esc(a.account)} --force</code></li>
            <li>Sube el nuevo token al VPS:<br><code>scp agente/credentials/gmail_token_${esc(a.account)}.json vps:/root/liados/agente/credentials/</code></li>
            <li>Prueba el collector:<br><code>python3 -m agente.scripts.gmail_collector --account ${esc(a.account)} --dry-run</code></li>
          </ol>
          <p class="muted">${icon('alert-triangle', 'ico ico-xs')} El re-OAuth requiere navegador interactivo. No se puede automatizar desde el dashboard.</p>
        </details>` : ''}
      </div>`;
    }).join('');
    $('#cfg-fuentes').innerHTML = html || '<div class="state empty"><div class="title">Sin cuentas configuradas</div><div class="desc">Añade <code>GMAIL_ACCOUNTS=cuenta1,cuenta2</code> en tu <code>.env</code></div></div>';
  } catch(e) {
    $('#cfg-fuentes').innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc>' + esc(e.message) + '</div></div>';
  }
}

// ── v6: Toast notifications ─────────────────────────────────────────────
const _toastQueue = [];
function toast(msg, type='info', ms=3500) {
  const c = $('#toastContainer');
  if (!c) return;
  const t = document.createElement('div');
  t.className = `toast toast-${type}`;
  t.setAttribute('role', 'status');
  t.innerHTML = `<span class="toast-ico">${type==='error' ? icon('x', 'ico ico-xs') : type==='success' ? '✓' : type==='warn' ? icon('alert-triangle', 'ico ico-xs') : 'ℹ'}</span><span>${esc(msg)}</span><button class="toast-x" aria-label="Cerrar">×</button>`;
  c.appendChild(t);
  // Animate in
  requestAnimationFrame(() => t.classList.add('toast-in'));
  // Auto dismiss
  const close = () => {
    t.classList.remove('toast-in');
    t.classList.add('toast-out');
    setTimeout(() => t.remove(), 300);
  };
  t.querySelector('.toast-x').onclick = close;
  if (ms > 0) setTimeout(close, ms);
}

// ── v6: Command palette (⌘K) ────────────────────────────────────────────
const COMMANDS = [
  { id: 'nav:dashboard', label: 'Ir a Dashboard', icon: 'bar-chart-3', action: () => switchView('dashboard') },
  { id: 'nav:ventas', label: 'Ir a Ventas', icon: 'trending-up', action: () => switchView('ventas') },
  { id: 'nav:gastos', label: 'Ir a Gastos (resumen)', icon: 'file-text', action: () => switchView('gastos') },

  { id: 'nav:config', label: 'Ir a Configuración', icon: 'cog', action: () => switchView('config') },
  { id: 'act:chat', label: 'Abrir asistente AI', icon: 'message-circle', action: () => { if (!$('#chatPanel').classList.contains('open')) $('#chatFab').click(); $('#chatText').focus(); } },
  { id: 'act:refresh', label: 'Refrescar datos', icon: 'refresh-cw', action: () => { loadAll(); toast('Datos refrescados', 'success'); } },
  { id: 'act:export-facturas', label: 'Exportar facturas a CSV', icon: '⬇', action: () => window.location = '/api/export/facturas' },
  { id: 'act:export-proveedores', label: 'Exportar gastos por proveedor a CSV', icon: '⬇', action: () => window.location = '/api/export/proveedores' },
  { id: 'act:export-categorias', label: 'Exportar gastos por categoría a CSV', icon: '⬇', action: () => window.location = '/api/export/categorias' },
  { id: 'act:export-ingresos', label: 'Exportar ingresos a CSV', icon: '⬇', action: () => window.location = '/api/export/ingresos' },
  { id: 'act:theme', label: 'Cambiar tema claro/oscuro', icon: 'moon', action: () => toggleTheme() },
  { id: 'act:help', label: 'Ver atajos de teclado', icon: 'help-circle', action: () => openModal('helpModal') },
];
function switchView(v) {
  const nav = $(`.nav-item[data-view="${v}"]`);
  if (nav) nav.click();
}
function openPalette() {
  openModal('paletteModal');
  $('#paletteInput').value = '';
  renderPalette('');
  setTimeout(() => $('#paletteInput').focus(), 50);
}
function renderPalette(filter) {
  const f = (filter || '').toLowerCase().trim();
  const items = COMMANDS.filter(c => !f || c.label.toLowerCase().includes(f) || c.id.includes(f));
  $('#paletteResults').innerHTML = items.length === 0
    ? '<div class="palette-empty">Sin resultados</div>'
    : items.map(c => `<button class="palette-item" data-id="${c.id}"><span class="palette-ico">${c.icon}</span><span>${esc(c.label)}</span><kbd>↵</kbd></button>`).join('');
  $$('#paletteResults .palette-item').forEach(b => b.onclick = () => {
    const cmd = COMMANDS.find(c => c.id === b.getAttribute('data-id'));
    if (cmd) { closeModal('paletteModal'); cmd.action(); }
  });
  if (items[0]) $('.palette-item')?.focus();
}
function initPalette() {
  $('#paletteInput').oninput = (e) => renderPalette(e.target.value);
  $('#paletteInput').onkeydown = (e) => {
    if (e.key === 'Enter') { const first = $('#paletteResults .palette-item'); if (first) first.click(); }
    if (e.key === 'Escape') closeModal('paletteModal');
  };
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
// v6: tolerante a Chart.js no cargado (red/CDN falla). El dashboard sigue
// funcionando sin gráficos si Chart no está disponible.
function applyChartDefaults() {
  if (typeof Chart === 'undefined') return;
  try {
    Chart.defaults.font.family = "'Inter', sans-serif";
    Chart.defaults.font.size = 12;
  } catch(e) { /* noop */ }
}
applyChartDefaults();

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

// Tooltip custom HTML (Chart.js external tooltip).
// Crea y posiciona un div absolute sobre el canvas con el detalle del tooltip.
function externalTooltip() {
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
      return `<div style="display:flex;align-items:center;gap:6px;margin-top:4px"><span style="width:8px;height:8px;border-radius:2px;background:${color}"></span><span style="color:${c.fg2};flex:1">${esc(label)}</span><b style="font-family:var(--font-mono);color:${c.fg}">${eur(val)}</b></div>`;
    }).join('');
    const total = tooltip.dataPoints.reduce((s,p) => s + (p.raw||0), 0);
    const totalRow = tooltip.dataPoints.length > 1 ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border);display:flex;justify-content:space-between"><span style="color:${c.fg3}">Total</span><b style="font-family:var(--font-mono);color:${c.fg}">${eur(total)}</b></div>` : '';
    el.innerHTML = `<div style="font-weight:600;color:${c.fg};font-size:13px">${esc(title)}</div>${items}${totalRow}`;
    el.style.opacity = 1;
    el.style.left = tooltip.caretX + 'px';
    el.style.top = (tooltip.caretY - 8) + 'px';
  };
}

function applyChartTheme() {
  if (typeof Chart === 'undefined') return;
  try {
    const c = chartColors();
    Chart.defaults.color = c.ticks;
    Chart.defaults.borderColor = c.grid;
  } catch(e) { /* noop */ }
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
  const k = DATA.kpis, comp = DATA.comp;
  const margin = k.margen_mes;
  const margenPct = k.ventas_mes ? (margin / k.ventas_mes * 100) : 0;
  $('#financeSales').textContent = eur(k.ventas_mes);
  $('#financeExpenses').textContent = eur(k.gastos_mes);
  $('#heroValue').textContent = eur(margin);
  $('#heroValue').className = margin >= 0 ? 'finance-positive' : 'finance-negative';
  $('#financeSalesDelta').className = 'finance-delta ' + ((comp.ventas.delta_pct ?? 0) >= 0 ? 'good' : 'bad');
  $('#financeSalesDelta').textContent = comp.ventas.delta_pct == null ? 'Sin período anterior' : `${comp.ventas.delta_pct >= 0 ? '▲' : '▼'} ${Math.abs(comp.ventas.delta_pct).toFixed(1)}%`;
  $('#financeExpensesDelta').className = 'finance-delta ' + ((comp.gastos.delta_pct ?? 0) <= 0 ? 'good' : 'bad');
  $('#financeExpensesDelta').textContent = comp.gastos.delta_pct == null ? 'Sin período anterior' : `${comp.gastos.delta_pct >= 0 ? '▲' : '▼'} ${Math.abs(comp.gastos.delta_pct).toFixed(1)}%`;
  $('#heroDelta').className = 'finance-delta ' + (margin >= 0 ? 'good' : 'bad');
  $('#heroDelta').textContent = `${margenPct.toFixed(1)}% sobre ventas`;
  $('#heroMeta').innerHTML = `<span>${k.facturas_ventas} tickets procesados</span><span>${k.facturas_gastos} facturas de gasto</span>`;
}

function deltaInner(d) {
  if (d == null) return '— sin dato anterior';
  const arrow = d >= 0 ? '▲' : '▼';
  return `${arrow} ${Math.abs(d).toFixed(1)}% <span style="opacity:.7;font-weight:500">vs mes ant.</span>`;
}

function renderKpis() {
  const k = DATA.kpis, comp = DATA.comp;
  const cards = [
    { label:'Ventas netas', value:k.ventas_mes, color:'green', sub:`${k.facturas_ventas} tickets · mes actual`, delta:comp.ventas.delta_pct, deltaGood: v=>v>=0 },
    { label:'Gastos operativos', value:k.gastos_mes, color:'red', sub:`${k.facturas_gastos} facturas · mes actual`, delta:comp.gastos.delta_pct, deltaGood: v=>v<0 },
    { label:'Margen operativo', value:k.margen_mes, color:'blue', sub:'Ventas menos gastos', delta:comp.margen.delta_pct, deltaGood: v=>v>=0 },
    { label:'Tickets procesados', value:k.facturas_ventas, color:'yellow', sub:'Ventas contabilizadas', delta:null },
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
  // v7.1: usar createElement + textContent para evitar XSS via vendor/categoria
  const container = $(target);
  container.innerHTML = '';
  if (!rows || rows.length === 0) {
    container.innerHTML = emptyState('Sin datos este mes', 'Aún no se han registrado movimientos en el periodo actual.');
    return;
  }
  rows.forEach(r => {
    const color = colorFn(r);
    const row = document.createElement('div');
    row.className = 'bar-row';
    const label = document.createElement('div');
    label.className = 'bar-label';
    label.textContent = labelFn(r);  // SAFE: textContent no interpreta HTML
    const track = document.createElement('div');
    track.className = 'bar-track';
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    fill.style.width = (valueFn(r) / max * 100).toFixed(1) + '%';
    fill.style.background = color;
    fill.textContent = eur(valueFn(r));
    track.appendChild(fill);
    const extra = document.createElement('div');
    extra.className = 'bar-value';
    extra.textContent = extraFn(r);
    row.appendChild(label);
    row.appendChild(track);
    row.appendChild(extra);
    container.appendChild(row);
  });
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
  const mmax = Math.max(...((DATA.margen||[]).map(m=>Math.max(m.ingresos,m.gastos))), 1);
  $('#margen').innerHTML = (DATA.margen||[]).map(m => `
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

}

function ensureHomeDataBlocks() {
  if (DATA.proveedores?.length && !$('#proveedores')?.children.length) {
    renderBars('#proveedores', DATA.proveedores, r=>'#8b5cf6', r=>(r.proveedor||'').slice(0,18), r=>r.total_eur, r=>`${r.facturas} fc.`);
  }
  if (DATA.categorias?.length && !$('#categorias')?.children.length) {
    renderBars('#categorias', DATA.categorias, r=>r.color||'#6b7280', r=>(r.categoria||'').slice(0,15), r=>r.total_eur, r=>`${r.facturas} fc.`);
  }
}

function buildCanalFilter() {
  const sel = $('#canalFilter');
  const opts = ['all', ...Object.keys(LABELS)];
  sel.innerHTML = opts.map(o => `<option value="${o}">${o==='all'?'Todos los canales':ICONS[o]+' '+LABELS[o]}</option>`).join('');
  sel.value = canalFilter;
  sel.onchange = () => { canalFilter = sel.value; renderCharts(); };
}

// ── Carga principal ──────────────────────────────────────────────────────
async function loadAll(opts = {}) {
  const [kpis, comp, canalMes, canalMeses, margen, ingresos, proveedores, categorias, localesMes, dia, spark6m] = await Promise.all([
    getJSON('/api/kpis'), getJSON('/api/kpis-comparativa'),
    getJSON('/api/ventas-por-canal'), getJSON('/api/canal-por-mes'),
    getJSON('/api/margen-por-mes'), getJSON('/api/ingresos-por-mes'),
    getJSON('/api/gastos-por-proveedor'), getJSON('/api/gastos-por-categoria'),
    getJSON('/api/ventas-por-local'),
    getJSON('/api/ventas-por-dia?days=30'), getJSON('/api/ingresos-6m'),
  ]);
  DATA = { kpis, comp, canalMes, canalMeses, margen, ingresos, proveedores, categorias, localesMes, dia, spark6m };
  // Mostrar "última sync"
  $('#syncTime').textContent = 'hace unos segundos';
  renderHero();
  renderKpis();
  buildCanalFilter();
  renderCharts();
  renderRest();
  wireBarDrillDown();
  requestAnimationFrame(ensureHomeDataBlocks);
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
function renderHistory(){ $('#chatBody').innerHTML=''; if(chatHistory.length===0){$('#chatBody').innerHTML='<div class="msg bot">¡Hola! ' + icon('message-circle', 'ico ico-xs') + ' Soy el asistente de Liados. Pregúntame sobre ventas, gastos, productos o reservas.</div>';} else chatHistory.forEach(m=>addMsg(m.role==='user'?esc(m.content):mdToHtml(m.content), m.role==='user'?'user':'bot')); }

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
  let streamOk = false;       // true si el stream emitio al menos un evento util

  // v6.0.2: timeout duro. Si el stream no emite nada en 90s, fallback a /api/chat.
  const STREAM_TIMEOUT_MS = 90_000;
  let streamTimer = setTimeout(() => {
    if (!streamOk) {
      console.warn('[chat] stream timeout, fallback a /api/chat');
      if (typing.parentNode) typing.remove();
      // Fallback no-stream
      _fallbackNonStream(msg);
    }
  }, STREAM_TIMEOUT_MS);

  try {
    const r = await _fetchAuth('/api/chat/stream', { method:'POST', json:{message:msg, history:chatHistory} });
    if (!r.ok) {
      clearTimeout(streamTimer);
      // Si el stream rechaza con 429 (rate limit) o 5xx, fallback al no-stream
      console.warn('[chat] stream fallo HTTP', r.status, '- fallback');
      if (typing.parentNode) typing.remove();
      return _fallbackNonStream(msg);
    }
    if (!r.body || !r.body.getReader) {
      clearTimeout(streamTimer);
      console.warn('[chat] body sin getReader, fallback');
      if (typing.parentNode) typing.remove();
      return _fallbackNonStream(msg);
    }
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
        let payload = {};
        try { payload = data ? JSON.parse(data) : {}; } catch(e) {
          // JSON parcial por corte de buffer: ignorar y seguir (evento siguiente lo traera completo)
          console.warn('[chat] JSON.parse fallo:', data?.substring(0, 80));
          continue;
        }
        streamOk = true;
        clearTimeout(streamTimer);  // ya tenemos datos, desactivamos timeout

        if (type === 'tool') {
          if (typing.parentNode) typing.remove();
          toolsUsed.push(payload.name);
          // Crear/actualizar chips de tools en la burbuja bot (si ya existe) o en una provisional
          if (!toolsChip) { toolsChip = document.createElement('div'); toolsChip.className='msg bot'; toolsChip.style.background='transparent'; toolsChip.style.border='none'; toolsChip.style.padding='0'; toolsChip.style.alignSelf='flex-start'; toolsChip.innerHTML='<div class="tools" style="border:none;padding:0;margin:0"></div>'; $('#chatBody').appendChild(toolsChip); }
          toolsChip.querySelector('.tools').innerHTML += `<span class="tchip">${icon('wrench', 'ico ico-xs')} ${esc(payload.name)}</span>`;
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
            const chips = `<div class="tools">${toolsUsed.map(t=>`<span class="tchip">${icon('wrench', 'ico ico-xs')} ${esc(t)}</span>`).join('')}</div>`;
            if (botMsg) botMsg.innerHTML = mdToHtml(fullReply) + chips;
            if (toolsChip) toolsChip.remove();
          }
          chatHistory = [...chatHistory, {role:'user',content:msg}, {role:'assistant',content:fullReply}].slice(-20);
          saveHist();
          if (pending && pending.token) { pendingToken = pending.token; showConfirm(pending); }
        } else if (type === 'error') {
          if (typing.parentNode) typing.remove();
          if (toolsChip) toolsChip.remove();
          addMsg(icon('alert-triangle', 'ico ico-xs') + ' ' + (payload.message||'Error del agente'), 'error')
          return;
        }
      }
    }
    // Si no llegó evento done (caída de conexión tras tokens)
    if (!streamOk) {
      if (typing.parentNode) typing.remove();
      addMsg('Sin respuesta del stream.','error');
    } else if (!botMsg && fullReply === '') {
      if (typing.parentNode) typing.remove();
      addMsg('Stream cerrado sin respuesta.','error');
    }
  } catch(e) {
    clearTimeout(streamTimer);
    console.error('[chat] sendMsg error:', e);
    if (typing.parentNode) typing.remove();
    if (toolsChip) toolsChip.remove();
    addMsg('Error de conexión: '+e.message+'. Probando fallback...','error');
    // Fallback silencioso al endpoint no-stream
    _fallbackNonStream(msg);
  } finally {
    clearTimeout(streamTimer);
    $('#chatSend').disabled=false; $('#chatText').focus();
  }
}

// v6.0.2: Fallback al endpoint no-stream cuando el stream falla o se agota el timeout.
async function _fallbackNonStream(originalMsg) {
  try {
    addMsg(icon('refresh-cw', 'ico ico-xs') + ' Conectando con modo alternativo...', 'bot');
    const r = await _fetchAuth('/api/chat', { method:'POST', json:{message: originalMsg, history: chatHistory} });
    if (!r.ok) {
      addMsg('❌ Error HTTP '+r.status+' (rate limit o servidor caído). Espera unos segundos.', 'error');
      return;
    }
    const d = await r.json();
    if (d.reply) {
      addMsg(mdToHtml(d.reply), 'bot');
      chatHistory = [...chatHistory, {role:'user',content:originalMsg}, {role:'assistant',content:d.reply}].slice(-20);
      saveHist();
      if (d.pending_confirmation && d.pending_confirmation.token) {
        pendingToken = d.pending_confirmation.token;
        showConfirm(d.pending_confirmation);
      }
    } else {
      addMsg('❌ Respuesta vacía del servidor.', 'error');
    }
  } catch(e) {
    console.error('[chat] fallback error:', e);
    addMsg('❌ Error en fallback: '+e.message, 'error');
  } finally {
    $('#chatSend').disabled=false; $('#chatText').focus();
  }
}

function showConfirm(p){
  const box=document.createElement('div'); box.className='confirm-box';
  box.innerHTML=`<div><b>${icon('alert-triangle', 'ico ico-xs')} ${esc(p.action)}</b><br>${esc(p.message||'Esta acción requiere confirmación.')}</div><div class="btns"><button class="yes">Confirmar</button><button class="no">Cancelar</button></div>`;
  $('#chatBody').appendChild(box); box.scrollIntoView();
  box.querySelector('.yes').onclick=async()=>{box.innerHTML='Ejecutando…';try{const r=await _fetchAuth('/api/chat/confirm',{method:'POST',json:{confirmation_token:pendingToken}});const d=await r.json().catch(()=>({error:'Respuesta no es JSON valido'}));box.remove();addMsg('```json\n'+JSON.stringify(d,null,2)+'\n```','bot');pendingToken=null;}catch(e){box.remove();addMsg('Error al confirmar: '+esc(e.message),'error');pendingToken=null;}};
  box.querySelector('.no').onclick=async()=>{try{await _fetchAuth('/api/chat/cancel',{method:'POST',json:{confirmation_token:pendingToken}});box.remove();addMsg('Acción cancelada.','bot');}catch(e){box.remove();addMsg('No se pudo cancelar (la acción puede seguir pendiente en el servidor): '+esc(e.message),'error');}pendingToken=null;};
}

// ── Reloj ────────────────────────────────────────────────────────────────
const TIPO_LABELS = {
  venta_caida: 'Caída de ventas',
  canal_ausente: 'Canal sin actividad',
  gasto_pico: 'Pico de gasto',
  factura_sin_categoria: 'Sin categorizar',
  sync_stale: 'Sync obsoleto',
  facturas_sin_pdf: 'Sin PDF',
  locales_huerfanos: 'Sin local',
  duplicado_potencial: 'Posible duplicado',
  ticket_anomalo: 'Ticket anómalo',
};
function tipoLabel(t) { return TIPO_LABELS[t] || t; }

function tick(){ const d=new Date(); $('#clock').textContent=d.toLocaleString('es-ES',{weekday:'short',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Madrid'}); }

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
      html += data.proveedores.map(p => {
        const safeName = esc(p.proveedor);
        // data-name en setAttribute para evitar inyeccion de comillas
        return `<div class="search-item" data-drill="proveedor"><div class="si-main"><div class="si-name">${highlight(p.proveedor,q)}</div><div class="si-sub">${p.facturas} facturas</div></div><div class="si-amount">${eur(p.total_eur)}</div></div>`;
      }).join('');
      html += '</div>';
    }
    if (data.facturas.length) {
      html += '<div class="search-group"><div class="sg-title">Facturas</div>';
      html += data.facturas.map(f => {
        const safeName = esc(f.vendor_name||'');
        return `<div class="search-item" data-drill="proveedor"><div class="si-main"><div class="si-name">${highlight(f.vendor_name||'Sin nombre',q)} ${f.invoice_number?'· '+esc(f.invoice_number):''}</div><div class="si-sub">${f.invoice_date||''} · ${esc(f.category_raw||'')}</div></div><div class="si-amount">${eur(f.total_amount)}</div></div>`;
      }).join('');
      html += '</div>';
    }
    if (!html) html = '<div class="search-empty">Sin resultados para "'+esc(q)+'"</div>';
    $('#searchResults').innerHTML = html;
    // Wire click -> drill-down (data-name en setAttribute, no en atributo)
    $$('#searchResults .search-item').forEach((item, i) => {
      const allItems = [...data.proveedores, ...data.facturas];
      const name = allItems[i]?.proveedor || allItems[i]?.vendor_name || '';
      if (name) {
        item.setAttribute('data-drill-name', name);
        item.onclick = () => { closeAllModals(); openDrill('proveedor', name); };
      }
    });
  } catch(e) { $('#searchResults').innerHTML = '<div class="search-empty">Error: '+esc(e.message)+'</div>'; }
}

async function openDrill(type, name) {
  name = (name || '').trim();
  if (!name) return;
  openModal('drillModal');
  $('#drillTitle').textContent = (type==='proveedor' ? icon('receipt', 'ico ico-xs') + ' ' : icon('package', 'ico ico-xs') + ' ') + name;
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
  let pendingG = false;
  let pendingGTimer = null;
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea';
    // ⌘K / Ctrl+K: command palette (funciona siempre, incluso en inputs)
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); return; }
    // Esc cierra todo
    if (e.key === 'Escape') { closeAllModals(); $('#chatPanel').classList.remove('open'); return; }
    // En inputs: solo Esc y ⌘K (ya gestionados arriba)
    if (typing) return;
    // G + <letra>: navegación estilo Gmail
    if (pendingG) {
      pendingG = false;
      clearTimeout(pendingGTimer);
      const k = e.key.toLowerCase();
      const map = { d:'dashboard', v:'ventas', g:'gastos', b:'desglose', c:'config' };
      if (map[k]) { e.preventDefault(); switchView(map[k]); return; }
    }
    if (e.key.toLowerCase() === 'g') {
      pendingG = true;
      pendingGTimer = setTimeout(() => { pendingG = false; }, 1200);
      return;
    }
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
  initPalette();
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

  loadAll().catch(e => {
    $$('.card-body, .kpis, .hero').forEach(el => { el.style.opacity=1; });
    $('#kpis').innerHTML = `<div class="state error" style="grid-column:1/-1"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg><div class="title">Error cargando datos</div><div class="desc">${esc(e.message)}</div><button class="seg" onclick="location.reload()">Reintentar</button></div>`;
  });

  // v7.1 PRO: auto-refresh honesto cada 5 min (en vez del fake "+1 min")
  let _lastLoadAt = Date.now();
  setInterval(async () => {
    try {
      await loadAll({silent: true});
      _lastLoadAt = Date.now();
      $('#syncTime').textContent = 'ahora';
    } catch(e) {
      console.warn('[auto-refresh] fallo:', e.message);
      $('#syncTime').textContent = 'actualización fallida';
      $('.live-dot').style.background = '#ef4444';  // rojo = degradado
    }
  }, 5 * 60 * 1000);

  // Update "sync" label cada 30s (timestamp honesto)
  setInterval(() => {
    const secs = Math.floor((Date.now() - _lastLoadAt) / 1000);
    if (secs < 5) $('#syncTime').textContent = 'ahora';
    else if (secs < 60) $('#syncTime').textContent = `hace ${secs}s`;
    else if (secs < 3600) $('#syncTime').textContent = `hace ${Math.floor(secs/60)} min`;
    else $('#syncTime').textContent = `hace ${Math.floor(secs/3600)} h`;
  }, 30000);
}

// v7.1 PRO: carga SOLO el badge (resumen de alertas), no la lista completa.
// Asi el sidebar badge aparece desde el primer load, sin esperar a abrir la vista.
async function loadAlertBadge() {
  try {
    const data = await getJSON('/api/alertas');
    const acks = await _loadAcks();
    const ackedIds = new Set(acks.map(a => a.alert_id));
    const pendingHigh = data.items.filter(a => a.severity === 'high' && !ackedIds.has(a.id)).length;
    const pendingMed = data.items.filter(a => a.severity === 'medium' && !ackedIds.has(a.id)).length;
    const total = pendingHigh + pendingMed;
    const badge = $('#nav-alert-badge');
    if (badge) {
      badge.textContent = total > 0 ? total : '';
      badge.style.display = total > 0 ? 'inline-block' : 'none';
    }
  } catch(e) {
    // Silencioso: el badge se carga al abrir la vista.
  }
}

// Inicializacion robusta: si el DOM ya esta listo (script cargado tarde,
// async, cache HIT antes del parse), ejecutar init directamente.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  // DOM ya listo, ejecutar inmediatamente
  init();
}


// ── v8.0 PRO: Desglose Excel-style ──────────────────────────────────

const DG = {
  // La entrada principal replica directamente el libro de los vídeos.
  activeTab: 'pyg',
  filters: {},
  _tabs: null,
};

async function renderDesglose() {
  DG._tabs = DG._tabs || $$('.excel-tab');
  // default fechas: últimos 12 meses
  const today = new Date();
  const yyyymm = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`;
  const fromInput = $('#dg-from');
  const toInput = $('#dg-to');
  if (fromInput && !fromInput.value) {
    const d = new Date(today); d.setFullYear(d.getFullYear() - 1);
    fromInput.value = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`;
  }
  if (toInput && !toInput.value) toInput.value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  if ($('#cal-year') && !$('#cal-year').value) $('#cal-year').value = today.getFullYear();

  // Tab clicks
  DG._tabs.forEach(tab => {
    if (tab._wired) return;
    tab._wired = true;
    tab.onclick = () => switchDesgloseTab(tab.getAttribute('data-tab'));
  });

  // Botón aplicar (filtros globales)
  const applyBtn = $('#dg-apply');
  if (applyBtn && !applyBtn._wired) {
    applyBtn._wired = true;
    applyBtn.onclick = () => {
      DG.filters = {
        date_from: $('#dg-from')?.value || '',
        date_to: $('#dg-to')?.value || '',
        cuenta: $('#dg-cuenta')?.value || '',
      };
      // recargar pestaña activa
      loadDesgloseTab(DG.activeTab);
      toast('Filtros aplicados', 'success');
    };
  }

  // Botón export CSV
  const exportBtn = $('#desglose-export-btn');
  if (exportBtn && !exportBtn._wired) {
    exportBtn._wired = true;
    exportBtn.onclick = () => exportDesgloseCsv();
  }

  // Botones pestañas específicas (matrix, top, calendar, compare)
  wireMatrixControls();
  wireTopControls();
  wireCalendarControls();
  wireCompareControls();

  // Abrir directamente el libro financiero; el resto queda disponible
  // como herramientas auxiliares en las pestañas superiores.
  switchDesgloseTab(DG.activeTab);
}

function switchDesgloseTab(tabName) {
  DG.activeTab = tabName;
  document.body.classList.toggle('cr-workbook-active', tabName === 'pyg');
  DG._tabs.forEach(t => t.classList.toggle('active', t.getAttribute('data-tab') === tabName));
  $$('.excel-panel').forEach(p => p.classList.toggle('active', p.getAttribute('data-tab-panel') === tabName));
  loadDesgloseTab(tabName);
}

async function loadDesgloseTab(tabName) {
  switch (tabName) {
    case 'resumen': await loadDesgloseResumen(); break;
    case 'analisis': await loadDesgloseMatrix(); break;
    case 'top': await loadDesgloseTop(); break;
    case 'calendario': await loadDesgloseCalendar(); break;
    case 'comparar': await loadDesgloseCompare(); break;
    case 'pyg': await loadCuentaResultados(); break;
  }
  // mostrar timestamp de generación
  const el = $('#dg-gen-at');
  if (el) el.textContent = `Última actualización: ${new Date().toLocaleString('es-ES')}`;
}

async function loadDesgloseResumen() {
  const grid = $('#resumen-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="skeleton-card"></div>'.repeat(6);
  try {
    const params = new URLSearchParams();
    Object.entries(DG.filters).forEach(([k,v]) => v && params.set(k, v));
    const d = await getJSON('/api/gastos/desglose/resumen?' + params.toString());

    const fmt = (n) => Number(n||0).toLocaleString('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const fmt0 = (n) => Number(n||0).toLocaleString('es-ES', {maximumFractionDigits: 0});

    grid.innerHTML = `
      <div class="resumen-card accent">
        <div class="resumen-label">Total facturas</div>
        <div class="resumen-value">${fmt0(d.total_facturas)}</div>
        <div class="resumen-meta">${fmt(d.n_vendors)} vendors · ${fmt0(d.n_categories)} categorías</div>
      </div>
      <div class="resumen-card">
        <div class="resumen-label">Importe total</div>
        <div class="resumen-value">${fmt(d.total_eur)}€</div>
        <div class="resumen-meta">ticket medio ${fmt(d.ticket_medio_eur)}€</div>
      </div>
      <div class="resumen-card success">
        <div class="resumen-label">Mes actual</div>
        <div class="resumen-value">${fmt(d.eur_mes_actual)}€</div>
        <div class="resumen-meta">${fmt0(d.facturas_mes_actual)} facturas este mes</div>
      </div>
      <div class="resumen-card warn">
        <div class="resumen-label">Importe máximo</div>
        <div class="resumen-value">${fmt(d.maximo_eur)}€</div>
        <div class="resumen-meta">mínimo: ${fmt(d.minimo_eur)}€</div>
      </div>
      <div class="resumen-card">
        <div class="resumen-label">Top categoría</div>
        <div class="resumen-value" style="font-size: var(--fz-lg)">${esc(d.top_category || '—')}</div>
        <div class="resumen-meta">${fmt(d.top_category_eur)}€</div>
      </div>
      <div class="resumen-card">
        <div class="resumen-label">Top proveedor</div>
        <div class="resumen-value" style="font-size: var(--fz-lg)">${esc(d.top_vendor || '—')}</div>
        <div class="resumen-meta">${fmt(d.top_vendor_eur)}€</div>
      </div>
    `;
  } catch(e) {
    grid.innerHTML = '<div class="state error"><div class="title">Error cargando resumen</div><div class="desc">' + esc(e.message) + '</div></div>';
  }
}

function wireMatrixControls() {
  const btn = $('#mtx-apply');
  if (!btn || btn._wired) return;
  btn._wired = true;
  btn.onclick = loadDesgloseMatrix;
}

async function loadDesgloseMatrix() {
  const wrap = $('#mtx-results');
  if (!wrap) return;
  wrap.innerHTML = '<div class="skeleton-table"><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div></div>';
  try {
    const params = new URLSearchParams();
    params.set('rows', $('#mtx-rows')?.value || 'month');
    params.set('cols', $('#mtx-cols')?.value || 'category');
    params.set('metric', $('#mtx-metric')?.value || 'sum');
    Object.entries(DG.filters).forEach(([k,v]) => v && params.set(k, v));
    const d = await getJSON('/api/gastos/desglose/matrix?' + params.toString());

    if (!d.cells || d.cells.length === 0) {
      wrap.innerHTML = '<div class="excel-empty"><div class="ico">' + icon('mail', 'ico ico-xs') + '</div><h3>Sin datos</h3><p>No hay facturas que coincidan con los filtros actuales.</p></div>';
      return;
    }

    // Construir tabla cruzada tipo Excel
    const rows = [...new Set(d.cells.map(c => c.row))].sort();
    const cols = [...new Set(d.cells.map(c => c.col))].sort();
    const cellMap = {};
    let maxValue = 0;
    d.cells.forEach(c => {
      cellMap[`${c.row}|${c.col}`] = c;
      if (c.value > maxValue) maxValue = c.value;
    });

    const fmt = (n) => Number(n||0).toLocaleString('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const fmt0 = (n) => Number(n||0).toLocaleString('es-ES', {maximumFractionDigits: 0});
    const intensityClass = (v) => {
      if (!v || maxValue === 0) return 'mtx-cell-zero';
      const r = v / maxValue;
      if (r < 0.2) return 'mtx-cell-1';
      if (r < 0.4) return 'mtx-cell-2';
      if (r < 0.6) return 'mtx-cell-3';
      if (r < 0.8) return 'mtx-cell-4';
      return 'mtx-cell-5';
    };

    let html = '<div style="overflow:auto;max-height:60vh"><table class="mtx-table"><thead><tr>';
    html += '<th class="row-label">' + esc(d.row_dim) + ' ↓ \\ ' + esc(d.col_dim) + ' →</th>';
    cols.forEach(c => { html += `<th class="num col-label">${esc(c)}</th>`; });
    html += '<th class="num total">Total fila</th></tr></thead><tbody>';

    rows.forEach(r => {
      html += `<tr><td class="row-label">${esc(r)}</td>`;
      let rowTotal = 0;
      cols.forEach(c => {
        const cell = cellMap[`${r}|${c}`];
        if (cell) {
          rowTotal += cell.value;
          html += `<td class="num mtx-cell ${intensityClass(cell.value)}" title="${esc(r)} × ${esc(c)}: ${fmt(cell.value)}€ (${cell.count} fac)">${d.metric === 'count' ? fmt0(cell.value) : fmt(cell.value)}</td>`;
        } else {
          html += '<td class="num mtx-cell-zero">·</td>';
        }
      });
      const rowTotalCell = d.row_totals[r] || rowTotal;
      html += `<td class="num total">${fmt(rowTotalCell)}</td>`;
      html += '</tr>';
    });

    // Total row
    html += '<tr class="total"><td class="row-label">Total</td>';
    cols.forEach(c => {
      html += `<td class="num total">${fmt(d.col_totals[c] || 0)}</td>`;
    });
    html += `<td class="num total">${fmt(d.grand_total)}</td></tr>`;
    html += '</tbody></table></div>';

    html += `<div style="margin-top:var(--s-3);font-size:var(--fz-xs);color:var(--fg-3)">${d.n_cells} celdas · Gran total: <b>${fmt(d.grand_total)}€</b> · métrica: ${esc(d.metric)}</div>`;

    wrap.innerHTML = html;
  } catch(e) {
    wrap.innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">' + esc(e.message) + '</div></div>';
  }
}

function wireTopControls() {
  const btn = $('#top-apply');
  if (!btn || btn._wired) return;
  btn._wired = true;
  btn.onclick = loadDesgloseTop;
}

async function loadDesgloseTop() {
  const wrap = $('#top-results');
  if (!wrap) return;
  wrap.innerHTML = '<div class="skeleton-card"></div>'.repeat(5);
  try {
    const params = new URLSearchParams();
    params.set('by', $('#top-by')?.value || 'vendor');
    params.set('metric', $('#top-metric')?.value || 'sum');
    params.set('limit', $('#top-limit')?.value || '20');
    if ($('#top-sparkline')?.checked) params.set('with_sparkline', 'true');
    Object.entries(DG.filters).forEach(([k,v]) => v && params.set(k, v));
    const d = await getJSON('/api/gastos/desglose/top?' + params.toString());

    if (!d.items || d.items.length === 0) {
      wrap.innerHTML = '<div class="excel-empty"><div class="ico">' + icon('trophy', 'ico ico-xs') + '</div><h3>Sin datos</h3></div>';
      return;
    }

    const fmt = (n) => Number(n||0).toLocaleString('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const maxValue = Math.max(...d.items.map(i => i.value), 1);
    const showSparkline = $('#top-sparkline')?.checked;

    wrap.innerHTML = '<div class="top-list">' + d.items.map((it, idx) => {
      const rank = idx + 1;
      const rankClass = rank <= 3 ? `top-${rank}` : '';
      const barWidth = (it.value / maxValue * 100).toFixed(1);
      const sparkSvg = (showSparkline && it.sparkline_6m && it.sparkline_6m.length > 0) ? renderSparkline(it.sparkline_6m) : '';
      return `
        <div class="top-row">
          <div class="top-rank ${rankClass}">#${rank}</div>
          <div class="top-name">${esc(it.dim)}</div>
          <div class="top-bar"><div class="top-bar-fill" style="width:${barWidth}%"></div></div>
          <div class="top-value">${fmt(it.value)}€</div>
          <div class="top-count">${it.count} fac</div>
          ${sparkSvg ? `<div class="top-spark">${sparkSvg}</div>` : ''}
        </div>
      `;
    }).join('') + '</div>';
  } catch(e) {
    wrap.innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">' + esc(e.message) + '</div></div>';
  }
}

function renderSparkline(data) {
  // data = [{month: 'YYYY-MM', eur: number}]
  if (!data || data.length === 0) return '';
  const w = 110, h = 24;
  const max = Math.max(...data.map(d => d.eur), 1);
  const min = Math.min(...data.map(d => d.eur), 0);
  const range = max - min || 1;
  const stepX = w / Math.max(data.length - 1, 1);
  const points = data.map((d, i) => {
    const x = i * stepX;
    const y = h - ((d.eur - min) / range * (h - 4)) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const lastPoint = data[data.length - 1];
  const lastX = (data.length - 1) * stepX;
  const lastY = h - ((lastPoint.eur - min) / range * (h - 4)) - 2;
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="vertical-align:middle">
    <polyline points="${points}" fill="none" stroke="var(--accent,#3b82f6)" stroke-width="1.5" />
    <circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="2.5" fill="var(--accent,#3b82f6)" />
  </svg>`;
}

function wireCalendarControls() {
  const btn = $('#cal-apply');
  if (!btn || btn._wired) return;
  btn._wired = true;
  btn.onclick = loadDesgloseCalendar;
}

async function loadDesgloseCalendar() {
  const wrap = $('#cal-results');
  if (!wrap) return;
  wrap.innerHTML = '<div class="skeleton-card"></div>';
  try {
    const year = $('#cal-year')?.value || new Date().getFullYear();
    const d = await getJSON(`/api/gastos/desglose/calendar?year=${year}`);
    const fmt = (n) => Number(n||0).toLocaleString('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const grid = d.grid || {};
    const allValues = Object.values(grid).flatMap(m => Object.values(m).map(c => c.eur || 0)).filter(v => v > 0);
    const maxVal = Math.max(...allValues, 1);

    const intensityLevel = (v) => {
      if (!v || v <= 0) return 0;
      const r = v / maxVal;
      if (r < 0.1) return 1;
      if (r < 0.25) return 2;
      if (r < 0.5) return 3;
      if (r < 0.8) return 4;
      return 5;
    };

    const months = ['01','02','03','04','05','06','07','08','09','10','11','12'];
    const monthNames = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
    const daysInMonth = (m, y) => new Date(y, parseInt(m), 0).getDate();

    let html = `<div class="cal-summary">
      <div><div class="cal-stat-label">Año</div><div class="cal-stat-value">${year}</div></div>
      <div><div class="cal-stat-label">Total facturas</div><div class="cal-stat-value">${d.total_count || 0}</div></div>
      <div><div class="cal-stat-label">Total €</div><div class="cal-stat-value">${fmt(d.total_eur)}€</div></div>
      <div><div class="cal-stat-label">Día pico</div><div class="cal-stat-value">${fmt(maxVal)}€</div></div>
      <div><div class="cal-stat-label">Celdas censuradas (n<3)</div><div class="cal-stat-value">${d.censored_cells || 0}</div></div>
    </div>`;

    html += '<div class="cal-grid">';
    // Header
    html += '<div class="cal-cell cal-header"></div>';
    for (let d = 1; d <= 31; d++) html += `<div class="cal-cell cal-header">${d}</div>`;
    // Meses
    months.forEach((m, mi) => {
      html += `<div class="cal-cell cal-row">${monthNames[mi]}</div>`;
      const daysM = daysInMonth(m, year);
      for (let d = 1; d <= 31; d++) {
        if (d > daysM) {
          html += '<div class="cal-cell cal-day-empty"></div>';
        } else {
          const cell = grid[m]?.[String(d).padStart(2, '0')];
          if (!cell) {
            html += '<div class="cal-cell cal-data" style="opacity:.2"></div>';
          } else if (cell.censored) {
            html += `<div class="cal-cell cal-data cal-censored" title="${d}/${m}/${year}: ${cell.count} fac (censurado)">n=${cell.count}</div>`;
          } else {
            const lvl = intensityLevel(cell.eur);
            const display = cell.eur > 1000 ? Math.round(cell.eur / 100) / 10 + 'k' : Math.round(cell.eur);
            html += `<div class="cal-cell cal-data cal-level-${lvl}" title="${d}/${m}/${year}: ${fmt(cell.eur)}€ (${cell.count} fac)">${display}</div>`;
          }
        }
      }
    });
    html += '</div>';
    wrap.innerHTML = html;
  } catch(e) {
    wrap.innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">' + esc(e.message) + '</div></div>';
  }
}

function wireCompareControls() {
  const btn = $('#cmp-apply');
  if (!btn || btn._wired) return;
  btn._wired = true;
  btn.onclick = loadDesgloseCompare;
  // Presets
  $$('[data-cmp-preset]').forEach(b => {
    if (b._wired) return;
    b._wired = true;
    b.onclick = () => applyComparePreset(b.getAttribute('data-cmp-preset'));
  });
}

function applyComparePreset(preset) {
  const today = new Date();
  const p1To = $('#cmp-p1-to');
  const p1From = $('#cmp-p1-from');
  const p2From = $('#cmp-p2-from');
  const p2To = $('#cmp-p2-to');
  if (!p1From || !p1To || !p2From || !p2To) return;
  if (preset === 'prev-month') {
    const d = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const lastPrev = new Date(today.getFullYear(), today.getMonth(), 0);
    const d2f = new Date(today.getFullYear(), today.getMonth() - 2, 1);
    const d2t = new Date(today.getFullYear(), today.getMonth() - 1, 0);
    p1From.value = formatYMD(d);
    p1To.value = formatYMD(lastPrev);
    p2From.value = formatYMD(d2f);
    p2To.value = formatYMD(d2t);
  } else if (preset === 'same-last-year') {
    const d = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const lastPrev = new Date(today.getFullYear(), today.getMonth(), 0);
    p1From.value = formatYMD(d);
    p1To.value = formatYMD(lastPrev);
    const d2 = new Date(today.getFullYear() - 1, today.getMonth() - 1, 1);
    const d2t = new Date(today.getFullYear() - 1, today.getMonth(), 0);
    p2From.value = formatYMD(d2);
    p2To.value = formatYMD(d2t);
  }
}

function formatYMD(d) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

async function loadDesgloseCompare() {
  const wrap = $('#cmp-results');
  if (!wrap) return;
  wrap.innerHTML = '<div class="skeleton-card"></div>';
  try {
    const params = new URLSearchParams();
    params.set('by', $('#cmp-by')?.value || 'vendor');
    params.set('p1_from', $('#cmp-p1-from')?.value || '');
    params.set('p1_to', $('#cmp-p1-to')?.value || '');
    params.set('p2_from', $('#cmp-p2-from')?.value || '');
    params.set('p2_to', $('#cmp-p2-to')?.value || '');
    const d = await getJSON('/api/gastos/desglose/compare?' + params.toString());

    if (!d.items || d.items.length === 0) {
      wrap.innerHTML = '<div class="excel-empty"><div class="ico">' + icon('scale', 'ico ico-xs') + '</div><h3>Sin datos comparables</h3><p>Ajusta los rangos de fechas.</p></div>';
      return;
    }

    const fmt = (n) => Number(n||0).toLocaleString('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2});

    wrap.innerHTML = `
      <div style="margin-bottom:var(--s-2);font-size:var(--fz-xs);color:var(--fg-3)">
        P1: <b>${esc(d.p1_from)} → ${esc(d.p1_to)}</b> vs P2: <b>${esc(d.p2_from)} → ${esc(d.p2_to)}</b>
      </div>
      <div style="overflow:auto"><table class="cmp-table">
        <thead><tr>
          <th>${esc(d.by)}</th>
          <th class="num">P1 (${esc(d.p1_from)}/${esc(d.p1_to)})</th>
          <th class="num">P2 (${esc(d.p2_from)}/${esc(d.p2_to)})</th>
          <th class="num">Δ</th>
          <th class="num">Δ%</th>
          <th class="num">Δ facturas</th>
        </tr></thead>
        <tbody>
          ${d.items.map(it => {
            const pct = it.delta_pct;
            const pctClass = pct == null ? 'cmp-delta-zero' : (pct > 0 ? 'cmp-delta-pos' : (pct < 0 ? 'cmp-delta-neg' : 'cmp-delta-zero'));
            const pctStr = pct == null ? '—' : (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%';
            const deltaClass = it.delta > 0 ? 'cmp-delta-pos' : (it.delta < 0 ? 'cmp-delta-neg' : 'cmp-delta-zero');
            const deltaStr = (it.delta >= 0 ? '+' : '') + fmt(it.delta) + '€';
            const cntDelta = it.p1_count - it.p2_count;
            const cntStr = (cntDelta >= 0 ? '+' : '') + cntDelta;
            return `<tr>
              <td>${esc(it.dim)}</td>
              <td class="num">${fmt(it.p1_total)}€<br><small>${it.p1_count} fac</small></td>
              <td class="num">${fmt(it.p2_total)}€<br><small>${it.p2_count} fac</small></td>
              <td class="num ${deltaClass}">${deltaStr}</td>
              <td class="num ${pctClass}">${pctStr}</td>
              <td class="num">${cntStr}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table></div>
    `;
  } catch(e) {
    wrap.innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">' + esc(e.message) + '</div></div>';
  }
}

async function exportDesgloseCsv() {
  const params = new URLSearchParams();
  // Export según pestaña activa
  let by = 'vendor';
  if (DG.activeTab === 'analisis' || DG.activeTab === 'top') by = $('#' + (DG.activeTab === 'analisis' ? 'mtx-cols' : 'top-by'))?.value || 'vendor';
  if (DG.activeTab === 'comparar') by = $('#cmp-by')?.value || 'vendor';
  params.set('by', by);
  Object.entries(DG.filters).forEach(([k,v]) => v && params.set(k, v));
  try {
    const r = await _fetchAuth('/api/gastos/desglose/export.csv?' + params.toString());
    if (!r.ok) { toast('Error exportando CSV', 'error'); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `desglose_${by}_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    toast('CSV descargado', 'success');
  } catch(e) {
    toast('Error: ' + e.message, 'error');
  }
}


// ── v8.3 PRO: Vista Productos ─────────────────────────────────────

const PR = {
  items: [],
  stats: null,
  detail: null,
};

async function renderProductos() {
  // Stats
  await loadProductosStats();
  // Lista
  await loadProductosList();
  // Wire controles
  const search = $('#pr-search');
  if (search && !search._wired) {
    search._wired = true;
    let to;
    search.oninput = () => { clearTimeout(to); to = setTimeout(() => loadProductosList(), 250); };
  }
  const av = $('#pr-available-only');
  if (av && !av._wired) {
    av._wired = true;
    av.onchange = loadProductosList;
  }
  const sort = $('#pr-sort');
  if (sort && !sort._wired) {
    sort._wired = true;
    sort.onchange = loadProductosList;
  }
}

async function loadProductosStats() {
  const grid = $('#pr-stats');
  if (!grid) return;
  try {
    const d = await getJSON('/api/productos/stats/resumen');
    PR.stats = d;
    const fmt = (n) => Number(n||0).toLocaleString('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const fmt0 = (n) => Number(n||0).toLocaleString('es-ES', {maximumFractionDigits: 0});
    grid.innerHTML = `
      <div class="pr-stat success">
        <div class="pr-stat-label">Total productos</div>
        <div class="pr-stat-value">${fmt0(d.total)}</div>
        <div class="pr-stat-meta">${fmt0(d.disponibles)} disponibles</div>
      </div>
      <div class="pr-stat">
        <div class="pr-stat-label">Precio mínimo</div>
        <div class="pr-stat-value">${fmt(d.precio_min/100)}€</div>
        <div class="pr-stat-meta">el más barato</div>
      </div>
      <div class="pr-stat">
        <div class="pr-stat-label">Precio máximo</div>
        <div class="pr-stat-value">${fmt(d.precio_max/100)}€</div>
        <div class="pr-stat-meta">el más caro</div>
      </div>
      <div class="pr-stat warn">
        <div class="pr-stat-label">Precio medio</div>
        <div class="pr-stat-value">${fmt(d.precio_medio/100)}€</div>
        <div class="pr-stat-meta">media del catálogo</div>
      </div>
    `;
  } catch(e) {
    grid.innerHTML = `<div class="pr-error"><h3>${icon('alert-triangle', 'ico ico-xs')} No se pudo cargar estadísticas</h3><p>${esc(e.message)}</p></div>`;
  }
}

async function loadProductosList() {
  const list = $('#pr-list');
  if (!list) return;
  list.innerHTML = '<div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div>';
  const params = new URLSearchParams();
  const av = $('#pr-available-only')?.checked;
  if (av) params.set('available_only', 'true');
  const search = $('#pr-search')?.value?.trim();
  if (search) params.set('search', search);
  params.set('limit', '50');
  try {
    const d = await getJSON('/api/productos/catalogo?' + params.toString());
    PR.items = d.items || [];
    renderProductosList();
    const el = $('#pr-gen-at');
    if (el) el.textContent = `Última actualización: ${new Date().toLocaleString('es-ES')}`;
  } catch(e) {
    list.innerHTML = `<div class="pr-error"><h3>${icon('alert-triangle', 'ico ico-xs')} Error cargando catálogo</h3><p>${esc(e.message)}</p></div>`;
  }
}

function renderProductosList() {
  const list = $('#pr-list');
  if (!list) return;
  let items = PR.items.slice();
  const sort = $('#pr-sort')?.value || 'name';
  if (sort === 'name') items.sort((a,b) => (a.name||'').localeCompare(b.name||''));
  else if (sort === 'price-asc') items.sort((a,b) => (a.price||0) - (b.price||0));
  else if (sort === 'price-desc') items.sort((a,b) => (b.price||0) - (a.price||0));
  
  if (items.length === 0) {
    list.innerHTML = `<div class="pr-empty"><h3>${icon('package', 'ico ico-xs')} Sin productos</h3><p>No se encontraron productos que coincidan con los filtros.</p></div>`;
    return;
  }

  list.innerHTML = items.map(p => {
    const price_eur = p.price != null ? (p.price / 100).toFixed(2) : null;
    const cents = p.price != null ? (' ' + (p.price % 100).toFixed(0).padStart(2, '0') + '€') : '';
    const status = p.available ? 'available' : 'unavailable';
    const statusText = p.available ? 'Disponible' : 'No disponible';
    const disabledClass = p.available ? '' : 'disabled';
    return `<div class="pr-card ${disabledClass}" data-product-id="${esc(p.id)}">
      <div class="pr-card-category">${esc(p.category || 'Sin categoría')}</div>
      <div class="pr-card-name">${esc(p.name || '(sin nombre)')}</div>
      <div class="pr-card-price">${price_eur != null ? price_eur + '€' : '—'}<span class="pr-card-price-cents"></span></div>
      <div class="pr-card-status ${status}">${statusText}</div>
      <div class="pr-card-id">${esc((p.id||'').slice(0,8))}…</div>
    </div>`;
  }).join('');
  
  // Wire clicks
  $$('.pr-card').forEach(card => {
    if (card._wired) return;
    card._wired = true;
    card.onclick = () => openProductoDetail(card.getAttribute('data-product-id'));
  });
}

async function openProductoDetail(productId) {
  if (!productId) return;
  try {
    const p = await getJSON('/api/productos/' + encodeURIComponent(productId));
    const price_eur = p.price != null ? (p.price / 100).toFixed(2) : null;
    const status = p.available ? 'Disponible' : 'No disponible';
    const statusClass = p.available ? 'available' : 'unavailable';
    const html = `
      <div class="pr-detail">
        <h3 style="margin:0 0 var(--s-3) 0">${esc(p.name)}</h3>
        <dl class="pr-detail-grid">
          <dt>ID</dt><dd><code>${esc(p.id)}</code></dd>
          <dt>Precio</dt><dd>${price_eur != null ? price_eur + '€' : '—'}</dd>
          <dt>Categoría</dt><dd>${esc(p.category || 'Sin categoría')}</dd>
          <dt>Estado</dt><dd><span class="pr-card-status ${statusClass}">${status}</span></dd>
          ${p.description ? `<dt>Descripción</dt><dd>${esc(p.description)}</dd>` : ''}
        </dl>
        <div style="display:flex;gap:var(--s-2);margin-top:var(--s-3)">
          <button class="pr-mini-btn success" onclick="toggleProducto('${esc(p.id)}', true)" ${p.available ? 'disabled style="opacity:.5"' : ''}>
            ✓ Marcar disponible
          </button>
          <button class="pr-mini-btn danger" onclick="toggleProducto('${esc(p.id)}', false)" ${!p.available ? 'disabled style="opacity:.5"' : ''}>
            '×' Marcar no disponible
          </button>
          <button class="pr-mini-btn" onclick="chatPrefill('Analiza el producto ${esc(p.name.replace(/'/g, "\\'"))} con ID ${p.id}')">
            icon('message-circle', 'ico ico-xs') Preguntar al chat
          </button>
        </div>
      </div>
    `;
    // Mostrar como toast persistente o reemplazar lista (modal sería ideal pero simple inline)
    const old = $('#pr-detail');
    if (old) old.remove();
    const detail = document.createElement('div');
    detail.id = 'pr-detail';
    detail.innerHTML = html;
    document.querySelector('[data-view="productos"]')?.appendChild(detail);
    detail.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  } catch(e) {
    toast('Error cargando producto: ' + e.message, 'error');
  }
}

async function toggleProducto(productId, available) {
  if (!confirm(`¿Cambiar disponibilidad a ${available ? 'DISPONIBLE' : 'NO DISPONIBLE'}? Esta acción modifica tu catálogo en Last.app.`)) return;
  try {
    const r = await _postJSON(`/api/productos/${encodeURIComponent(productId)}/disponibilidad`, {available, reason: 'Cambiado desde dashboard'});
    if (r.ok) {
      toast(`✓ Disponibilidad actualizada`, 'success');
      await loadProductosList();
    } else {
      toast(icon('alert-triangle', 'ico ico-xs') + ' La operación requiere confirmación', 'warn');
    }
  } catch(e) {
    toast('Error: ' + e.message, 'error');
  }
}

// ── PYG / Análisis (jerárquico) ──────────────────────────────────────

function formatEuro(v) {
  if (v == null || isNaN(v)) return '—';
  const sign = v < 0 ? '-' : '';
  return sign + new Intl.NumberFormat('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Math.abs(v)) + ' €';
}

function formatPct(v) {
  if (v == null || isNaN(v)) return '';
  return (v * 100).toFixed(1) + '%';
}

async function loadDesglosePyg() {
  const fromVal = $('#dg-from').value;
  const toVal = $('#dg-to').value;
  const cuenta = $('#dg-cuenta').value;
  const cmpMode = $('#pyg-cmp-mode').value;
  const tbody = $('#pyg-tbody');
  const issuesEl = $('#pyg-issues');
  if (!fromVal || !toVal) {
    toast(icon('alert-triangle', 'ico ico-xs') + ' Selecciona Desde y Hasta en los filtros globales', 'warn');
    return;
  }

  // Determinar compare_from / compare_to
  let compareFrom = null, compareTo = null;
  if (cmpMode === 'prev') {
    const d1 = new Date(fromVal);
    const d2 = new Date(toVal);
    const days = Math.round((d2 - d1) / 86400000);
    const prevD2 = new Date(d1);
    prevD2.setDate(prevD2.getDate() - 1);
    const prevD1 = new Date(prevD2);
    prevD1.setDate(prevD1.getDate() - days);
    compareFrom = prevD1.toISOString().slice(0, 10);
    compareTo = prevD2.toISOString().slice(0, 10);
  } else if (cmpMode === 'custom') {
    compareFrom = $('#pyg-cmp-from').value || null;
    compareTo = $('#pyg-cmp-to').value || null;
  }

  tbody.innerHTML = '<tr><td colspan="3" class="muted">⏳ Calculando PYG...</td></tr>';
  issuesEl.innerHTML = '';

  try {
    const params = new URLSearchParams({
      date_from: fromVal,
      date_to: toVal,
    });
    if (cuenta) params.set('cuenta', cuenta);
    if (compareFrom) params.set('compare_from', compareFrom);
    if (compareTo) params.set('compare_to', compareTo);
    const r = await fetch('/api/gastos/pyg?' + params.toString(), {credentials: 'include'});
    if (!r.ok) {
      const errText = await r.text();
      throw new Error(`HTTP ${r.status}: ${errText.slice(0, 200)}`);
    }
    const data = await r.json();
    renderPygResults(data);
  } catch(e) {
    tbody.innerHTML = '<tr><td colspan="3" class="state error">' + esc(e.message) + '</td></tr>';
    toast('Error PYG: ' + e.message, 'error');
  }
}

function renderPygResults(data) {
  const t = data.totals;
  const buckets = data.buckets;
  const lines = data.lines;
  const issues = data.issues;
  const comparison = data.comparison;

  // KPIs
  $('#pyg-kpi-ingresos').textContent = formatEuro(t.ingresos);
  $('#pyg-kpi-ingresos-pct').textContent = '';
  $('#pyg-kpi-margenbruto').textContent = formatEuro(t.margen_bruto);
  $('#pyg-kpi-margenbruto-pct').textContent = formatPct(t.margen_bruto_pct) + ' s/ingresos';
  $('#pyg-kpi-mc').textContent = formatEuro(t.mc);
  $('#pyg-kpi-mc-pct').textContent = formatPct(t.mc_pct) + ' s/ingresos';
  $('#pyg-kpi-ebitda').textContent = formatEuro(t.ebitda);
  $('#pyg-kpi-ebitda-pct').textContent = formatPct(t.ebitda_pct) + ' s/ingresos';
  // Color EBITDA
  const ebitdaEl = $('#pyg-kpi-ebitda');
  ebitdaEl.classList.remove('kpi-pos', 'kpi-neg');
  if (t.ebitda > 0) ebitdaEl.classList.add('kpi-pos');
  else if (t.ebitda < 0) ebitdaEl.classList.add('kpi-neg');

  // Issues
  const issuesEl = $('#pyg-issues');
  if (!issues || issues.length === 0) {
    issuesEl.innerHTML = '<div class="state ok">✓ Sin alertas en este período</div>';
  } else {
    issuesEl.innerHTML = issues.map(i =>
      `<div class="state ${i.level === 'error' ? 'error' : 'warn'}">
        <div class="title">${i.level === 'error' ? '🔴' : i.level === 'warn' ? '🟡' : '🔵'} ${esc(i.code)}</div>
        <div class="desc">${esc(i.message)}</div>
      </div>`
    ).join('');
  }

  // Tabla de líneas
  const tbody = $('#pyg-tbody');
  tbody.innerHTML = lines.map(line => {
    const indent = '— '.repeat(line.level || 0);
    const isSubtotal = line.kind === 'subtotal' || line.kind === 'kpi';
    const highlight = line.highlight ? ` class="pyg-line-${line.highlight}"` : '';
    const valClass = line.value < 0 ? 'num neg' : 'num';
    return `<tr${highlight}>
      <td>${indent}${esc(line.label)}</td>
      <td class="${valClass}">${formatEuro(line.value)}</td>
      <td class="num">${line.pct != null ? formatPct(line.pct) : ''}</td>
    </tr>`;
  }).join('');

  // Comparación
  const cmpEl = $('#pyg-comparison');
  const cmpTable = $('#pyg-comparison-table');
  if (comparison) {
    cmpEl.style.display = 'block';
    const keys = ['ingresos', 'total_gastos', 'margen_bruto', 'mc', 'ebitda', 'beneficio'];
    const labels = {
      ingresos: 'Ingresos',
      total_gastos: 'Total gastos',
      margen_bruto: 'Margen bruto',
      mc: 'MC',
      ebitda: 'EBITDA',
      beneficio: 'Beneficio neto',
    };
    let html = '<table class="gd-pyg-table"><thead><tr><th>Métrica</th><th class="num">Actual</th><th class="num">Anterior</th><th class="num">Δ €</th><th class="num">Δ %</th></tr></thead><tbody>';
    keys.forEach(k => {
      const c = comparison[k];
      if (!c) return;
      const pct = c.diff_pct;
      const cls = c.diff_eur > 0 ? 'kpi-pos' : c.diff_eur < 0 ? 'kpi-neg' : '';
      html += `<tr>
        <td>${labels[k]}</td>
        <td class="num">${formatEuro(c.current)}</td>
        <td class="num">${formatEuro(c.previous)}</td>
        <td class="num ${cls}">${(c.diff_eur > 0 ? '+' : '') + formatEuro(c.diff_eur)}</td>
        <td class="num ${cls}">${pct > 0 ? '+' : ''}${formatPct(pct)}</td>
      </tr>`;
    });
    html += '</tbody></table>';
    html += `<p class="muted">Comparando con período ${esc(comparison.period.from)} → ${esc(comparison.period.to)}</p>`;
    cmpTable.innerHTML = html;
  } else {
    cmpEl.style.display = 'none';
  }

  // Drill-down
  const drillEl = $('#pyg-drilldown');
  const drillContent = $('#pyg-drilldown-content');
  const drill = data.drilldown || {};
  if (Object.keys(drill).length > 0) {
    drillEl.style.display = 'block';
    let html = '';
    Object.entries(drill).forEach(([bucket, subs]) => {
      const bucketTotal = buckets[bucket] || 0;
      html += `<div class="pyg-bucket"><h4>${esc(bucket)} · ${formatEuro(bucketTotal)}</h4>`;
      Object.entries(subs).forEach(([sub, info]) => {
        html += `<div class="pyg-subcat"><strong>${esc(sub)}</strong> · ${formatEuro(info.value)}<ul>`;
        info.vendors.forEach(v => {
          html += `<li>${esc(v.name)} — ${formatEuro(v.value)}</li>`;
        });
        html += '</ul></div>';
      });
      html += '</div>';
    });
    drillContent.innerHTML = html;
  } else {
    drillEl.style.display = 'none';
  }
}

function wirePygControls() {
  const apply = $('#pyg-apply');
  if (apply && !apply._wired) {
    apply._wired = true;
    apply.onclick = loadDesglosePyg;
  }
  const mode = $('#pyg-cmp-mode');
  if (mode && !mode._wired) {
    mode._wired = true;
    mode.onchange = () => {
      const showCustom = mode.value === 'custom';
      $$('.pyg-cmp-custom').forEach(el => { el.style.display = showCustom ? '' : 'none'; });
    };
  }
  // Auto-cargar al activar la pestaña
  const pygTab = $$('.excel-tab').find(t => t.getAttribute('data-tab') === 'pyg');
  if (pygTab && !pygTab._pygWired) {
    pygTab._pygWired = true;
    pygTab.addEventListener('click', () => {
      // Espera a que el panel esté visible
      setTimeout(() => {
        const legacyPygBody = $('#pyg-tbody');
        if (legacyPygBody && legacyPygBody.children.length <= 1) {
          loadDesglosePyg();
        }
      }, 100);
    });
  }
}

// Llamada inicial tras DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(wirePygControls, 200);
});


// ── Libro financiero reconstruido desde la referencia Excel ─────────
const CR = { data: null, sheet: 'resumen', month: '' };

function crMonthLabel(key) {
  const [y,m] = key.split('-');
  const names = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  return `${names[Number(m)-1]}-${y.slice(2)}`;
}
function crNumber(value, percentage=false) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  let n = Number(value);
  if (Math.abs(n) < 1e-9) n = 0;
  if (percentage) {
    const pct = n * 100;
    const digits = pct !== 0 && Math.abs(pct) < 1 ? 1 : 0;
    return `${pct.toLocaleString('es-ES',{minimumFractionDigits:digits,maximumFractionDigits:digits})}%`;
  }
  const rounded = Math.round(Math.abs(n)).toString().replace(/\B(?=(\d{3})+(?!\d))/g,'.');
  return `${n < 0 ? '-' : ''}${rounded}`;
}
function crColumnName(index) {
  let name = '';
  for (let n = index + 1; n; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  return name;
}

function crRenderRow(row, columns, parentCode=null, rowNumber=1) {
  const percentage = row.kind === 'percentage';
  const unavailable = row.availability === 'unavailable';
  const classes = [`cr-kind-${row.kind || 'line'}`, row.section ? 'cr-section' : '', parentCode ? 'cr-child' : ''].filter(Boolean).join(' ');
  const parentAttr = parentCode ? ` data-parent="${esc(parentCode)}" style="display:none"` : '';
  const code = esc(row.code);
  let html = `<tr class="${classes}" data-code="${code}"${parentAttr}>`;
  html += `<td class="cr-row-num">${rowNumber}</td>`;
  html += `<td class="cr-label" style="padding-left:${12 + (row.level||0)*18}px">${row.children && row.children.length ? `<button class="cr-chevron" aria-label="Mostrar desglose">+</button>` : ''}<span>${esc(row.label)}</span>${unavailable ? '<small class="cr-na">N/D</small>' : ''}</td>`;
  columns.forEach(col => {
    const value = unavailable ? null : (row.values || {})[col];
    html += `<td class="cr-num ${value < 0 ? 'cr-negative' : ''}" data-formula="${value == null ? '' : esc(String(value))}">${crNumber(value, percentage)}</td>`;
  });
  html += '</tr>';
  (row.children || []).forEach((child, index) => { html += crRenderRow(child, columns, row.code, `${rowNumber}.${index + 1}`); });
  return html;
}

function crTableHead(columns, title) {
  const letters = ['A', ...columns.map((_, i) => crColumnName(i + 1))];
  const years = columns.map(c => c === 'YTD' ? 'YTD' : c.slice(0,4));
  const monthNumbers = columns.map(c => c === 'YTD' ? 'YTD' : Number(c.slice(5,7)));
  return `<tr class="cr-col-letters"><th class="cr-corner"></th>${letters.map(l => `<th>${l}</th>`).join('')}</tr>` +
    `<tr class="cr-head-period"><th></th><th></th>${columns.map(c => `<th>${c === 'YTD' ? 'YTD' : crMonthLabel(c)}</th>`).join('')}</tr>` +
    `<tr class="cr-head-real"><th></th><th></th>${columns.map(() => '<th>REAL</th>').join('')}</tr>` +
    `<tr class="cr-head-year"><th></th><th>${esc(title)}</th>${years.map(y => `<th>${y}</th>`).join('')}</tr>` +
    `<tr class="cr-head-index"><th></th><th></th>${monthNumbers.map(m => `<th>${m}</th>`).join('')}</tr>` +
    `<tr class="cr-head-month"><th></th><th>€</th>${columns.map(c => `<th>${c === 'YTD' ? 'YTD' : crMonthLabel(c)}</th>`).join('')}</tr>`;
}

function crCollectProviders(rows, columns) {
  const merged = new Map();
  function visit(row) {
    if (row.kind === 'provider') {
      const key = row.provider_key || row.label;
      if (!merged.has(key)) merged.set(key, {code:`provider.${key}`, label:row.label, kind:'provider', level:0, values:{}});
      const target = merged.get(key);
      columns.forEach(col => { target.values[col] = Number(target.values[col] || 0) + Number((row.values || {})[col] || 0); });
    }
    (row.children || []).forEach(visit);
  }
  (rows || []).forEach(visit);
  return [...merged.values()].sort((a,b) => Math.abs(b.values.YTD || 0) - Math.abs(a.values.YTD || 0));
}

function crCategoryRows(rows) {
  return (rows || []).filter(row => row.section || row.kind === 'percentage').map(row => ({...row, children: row.children || []}));
}

function crBlankSheet() {
  const head = $('#cr-head'), body = $('#cr-body');
  const columns = Array.from({length:13}, (_,i) => crColumnName(i + 1));
  head.innerHTML = `<tr class="cr-col-letters"><th class="cr-corner"></th><th>A</th>${columns.map(c=>`<th>${c}</th>`).join('')}</tr>`;
  body.innerHTML = Array.from({length:32},(_,r) => `<tr><td class="cr-row-num">${r+1}</td><td class="cr-label cr-empty-cell"></td>${columns.map(()=>'<td class="cr-num cr-empty-cell"></td>').join('')}</tr>`).join('');
}

function crRenderSheet(sheet=CR.sheet) {
  if (!CR.data) return;
  CR.sheet = sheet;
  $$('.cr-sheet-tab').forEach(tab => {
    const active = tab.dataset.crSheet === sheet;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const allColumns = CR.data.columns || [];
  let columns = allColumns, rows = CR.data.rows || [], title = 'A. Cuenta de resultados';
  if (sheet === 'resumen') {
    const monthCols = allColumns.filter(c => c !== 'YTD');
    columns = [CR.month || monthCols.at(-1), 'YTD'].filter(Boolean);
    rows = (CR.data.rows || []).filter(row => row.section || row.kind === 'percentage');
    title = 'Resumen Ejecutivo';
  } else if (sheet === 'evolucion') {
    title = 'Evolución Mensual';
  } else if (sheet === 'proveedores') {
    rows = crCollectProviders(CR.data.rows || [], allColumns);
    if (CR.month) columns = [CR.month, 'YTD'];
    title = 'Análisis Proveedores';
  } else if (sheet === 'categorias') {
    rows = crCategoryRows(CR.data.rows || []);
    if (CR.month) columns = [CR.month, 'YTD'];
    title = 'Por Categorías';
  } else if (sheet === 'hoja5') {
    crBlankSheet();
    $('#cr-formula').textContent = '';
    $('#cr-name-box').textContent = 'A1';
    return;
  }
  $('#cr-head').innerHTML = crTableHead(columns, title);
  $('#cr-body').innerHTML = rows.map((row,index) => crRenderRow(row, columns, null, index + 1)).join('') || '<tr><td class="cr-row-num">1</td><td class="muted">Sin datos para esta hoja.</td></tr>';
  $('#cr-formula').textContent = title;
  $('#cr-name-box').textContent = 'A1';
}
async function loadCuentaResultados() {
  const today = new Date().toISOString().slice(0,10);
  const selectedFrom = $('#dg-from')?.value || '';
  const selectedTo = $('#dg-to')?.value || today;
  const to = selectedTo > today ? today : selectedTo;
  const targetYear = Number(to.slice(0,4)) || new Date().getFullYear();
  const defaultFrom = `${targetYear}-01-01`;
  const from = selectedFrom && selectedFrom <= to ? selectedFrom : defaultFrom;
  const cuenta = $('#dg-cuenta')?.value;
  const head = $('#cr-head'), body = $('#cr-body');
  if (!head || !body || !from || !to) return;
  body.innerHTML = '<tr><td class="muted">Calculando cuenta de resultados…</td></tr>';
  try {
    const params = new URLSearchParams({date_from: from, date_to: to});
    if (cuenta) params.set('cuenta', cuenta);
    const data = await getJSON('/api/gastos/cuenta-resultados?' + params.toString());
    CR.data = data;
    const monthFilter = $('#cr-month-filter');
    if (monthFilter) {
      const months = (data.columns || []).filter(c => c !== 'YTD');
      const previous = CR.month;
      monthFilter.innerHTML = '<option value="">Todos los meses</option>' + months.map(c => `<option value="${esc(c)}">${crMonthLabel(c)}</option>`).join('');
      CR.month = months.includes(previous) ? previous : '';
      monthFilter.value = CR.month;
      if (!monthFilter._wired) {
        monthFilter._wired = true;
        monthFilter.onchange = () => { CR.month = monthFilter.value; crRenderSheet(CR.sheet); };
      }
    }
    crRenderSheet(CR.sheet);
    $('#cr-meta').textContent = `REAL · ${data.period.from} → ${data.period.to} · ${data.rows_used || 0} registros · importes en €`;
    const issues = (data.issues || []).filter(i => i.level && i.level !== 'info');
    $('#cr-issues').innerHTML = issues.map(i => `<span class="cr-issue">${icon('alert-triangle','ico ico-xs')} ${esc(i.message)}</span>`).join('');
    const reload = $('#cr-reload');
    if (reload && !reload._wired) { reload._wired = true; reload.onclick = loadCuentaResultados; }
    const expand = $('#cr-expand-all');
    if (expand && !expand._wired) {
      expand._wired = true;
      expand.onclick = () => {
        const hidden = $$('.cr-child').some(el => el.style.display === 'none');
        $$('.cr-child').forEach(el => { el.style.display = hidden ? 'table-row' : 'none'; });
        expand.textContent = hidden ? 'Ocultar detalle' : 'Expandir detalle';
      };
    }
    body.onclick = (event) => {
      const cell = event.target.closest('td');
      if (cell) {
        $$('#cr-body td.cr-selected').forEach(el => el.classList.remove('cr-selected'));
        cell.classList.add('cr-selected');
        const row = cell.closest('tr');
        const rowIndex = [...body.children].indexOf(row) + 1;
        const colIndex = [...row.children].indexOf(cell);
        $('#cr-name-box').textContent = `${crColumnName(Math.max(0,colIndex-1))}${rowIndex}`;
        $('#cr-formula').textContent = cell.dataset.formula || cell.textContent.trim();
      }
      const button = event.target.closest('.cr-chevron');
      if (!button) return;
      const row = button.closest('tr');
      const code = row?.dataset.code;
      const children = $$(`.cr-child[data-parent="${CSS.escape(code)}"]`);
      const show = children.some(el => el.style.display === 'none');
      children.forEach(el => { el.style.display = show ? 'table-row' : 'none'; });
      button.textContent = show ? '−' : '+';
    };
    $$('.cr-sheet-tab').forEach(tab => {
      if (tab._wired) return;
      tab._wired = true;
      tab.onclick = () => crRenderSheet(tab.dataset.crSheet);
    });
  } catch (e) {
    body.innerHTML = `<tr><td class="state error">${esc(e.message)}</td></tr>`;
  }
}
