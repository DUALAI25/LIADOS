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
        if (v === 'gastos-detalle') renderGastosDetalle();
        if (v === 'alertas') renderAlertas();
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
  $('#gd-prev').onclick = () => { if (GD.page > 1) { GD.page--; loadGastos(); } };
  $('#gd-next').onclick = () => { GD.page++; loadGastos(); };
  // Submit on Enter en cualquier input de filtro
  ['gd-q','gd-from','gd-to','gd-vendor','gd-cat','gd-min','gd-max'].forEach(id => {
    const el = $('#'+id);
    if (el) el.onkeydown = (e) => { if (e.key === 'Enter') { GD.page = 1; loadGastos(); } };
  });
  loadGastos();
}

async function refreshGastosDetalle() {
  // Re-carga sin resetear paginación (para refresh manual)
  loadGastos();
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
          <td><span class="status status-${esc(r.status||'pending')}">${esc(r.status||'pending')}</span></td>
          <td class="num"><b>${eur(r.total_amount||0)}</b></td>
          <td>${r.raw_file_url ? '<span class="pdf-yes" title="PDF disponible">📎</span>' : '<span class="muted" title="Sin PDF">—</span>'}</td>
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
    const pdfBlock = f.raw_file_url
      ? (f.pdf_exists
          ? `<a class="btn primary" href="/api/gastos/${id}/pdf" target="_blank" rel="noopener" download>📄 Ver/Descargar PDF (${(f.pdf_size_bytes/1024).toFixed(1)} KB)</a>`
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
        <div><span class="factura-label">Status</span><span class="status status-${esc(f.status||'pending')}">${esc(f.status||'pending')}</span></div>
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
        <button class="btn ghost" onclick="chatPrefill('Analiza la factura ${esc(f.invoice_number||id)} de ${esc((f.vendor_name||'').replace(/'/g, ''))}')">💬 Abrir en chat AI</button>
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
    // Badge en nav
    const badge = $('#nav-alert-badge');
    if (badge) {
      const total = r.high + r.medium;
      badge.textContent = total > 0 ? total : '';
      badge.style.display = total > 0 ? 'inline-block' : 'none';
    }
    if (data.items.length === 0) {
      list.innerHTML = `<div class="al-empty"><div class="al-empty-icon">✅</div><h3>Sin alertas activas</h3><p>Todos los indicadores están dentro de los rangos esperados.</p></div>`;
      return;
    }
    const dismissed = JSON.parse(localStorage.getItem('liados_alerts_dismissed') || '{}');
    const now = Date.now();
    list.innerHTML = data.items.map(a => {
      const isDismissed = dismissed[a.id] && (now - dismissed[a.id] < 24*3600*1000);
      const dismissBtn = isDismissed ? '' : `<button class="al-dismiss" data-id="${esc(a.id)}" aria-label="Descartar alerta">✕</button>`;
      const cta = a.cta
        ? (a.cta.prefill
            ? `<button class="al-cta" data-prefill="${esc(a.cta.prefill)}">${esc(a.cta.label||'Abrir en chat')} →</button>`
            : `<button class="al-cta" data-prefill="${esc(a.titulo)}">${esc(a.cta.label||'Abrir en chat')} →</button>`)
        : '';
      return `<article class="al-card al-${esc(a.severity)} ${isDismissed?'al-dismissed':''}" role="alert" aria-label="Alerta ${a.severity}: ${esc(a.titulo)}">
        <div class="al-stripe"></div>
        <div class="al-body">
          <div class="al-head">
            <span class="al-sev al-sev-${esc(a.severity)}">${sevLabel(a.severity)}</span>
            <span class="al-tipo">${esc(a.tipo)}</span>
            <h3>${esc(a.titulo)}</h3>
            ${dismissBtn}
          </div>
          <p class="al-desc">${esc(a.descripcion)}</p>
          ${a.accion_sugerida ? `<p class="al-accion">💡 <b>Acción:</b> ${esc(a.accion_sugerida)}</p>` : ''}
          <div class="al-foot">
            ${cta}
            <span class="al-ts">Detectada: ${esc(data.generated_at.replace('T',' ').replace('Z',' UTC'))}</span>
          </div>
        </div>
      </article>`;
    }).join('');
    // Wire dismiss
    $$('.al-dismiss').forEach(b => b.onclick = () => {
      const id = b.getAttribute('data-id');
      const d = JSON.parse(localStorage.getItem('liados_alerts_dismissed') || '{}');
      d[id] = Date.now();
      localStorage.setItem('liados_alerts_dismissed', JSON.stringify(d));
      const card = b.closest('.al-card');
      if (card) { card.style.transition = 'opacity .3s, transform .3s'; card.style.opacity = '0'; card.style.transform = 'translateX(20px)'; setTimeout(() => card.remove(), 300); }
      toast('Alerta descartada (24h)', 'info');
    });
    // Wire CTA
    $$('.al-cta').forEach(b => b.onclick = () => chatPrefill(b.getAttribute('data-prefill')));
  } catch(e) {
    list.innerHTML = '<div class="state error"><div class="title">Error</div><div class="desc">' + esc(e.message) + '</div></div>';
  }
}

function sevLabel(s) {
  return { high: '🔴 ALTA', medium: '🟡 MEDIA', low: '🔵 BAJA', info: '⚪ INFO' }[s] || s;
}

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
          <b>📧 ${esc(a.account)}</b>
          ${statusBadge}
        </div>
        <div class="cfg-fuente-grid">
          <div><span>Credentials</span><b>${a.credentials_file_exists ? '✓' : '✗'}</b></div>
          <div><span>Token</span><b>${a.token_file_exists ? '✓' : '✗'}</b></div>
          <div><span>Refresh</span><b>${a.has_refresh_token ? '✓' : '✗'}</b></div>
          <div><span>Edad token</span><b>${ageStr}</b></div>
          <div><span>Client ID</span><b><code>${esc(clientStr)}</code></b></div>
          <div><span>Scope</span><b><code>${esc(a.scope||'—')}</code></b></div>
        </div>
        ${a.status === 'MISSING_TOKEN' || a.status === 'STALE' ? `<details class="cfg-reauth"><summary>🔄 Reautorizar esta cuenta</summary>
          <ol>
            <li>En tu máquina local, ejecuta:<br><code>python3 -m agente.scripts.gmail_auth --account ${esc(a.account)} --force</code></li>
            <li>Sube el nuevo token al VPS:<br><code>scp agente/credentials/gmail_token_${esc(a.account)}.json vps:/root/liados/agente/credentials/</code></li>
            <li>Prueba el collector:<br><code>python3 -m agente.scripts.gmail_collector --account ${esc(a.account)} --dry-run</code></li>
          </ol>
          <p class="muted">⚠️ El re-OAuth requiere navegador interactivo. No se puede automatizar desde el dashboard.</p>
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
  t.innerHTML = `<span class="toast-ico">${type==='error'?'⛔':type==='success'?'✓':type==='warn'?'⚠':'ℹ'}</span><span>${esc(msg)}</span><button class="toast-x" aria-label="Cerrar">✕</button>`;
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
  { id: 'nav:dashboard', label: 'Ir a Dashboard', icon: '📊', action: () => switchView('dashboard') },
  { id: 'nav:ventas', label: 'Ir a Ventas', icon: '📈', action: () => switchView('ventas') },
  { id: 'nav:gastos', label: 'Ir a Gastos (resumen)', icon: '📄', action: () => switchView('gastos') },
  { id: 'nav:gastos-detalle', label: 'Ir a Detalle gastos', icon: '🧾', action: () => switchView('gastos-detalle') },
  { id: 'nav:alertas', label: 'Ir a Alertas', icon: '🔔', action: () => switchView('alertas') },
  { id: 'nav:config', label: 'Ir a Configuración', icon: '⚙️', action: () => switchView('config') },
  { id: 'act:chat', label: 'Abrir asistente AI', icon: '💬', action: () => { if (!$('#chatPanel').classList.contains('open')) $('#chatFab').click(); $('#chatText').focus(); } },
  { id: 'act:refresh', label: 'Refrescar datos', icon: '🔄', action: () => { loadAll(); toast('Datos refrescados', 'success'); } },
  { id: 'act:export-facturas', label: 'Exportar facturas a CSV', icon: '⬇️', action: () => window.location = '/api/export/facturas' },
  { id: 'act:export-proveedores', label: 'Exportar gastos por proveedor a CSV', icon: '⬇️', action: () => window.location = '/api/export/proveedores' },
  { id: 'act:export-categorias', label: 'Exportar gastos por categoría a CSV', icon: '⬇️', action: () => window.location = '/api/export/categorias' },
  { id: 'act:export-ingresos', label: 'Exportar ingresos a CSV', icon: '⬇️', action: () => window.location = '/api/export/ingresos' },
  { id: 'act:theme', label: 'Cambiar tema claro/oscuro', icon: '🌗', action: () => toggleTheme() },
  { id: 'act:help', label: 'Ver atajos de teclado', icon: '❓', action: () => openModal('helpModal') },
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
      const map = { d:'dashboard', v:'ventas', g:'gastos', a:'alertas', c:'config' };
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
  // refresh sync label cada minuto
  let syncMin = 0;
  setInterval(() => { syncMin++; $('#syncTime').textContent = syncMin===1?'hace 1 min':`hace ${syncMin} min`; }, 60000);

  loadAll().catch(e => {
    $$('.card-body, .kpis, .hero').forEach(el => { el.style.opacity=1; });
    $('#kpis').innerHTML = `<div class="state error" style="grid-column:1/-1"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg><div class="title">Error cargando datos</div><div class="desc">${esc(e.message)}</div><button class="seg" onclick="location.reload()">Reintentar</button></div>`;
  });
}

document.addEventListener('DOMContentLoaded', init);
