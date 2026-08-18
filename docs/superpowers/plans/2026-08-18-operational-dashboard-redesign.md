# Liados Dashboard Operational Redesign Implementation Plan

> **For agentic workers:** Execute task-by-task with tests and a browser gate after each UI batch.

**Goal:** Convert the Liados dashboard into a clean, data-backed operational dashboard while preserving the Excel-style financial workbook structure.

**Architecture:** Keep the existing FastAPI endpoints and real-data calculation engines. Simplify the rendered navigation and dashboard view in `dashboard/app.py`, remove alert/last-invoice loading from the client, and restyle the workbook without changing its accounting contract. Every visible KPI must come from existing API data; unavailable accounting fields remain N/D.

**Tech Stack:** FastAPI HTML template, vanilla JavaScript, CSS tokens, PostgreSQL, Playwright, pytest.

## Global Constraints

- Canonical project is `/root/liados` on the VPS.
- Do not copy demonstration values from the videos into production data.
- Do not fabricate KPIs, alerts, invoices, testimonials or accounting fields.
- Preserve the five workbook sheets and monthly/YTD behavior.
- Keep `Alertas` out of the visible dashboard and stop loading its API from the initial client path.
- Keep the last-invoice endpoint available unless an API consumer requires removal; remove its visible card and client request.
- Use authenticated HTTP smoke, Playwright visual smoke and the existing Python suite before completion.
- Do not commit or push unless explicitly requested.

---

### Task 1: Remove noisy dashboard surfaces

**Files:**
- Modify: `dashboard/app.py` dashboard navigation and dashboard HTML.
- Modify: `dashboard/static/app.js` initial data loading and view navigation.
- Modify: `dashboard/static/app.css` obsolete card/layout styles only when they become unreachable.

- [ ] Remove the visible `Alertas` navigation item, alert badge and alert view from the dashboard UI.
- [ ] Remove `getJSON('/api/alertas')` from the initial badge/loading path and stop starting the alert refresh timer for the normal dashboard session.
- [ ] Remove the visible `Última factura extraída` card and its initial client request.
- [ ] Keep backend endpoints intact unless endpoint usage audit proves they are private dead code.
- [ ] Add an E2E assertion that the dashboard HTML has no visible alert navigation or last-invoice card.

### Task 2: Rebuild the operational home view

**Files:**
- Modify: `dashboard/app.py` dashboard home markup.
- Modify: `dashboard/static/app.js` home rendering.
- Modify: `dashboard/static/app.css` home layout.
- Test: `tests/test_e2e_dashboard.py`.

- [ ] Keep only real cards: net sales for the selected period, total expenses, EBITDA/margin, invoices pending classification, and source sync status.
- [ ] Replace any fake or ambiguous counters with explicit labels and source periods.
- [ ] Keep one monthly sales chart, one PYG expense distribution, one top-provider table and one data-quality block.
- [ ] Remove duplicate sales/gastos cards that repeat information without adding an action.
- [ ] Ensure every card has a loading, empty and error state.
- [ ] Verify cards render from live endpoints and never embed fixed sample amounts.

### Task 3: Simplify workbook presentation without changing accounting structure

**Files:**
- Modify: `dashboard/app.py` workbook markup.
- Modify: `dashboard/static/app.js` workbook controls.
- Modify: `dashboard/static/app.css` workbook presentation.
- Test: `tests/test_e2e_dashboard.py`.

- [ ] Remove the fake Excel title/ribbon/formula chrome that does not help the user.
- [ ] Keep the workbook body, row hierarchy, five sheet tabs, month selector, date range, YTD column, row expansion, cell selection and export.
- [ ] Present a compact header with only: `Cuenta de resultados`, `Desde`, `Hasta`, `Cuenta`, `Separar por mes`, `Actualizar`.
- [ ] Preserve the exact sheet names: `Resumen Ejecutivo`, `Evolución Mensual`, `Análisis Proveedores`, `Por Categorías`, `Hoja5`.
- [ ] Improve spacing, contrast, typography, frozen labels and responsive horizontal scrolling.
- [ ] Add E2E checks for direct workbook entry, month selection, sheet switching and filter preservation.

### Task 4: Data and interaction quality gate

**Files:**
- Modify: `tests/test_e2e_dashboard.py`.
- Modify: `tests/smoke_cuenta_resultados_http.py` if a new invariant is required.

- [ ] Assert all visible home KPIs have a source period and do not render placeholder sample values.
- [ ] Assert no alert API request is made during normal dashboard initialization.
- [ ] Assert no last-invoice API request is made during normal dashboard initialization.
- [ ] Assert workbook monthly parent channels reconcile with gross/net sales.
- [ ] Assert provider and category sheets retain real rows and N/D semantics.

### Task 5: Verification and runtime audit

- [ ] Run `pytest -q tests/test_cuenta_resultados.py tests/test_desglose_pyg.py tests/test_e2e_dashboard.py --browser chromium`.
- [ ] Run `python3 tests/smoke_cuenta_resultados_http.py`.
- [ ] Run authenticated Playwright screenshots at desktop 1600px and mobile 390px.
- [ ] Inspect screenshots against the approved screenshots and video reference.
- [ ] Verify `systemctl is-active liados-dashboard`, PID change after restart, HTTPS health 200, and public login 200/unauthenticated root 401.
- [ ] Run independent read-only review; fix every P0/P1 before reporting completion.
