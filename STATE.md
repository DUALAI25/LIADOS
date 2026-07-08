# Loop State — Liados / Desliado

Last run: 2026-07-08 (v6 premium completo en feat/dashboard-v6-premium, commit 313be17)

## Resolved (v6 premium — feat/dashboard-v6-premium, commit 313be17)

### Entregable A — Limpieza técnica
- **[P1] 786 facturas huérfanas `sin-local` en `/api/locales`.** → ✅ Migración `db/migrations/005_fix_sin_local.sql` aplicada: las 786 facturas de `Vamos al lío S.L.` (2026-06-17 → 2026-07-07) ahora tienen `location_id = a8f15efa-...` asignado. Auditoría en `_migration_005_audit` (786 rows). Post-migración: 0 huérfanos. `/api/locales` ahora devuelve 1 local consolidado con 8757 facturas / 254.382€. Migración idempotente + 2 índices nuevos (`idx_invoices_expense_filters`, `idx_invoices_vendor_lower`).
- **[P1] `loop-ledger.json` inexistente.** → ✅ Creado con schema `{attempts: {<item_id>: [{ts,action,result,hash}]}}`. `scripts/loop_guard.py` (124 líneas) implementa `check|log|reset|status`. Enforcement mecánico del límite de 3 intentos operativo (test verificado: 3 log → check devuelve BLOCK con exit 1).
- **[P1] 6 scripts legacy en `scripts/` sin documentar.** → ✅ Movidos a `scripts/_legacy/` con `README.md` explicativo. Verificado: ninguno referenciado desde cron/systemd/imports.
- **[P1] Confusión `lastapp_sync.py` vs `lastapp_server.py`.** → ✅ Aclarado en este STATE.md: NO son el mismo concepto. `lastapp_sync.py` = sync de datos (lo usa `run_all.py`). `lastapp_server.py` = MCP server para chat agent. Ambos vivos, NO se deprecó nada.
- **[P2] `agente/mcp/lastapp_server.py.bak.c16`.** → Confirmado cubierto por `.gitignore:33` (`*.bak.*`).

### Entregable B — Gmail status (read-only)
- Nuevo endpoint `GET /api/admin/gmail-status`. **Nunca expone tokens** (test verifica que `"refresh_token"`, `"access_token"`, `"client_secret"` no aparecen en la respuesta JSON). Solo metadatos: `client_id` truncado, `scope`, `issued_at`, `last_check`, `age_days`, `has_*_token` (booleans). Resolución robusta de credentials dir (ENV > CWD > package-relative > /root/liados fallback).
- Vista Configuración muestra estado de cada cuenta + accordion con comandos exactos de reauth cuando MISSING_TOKEN/STALE.
- **P0 Gmail sigue activo**: `principal` OK, `secundaria` MISSING_TOKEN. Reauth requiere navegador humano (denylist). Comandos en `Configuración → cuenta secundaria → Reautorizar`.

### Entregable D1 — Gastos desglosados
- 5 endpoints nuevos: `/api/gastos` (paginado + 7 filtros combinables + facets), `/api/gastos/stats`, `/api/gastos/{id}` (detalle completo con pagos + pdf_exists), `/api/gastos/{id}/pdf` (FileResponse, Content-Disposition), `/api/gastos/timeline/groups` (heatmap calendar).
- UI: vista "Detalle gastos" con 5 stats globales, filtros con datalist de vendors, tabla paginada con sort por columnas clickables, modal detalle con importes desglosados, categoría colorida, badge de status, **descarga PDF inline**, link "Abrir en chat AI" (precarga factura en chat).

### Entregable D2 — Alertas IA
- Nuevo endpoint `GET /api/alertas`: detector SQL de **8 tipos** de anomalías (venta_caida MoM, canal_ausente, gasto_pico, factura_sin_categoria, sync_stale, facturas_sin_pdf, locales_huerfanos, duplicado_potencial). Severidad high/medium/low/info. Ordenadas por severidad.
- UI: vista "Alertas" con cards por severidad, **badge en sidebar** (contador high+medium), dismiss con TTL 24h (localStorage), CTA "Abrir en chat AI" con prefill de contexto, auto-refresh cada 60s.

### Entregable C — Premium polish
- Skeleton loaders con shimmer animation.
- Toast notifications (success/error/warn/info) con auto-dismiss y queue.
- Focus-visible WCAG 2.1 AA en todos los interactivos.
- Command palette (Ctrl/⌘+K) con 14 comandos (navegación + acciones + exports).
- Keyboard shortcuts Gmail-style: **G+D/V/G/A/C**.
- `@media (prefers-reduced-motion)` y `@media print`.

### Tests
- **99/99 PASS** (62 originales + 37 nuevos). Cubre estructura, auth 401, 404, filtros, no-leak de tokens, descarga PDF, validación de severidad/tipo/descripcion en alertas.

### Version
- Dashboard: 5.1.0 → **6.0.0** (`/api/health.version`).

## Pendiente para Antonio (acción humana requerida)

1. **Push a `origin/main`**: rama `feat/dashboard-v6-premium` con commit `313be17`. Por safety.md, NO se ha pusheado automáticamente. Comandos:
   ```bash
   cd /root/liados
   git fetch /tmp/worktree-dashboard-v6 feat/dashboard-v6-premium
   # Revisar diff con: git diff main..feat/dashboard-v6-premium --stat
   git checkout feat/dashboard-v6-premium
   git push -u origin feat/dashboard-v6-premium
   # PR: abrir en GitHub (no hay gh CLI en el VPS)
   ```

2. **Deploy a producción**: el dashboard actual sigue en v5.1.0 (puerto 9121). Para actualizar:
   ```bash
   cd /root/liados
   git checkout main
   git merge feat/dashboard-v6-premium   # o rebase
   systemctl restart liados-dashboard
   ```

3. **Gmail OAuth `secundaria`**: ejecutar reauth manual (3 comandos en `Configuración → Reautorizar`).

4. **Decisión ramas stale `feat/lastapp-*`**: rebase o cerrar (siguen detrás de main).

## Watch List (sin cambios)

- **[P1] Sin CI formal** (`.github/workflows/` ausente). E2E solo vía cron 03:00.
- **[P1] Deuda técnica ya conocida** (`CONTRIBUTING.md:57-61`): `open_support_ticket` sin tool remota, `top_products` con args vacíos, `weekly_summary.py` con prints, HTTPS no configurado.

---

## Estado del repo (snapshot 2026-07-08 08:04)

- **Branch:** `feat/dashboard-v6-premium` (worktree en `/tmp/worktree-dashboard-v6`)
- **HEAD:** `313be17 feat(dashboard): v6 premium...`
- **Tests E2E:** **99/99 PASS** (`tests/test_api.py`)
- **Dashboard:** v6.0.0 en servidor de test (9122, ya parado). v5.1.0 en producción (9121) — actualizar tras merge.
- **Loop Engineering:** L3 (100/100), tool=opencode, pattern=daily-triage
- **Safety:** verificada. Ningún path denylist tocado. Migración 005 idempotente.
- **Push:** NO realizado (requiere OK humano explícito por safety.md).
