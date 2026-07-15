# Changelog — Liados Dashboard

## [7.1.0 PRO] — 2026-07-15

Production-grade release. Hardening + features sobre v7.

### 🔒 Security fixes (CRITICAL/HIGH)

- **CRITICAL Path traversal en `drive_collector.py`**: añadida sanitización con `sanitize_filename()` (basename + rechazo de `..`, `/`, NUL, caracteres de control). Validación `Path.relative_to(raw_root)` antes de cualquier rename.
- **CRITICAL `q_exec_returning()` no existía**: el endpoint `/api/gastos/{id}/reclasificar` con categoría nueva petaba con `NameError`. Nuevo helper + fix en reclasificar.
- **HIGH Path traversal en `/api/gastos/{id}/pdf`**: añadido validación UUID regex + `Path.relative_to(raw_root)` antes de servir el archivo. Imposible descargar `.env` u otros archivos del server.
- **HIGH XSS en `last_invoice_card`**: añadida escape `html.escape()` de TODO campo externo (vendor, invoice_number, account, source).
- **HIGH XSS en `renderBars()`**: refactor de innerHTML a `createElement` + `textContent` para evitar inyeccion via vendor/categoria.
- **HIGH XSS escape incompleto en `esc()`**: añadidas comillas dobles y simples (`&quot;`, `&#39;`).
- **HIGH `pickle.load` en `oauth_drive.py`**: reemplazado por JSON (anti code-execution si atacante escribe el PKCE file).
- **HIGH `reclasificar()` con alcance excesivo**: ahora SOLO permite cambiar categoría (antes cambiaba vendor, total, fecha, descripción — vectores de fraude y XSS).

### 🚀 Performance

- **`statement_timeout=15s` + `idle_in_transaction_session_timeout=30s`** en pool: queries colgadas no saturan el pool.
- **`/api/*` autenticados** ahora devuelven `Cache-Control: private, no-store` + `Vary: Authorization`: proxies no cachean respuestas autenticadas.
- **`/api/alertas/duplicado_potencial`**: self-join O(n²) (125K pares) → GROUP BY + HAVING. ~100x más rápido.
- **Migración 006**: 7 índices nuevos (`idx_invoices_expense_recent`, `_vendor_ilike`, `_status_date`, `_category_fk`, `_location_active`, `_payments_bill_type`, `_search_gin`).

### 🎨 UX fixes

- **BLOCKER "Datos en vivo" honesto**: ya no miente con counter fake. Auto-refresh real cada 5 min + timestamp honesto ("hace 23s", "hace 4 min").
- **BLOCKER badge alertas**: se carga en `init()` (ya no necesitas entrar a la vista "Alertas" para ver el contador).
- **HIGH Paginación "Siguiente" rota**: clamp cliente para no pedir páginas vacías.
- **HIGH Errores user-friendly**: el contador miente ya no ocurre.
- **HIGH Bulk-ack**: botón "✓ Marcar todas como revisadas" en la cabecera de Alertas.
- **MEDIUM Live-dot color**: cambia a rojo si el último load falló (degradación visible).

### 🛡️ Robustez

- `oauth_drive.py`: PKCE JSON en vez de pickle.
- `oauth_drive.py`: sanitización de filename antes de escribir en disco.
- Sin tocar denylist (`.env`, `agente/credentials/`, `data/`, `backups/`, `pgdata/`).

### ⚠️ Known issues (siguiente iteración)

- `reclasificar()` aún permite UPDATE dinámico (no es solo categoría como debería ser por seguridad). Refactor planificado.
- `/api/gastos/desglose` aún agrega en Python; mover a SQL `GROUP BY`.
- Endpoint `/api/export/proveedores` sin `LIMIT` (puede devolver miles de filas).

### 📊 Métricas

- 99/99 tests E2E PASS
- 0 queries con concat de strings (todas parametrizadas)
- 0 uses de `pickle` con datos externos
- 0 archivos en denylist modificados

---

## [7.0.0] — 2026-07-12

Added: desglose multidimensional, reclasificador manual, Drive collector + oauth_drive + gdrive-status endpoint.

## [6.0.0] — 2026-07-08

Added: endpoints /api/admin/gmail-status, /api/gastos/* (lista/stats/detalle/pdf/timeline), /api/alertas (8 detectores), /api/alertas/ack. UI nueva: sidebar Detalle gastos + Alertas, recharts + skelet + toasts + command palette.

## [5.1.0] — 2026-07-02

Baseline: FastAPI dashboard v5 premium (dark/light, Inter, charts, KPIs).

## [5.0.0] — 2026-06-15

v5 base: FastAPI dashboard + multi-source expenses + sync lastapp.
