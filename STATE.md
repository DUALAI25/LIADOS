# Loop State — Liados / Desliado

Last run: 2026-08-19 00:25 (L1 report-only)

## Resolved (P0 fixed this session)

- **[P0] `docs/safety.md` vacío** → ✅ Commit `3d60cc8` con denylist específico del proyecto (12 paths críticos + 10 ops, allow-list, protocolo verificación, escalación).
- **[P0] `STATE.md` working tree sin commit** → ✅ Commit `3d60cc8` incluye STATE.md triage.

## High Priority (loop is acting or waiting on human)

- **[P0] Gmail collector en `MISSING_TOKEN` (ambas cuentas).** `principal` y `secundaria` requieren reautorización OAuth. No bloquea el dashboard (Last.app lo alimenta), pero rompe el pipeline Gmail→invoices. Acción humana: `python3 -m agente.scripts.gmail_auth --account <cuenta> --force`.
- **[P0] `main` con 2 commits sin push** → ✅ RESUELTO 2026-08-18 19:25, push a `origin/main` tras verificación 233/233 E2E PASS. SHA `33c823b` = HEAD local = HEAD remoto.
- **[P0] E2E cron roto por HTTPS + backup cron desaparecido** → ✅ RESUELTO 2026-08-18 19:31. Diagnóstico: dashboard HTTPS desde v9.0 PRO rompe `run_e2e.sh` HTTP; `/etc/cron.d/liados` perdió el job `backup_wrapper`. Fix: ambos crons reescritos, secuenciados 03:00 backup / 03:15 E2E con HTTPS explícito. Smoke test: backup `db-20260818-1931.sql.gz` 2.1 MB OK; E2E 233/233 PASS. Log e2e rotado. Log backup en `/var/log/liados-backup.log` (nuevo).
- **[P0] Working tree sucio (P&L estilo Excel + chart.js vendored + test E2E)** → ✅ RESUELTO 2026-08-18 19:25. Commit `33c823b feat(dashboard): P&L estilo Excel workbook`. Diff: 7 archivos, +414/-42. Pre-push verificado: 233/233 E2E PASS. Push a `origin/main` confirmado (SHA `33c823b` en `git ls-remote`).

## High Priority (loop is acting or waiting on human)

- **[P0] Working tree sucio — 4 archivos modificados a 22:00 Aug 18, sin commit.** Commit `83342e7` (Jarvis 21:50) consolidó TEST_CAT_DEL + vendor fuzzy match. Una edición posterior (otra sesión de agente, 22:00) **borró Hoja5 + ribbon + formula bar + cr-row-num + cr-col-letters** del workbook P&L, simplificándolo a 4 hojas. Diff: `dashboard/app.py` -16/+5, `app.css` +50/-22, `app.js` +24/-44, `test_e2e_dashboard.py` +3/-3. **Revierte parcialmente el diseño Excel** commiteado en `33c823b`. `py_compile` OK. No toca paths protegidos. Decisión humana: commit + push (recomendado: `--no-ff` para preservar trazabilidad) o `git checkout --` para descartar. Test E2E cron ya validaría solo `test_api.py` (no Playwright); la modificación de `test_11_excel_workbook_sheets_and_mobile_drawer` solo se valida con playwright manual.
- **[P0] Gmail collector en `MISSING_TOKEN` (ambas cuentas).** Vigente. No bloquea dashboard, sí pipeline Gmail→invoices. Acción humana: `python3 -m agente.scripts.gmail_auth --account <cuenta> --force`.

## Watch List

- **[P1] `lastapp_sync.py` (DEPRECATED) coexiste con `lastapp_server.py` (MCP oficial).** Riesgo de confusión. Confirmar cuál invoca el cron / `run_all`. La rama `feat/lastapp-integration` aún modifica `lastapp_sync.py` (commit `27ac26b`) — puede ser merge conflictivo con main si se mergea.
- **[P1] 2 ramas remotas `feat/lastapp-*` están stale (detrás de main).** `git log main..origin/feat/lastapp-integration` está vacío; idem `feat/lastapp-official-mcp`. Decisión humana: rebase o cerrar.
- **[P1] `loop-ledger.json` referenciado en `loop-constraints.md:21` no existe.** Sin enforcement mecánico del límite de 3 intentos. Crear antes de habilitar L2.
- **[P1] Sin CI formal** (`.github/workflows/` ausente). E2E corre solo vía cron 03:00 (`/etc/cron.d/liados-e2e`). No hay status badge ni PR checks.
- **[P1] 6 scripts en `scripts/` sin documentar.** `analytics_pull.py`, `analytics_pull_v2.py`, `derive_analytics.py`, `analytics_final.py`, `lastapp_full_pull.py`, `ingest_lastapp.py`. Verificar si están en uso o son legacy (probablemente superseded por `agente/scripts/`).
- **[P1] Deuda técnica ya conocida** (`CONTRIBUTING.md:57-61`): `open_support_ticket` sin tool remota, `top_products` con args vacíos, `weekly_summary.py` con prints, HTTPS no configurado (depende de reverse proxy externo).

## Cleanup (no rush)

- **[P2] `agente/mcp/lastapp_server.py.bak.c16` (15 KB, 1 jul).** Backup obsoleto. **Ya está cubierto por `.gitignore:33` (`*.bak.*`)** — NO es riesgo de commit accidental (verificado con `git check-ignore -v`). Acción opcional: borrar manualmente.

## Recent Noise (ignored this run)

- 8 backups `db-YYYYMMDD-0300.sql.gz` históricos en `backups/` (rotación OK, el `.gitignore` los excluye). Último: `db-20260818-1931.sql.gz` (2.2 MB, del smoke test post-fix 19:31). Pendiente: el primer backup automático real será 03:00 hoy (19-aug).
- Carpeta `agente/credentials/` y `data/` excluidas por `.gitignore` (correcto, no tocar). `.env` con perms 600 root:root (cumple CONTRIBUTING.md:65).
- `agente/scripts/test_*.py` y `tests/test_e2e.js` (legacy) — fuera de la suite oficial.
- `tests/test_browser4.py`, `tests/demo_flow.py`, `tests/test_chat_long.py` — verificado: tests E2E oficiales = `tests/run_e2e.sh` = **233 checks PASS** (test_api.py).

---

## Estado del repo (snapshot 2026-08-19 00:25)

- **Branch:** `main`, working tree **sucio con 4 archivos no commiteados** (post-commit 83342e7)
- **HEAD local:** `83342e7 feat(dashboard): filtro TEST_CAT_DEL, CTE channel_rows prorrateado, vendor fuzzy match, docs/superpowers`
- **HEAD remoto:** `git ls-remote` falló por host key verification hoy (`Host key verification failed`). SSH a GitHub necesita aceptar fingerprint o regenerar known_hosts. ANTES del fallo: 8f14585 (19:33 Aug 18) era HEAD remoto; 83342e7 (21:50 Aug 18) **puede estar sin push**.
- **Tests E2E:** **233/233 PASS** en último run (21:50 Aug 18, log `.log.1`). El log `.log` actual está en 0 bytes porque logrotate rotó a 00:00 hoy; próximo run programado 03:15.
- **Dashboard:** v9.0.0, `systemctl is-active liados-dashboard` → `active`, `/api/health` → `{status:ok, db:ok, pool:{used:0, free:2}, version:9.0.0}`
- **Stack:** Python 3 + FastAPI 5.1.0 + Postgres 16 (nativo) + MinIO + OpenCode Go (LLM) + 2× MCP server (invoices + lastapp)
- **Deploy:** systemd `liados-dashboard.service` `:9121` + cron 03:00 (backup + E2E)
- **Loop Engineering:** L3 (100/100), tool=opencode, pattern=daily-triage, opencode CLI v1.17.13 disponible en VPS
- **Safety:** denylist poblado (12 paths + 10 ops), allow-list definido, protocolo verificación L2 documentado
- **Loop runs históricos en `loop-run-log.md`:** 1 (este). Pendiente: añadir entrada al run log en próximo run.

---

## Verification run 2026-08-18 (L1+L2 combinado)

- L1+L2 ejecutados bajo autorización humana explícita (jefe: "hazlo pero asegurate de no romper nada").
- Cambios commiteados y pushados: `33c823b feat(dashboard): P&L estilo Excel workbook (5 hojas) + CSP self-hosted + chart.js vendored + test E2E` (HEAD `main` = `33c823b`).
- Crons reparados: `/etc/cron.d/liados-e2e` ahora usa `https://localhost:9121` y corre a 03:15; `/etc/cron.d/liados` restaurado con `backup_wrapper.py` corriendo a 03:00. Logs separados: `/var/log/liados-e2e.log` (rotado hoy) y `/var/log/liados-backup.log` (nuevo).
- Smoke test post-fix: backup `db-20260818-1931.sql.gz` 2.1 MB OK; E2E 233/233 PASS via `run_e2e.sh https`; dashboard `/api/health` 200 v9.0.0; cron daemon activo.
- Gmail age: log estancado en 2026-08-10 — el cron `liados-gmail-age` debería haber escrito el 2026-08-11..18 pero no lo hizo. Misma causa probable (HTTPS + cambios de schedule). **Pendiente investigar** en próximo run.

Run log: L1+L2 (2026-08-18). 3 P0 cerrados (Excel commit, E2E cron, backup cron). Pendiente: Gmail age cron, OAuth Gmail reauth manual, ramas feat stale.

---

## Verification run 2026-08-19 00:25 (L1 report-only)

- L1 ejecutada por agente cron (modo report-only, sin ediciones de código, sin push, sin reinicios).
- **Hallazgo crítico:** working tree sucio con 4 archivos (post-commit 83342e7 de 21:50 Aug 18). Sesión de agente posthoc (22:00 Aug 18) eliminó Hoja5 + ribbon chrome + formula bar + cr-row-num + cr-col-letters del workbook P&L, simplificándolo a 4 hojas pero **sin commit**. Decisión humana: commit + push o `git checkout --` para descartar.
- **Smoke test E2E live:** 233/233 PASS en último run real (21:50 Aug 18, log `.log.1`). Mi run manual dio 232/233 — 1 fallo `Permission denied: '.env'` esperable porque mi usuario es `hermes-liados` (uid 999) y `.env` es 600 root:root. Cron E2E corre como root, **no afecta** al cron path.
- **SSH a GitHub roto:** `git ls-remote origin` falla con `Host key verification failed`. Imposible saber si 83342e7 está pusheado. Necesita intervención humana: `ssh -o StrictHostKeyChecking=accept-new github.com` o aceptar fingerprint en `~/.ssh/known_hosts`.
- **Otros crons:** backup cron 03:00 hoy (primer run automático real); E2E cron 03:15 hoy; oauth-watchdog hourly OK; gmail-age 08:00 (sin escribir desde 2026-08-10, gap documentado).
- **Sin procesos huérfanos**, sin restarts anómalos, memoria dashboard 71.9 MB estable, uptime desde 22:00 Aug 18.

Run log: L1 (2026-08-19). 0 P0 cerrados. 1 P0 nuevo (working tree sucio post-commit). 1 P0 vigente (Gmail OAuth). Pendiente: commit/discard del working tree, arreglar SSH known_hosts, reautorizar Gmail, ramas feat stale.

---

## Verification run 2026-08-19 05:43 (L1 report-only)

- L1 ejecutada por agente cron (modo report-only, sin ediciones de código, sin push, sin reinicios).
- **Working tree sigue sucio** (4 archivos, mtime 22:00 Aug 18, sin commit). Diff vs `83342e7`:
  - `dashboard/app.py`: -7 líneas (borra bloque `cr-formula-row`, botón `cr-sheet-nav`, tab `Hoja5`, span `cr-sheet-add`, span `cr-zoom`, div `cr-statusbar`).
  - `dashboard/static/app.css`: 28 líneas cambiadas — paleta `--holded-surface` cambia de `#ffffff` a `#f2f5f9` (gris Holded más oscuro); fondos de `.cr-workbook`, `.cr-meta-line`, `.cr-grid-shell`, `.cr-table`, `.cr-toolbar`, `.cr-sheetbar`, `.cr-sheet-tab` pasan de blanco a gris; `.seg/select/input` añaden background gris + color texto.
  - `dashboard/static/app.js`: -16/+24 (revierte `crRenderRow` a 3 params sin `rowNumber`, elimina `td.cr-row-num`, elimina `data-formula`, simplifica `crTableHead` a 1 fila `cr-head-month`, elimina `crBlankSheet`, elimina handler `'hoja5'`, elimina handlers de selección de celda para `cr-name-box`/`cr-formula`).
  - `tests/test_e2e_dashboard.py`: -2/+3 (saca `"Hoja5"` del array de sheets, añade aserciones `cr-row-num.count()==0` y `cr-col-letters.count()==0`, añade aserción `finance-overview bgColor rgb(242,245,249)`).
- **Causa aparente:** sesión posthoc (no humana) editó a las 22:00 Aug 18 simplificando el workbook Excel a 4 hojas + paleta Holded más oscura, sin commit. Posible origen: sesión nocturna de OpenCode CLI sin prompt explícito.
- **Crons automáticos nocturnos OK:**
  - 03:00 backup: `db-20260819-0300.sql.gz` 2.2 MB, log `BACKUP OK: 2.1 MB` (`/var/log/liados-backup.log`).
  - 03:15 E2E: **233/233 PASS** contra `main` (HEAD `83342e7`), `RESULT: PASS` en `/var/log/liados-e2e.log` (20 KB, 631 líneas).
- **SSH a GitHub sigue roto** (`Host key verification failed`) — no se puede verificar push de `83342e7` mediante `git ls-remote`. Las ramas remotas están en `.git/refs/remotes/origin/` cacheadas; última actualización de esas refs no documentada.
- **Watchdog systemd timers OK:** `liados-watchdog.timer` y `liados-tunnel-tracker.timer` activos (cada 1min / 5min respectivamente). `run_all.py` ejecutado por systemd a 05:30 con todos los bloques OK (Last.app 0.9s, Gmail 1.6s, Drive 7.5s). `Gmail collector` no devuelve `MISSING_TOKEN` (log dice `[INFO] Gmail collector OK (1.6s)`) — esto contradice STATE.md previo que reportaba MISSING_TOKEN. **Verificar**: ¿el watchdog oauth reporta 3/3 OK pero el run_all real ejecuta Gmail sin error? Probable: el token `MISSING_TOKEN` se refería a la fase de validación previa al reauth; el Gmail collector puede operar hasta que el refresh falle. Acción: humana confirma estado de tokens con `check_gmail_token_age.py` y `oauth_watchdog.py --verbose`.
- **Dashboard health OK:** `/api/health` 200 `{"status":"ok","version":"9.0.0","checks":{"database":"ok","pool":{"used":0,"free:2}}}`. Uvicorn 7h42m uptime. Proxy 9122 activo. `/login` 200, `/static/app.js` 200.
- **`/api/cuenta_resultados` 404** — confirmado: el endpoint correcto es `/api/gastos/cuenta-resultados` (no documentado en `/api/health`). No es bug; el triage intentó ruta incorrecta.
- **Tunnel tracker:** última URL `https://baby-org-weight-dave.trycloudflare.com` con `healthy: false` (timestamp 2026-08-18T18:35). El watchdog systemd timer está activo pero la URL reportada es de hace 11h — puede indicar que el tracker no se ha ejecutado o que la URL no responde. Verificar con `journalctl -u liados-tunnel-tracker --since today`.

Run log: L1 (2026-08-19 05:43). 0 P0 cerrados. 2 P0 vigentes: working tree sucio + Gmail OAuth. 1 P0 escalado: SSH known_hosts a GitHub. Pendiente: commit/discard del working tree (decisión humana), arreglar SSH fingerprint, reautorizar Gmail, validar tunnel URL.

---

## Verification run 2026-08-19 10:45 (L1 report-only)

- L1 ejecutada por agente cron (modo report-only, sin ediciones de código, sin push, sin reinicios).
- **Working tree ACTUALIZADO — pasa de "simplificar P&L" a "PYG v2 + impuesto 25% + SGG real + drilldown proveedores".** 5 archivos, +347/-65, mtimes 08:28–10:38 Aug 19. Diff vs HEAD `de0b244`:
  - `dashboard/desglose_pyg_rules.py` (+226/-65): reescrito a v2 con buckets reales del cliente (Suministros, Servicios Profesionales, Alquiler, Gastos Bancarios, Seguros, Impuestos y Tasas, Oficina, Software y SaaS) y comentario expandido con sub-nodos.
  - `dashboard/cuenta_resultados.py` (+50/-18): `net_before` → `net_after` (ventas post-descuento) en todas las ratios; `_real_category_split` ahora acumula positivo (gasto real); EBITDA ya no resta `sgg_total` (porque `other` ya lo tiene restado); `impuesto_sociedades` calculado al 25% sobre resultado_antes_impuestos (era 0); sección "Otros gg. producción" ahora es `section=True` con drill-down de top 30 proveedores reales vía `_all_real_vendors`; `_all_real_vendors()` helper añadido; issue `impuesto_sin_datos` reemplazado por `impuesto_sociedades_25` (info).
  - `dashboard/app.py` (+33/-0): nuevo endpoint `/api/gastos/csv-reference` que lee `gastos-categorias.csv` (12 categorías) como comparativa histórica con la BD.
  - `tests/test_cuenta_resultados.py` (+18/-2): test_monthly_ytd ahora valida impuesto_sociedades = resultado_antes_impuestos × 0.25 si > 0; test_accounting_rows quita aserción rígida de impuesto_sociedades=0 y la hace condicional.
  - `?? dashboard/gastos-categorias.csv` (318 B, 12 categorías: Suministros 244 fact/87k€, Restauración 67/20k€, etc. — histórico de comparación). **NO debería estar en el repo: es data de referencia, no código fuente.**
- **HEAD:** `de0b244 fix(pyg): SGG extraido de facturas reales + anti doble-contabilizacion + keywords OR` (Jarvis 08:14). El árbol de trabajo contiene los siguientes commits sin push: `5d150ea feat(pyg): jerarquia completa`, `de0b244 fix(pyg): SGG extraido + anti doble-contabilizacion`. Ambos commiteados por Jarvis hoy 08:14 Aug 19 — `5d150ea` está en `main..HEAD` sin push (verificado: `git log origin/main..HEAD` no aplicable por SSH roto, pero cache de refs confirma `origin/main` en `8f14585` y HEAD local en `de0b244`).
- **Sesión posthoc otra vez:** el árbol contiene trabajo substancial de PYG no humano (entre 08:14 y 10:38). El CSV histórico `gastos-categorias.csv` subido al árbol sugiere un agente con acceso write está operando fuera del protocolo humano-gated.
- **Verificación segura (read-only) ejecutada por este run:**
  - `py_compile` los 4 archivos modificados → EXIT=0.
  - `pytest tests/test_cuenta_resultados.py` → **6/6 PASS** (incluye las aserciones nuevas del 25% IS).
  - `curl /api/gastos/csv-reference` → 401 (requiere auth, esperado; el endpoint existe y responde).
- **Crons automáticos nocturnos OK:**
  - 03:00 backup: `db-20260819-0300.sql.gz` 2.24 MB, log `BACKUP OK: 2.1 MB`.
  - 03:15 E2E: **233/233 PASS** contra `de0b244`, log `Tests: 233 | PASS: 233 | FAIL: 0`.
  - 08:00 gmail-age: tokens 23.0d (production, <90d WARN / <180d CRIT) → **OK ambos**.
  - 10:30 drive: secundaria falla con `Drive token no OK para secundaria: missing` (esperado, no es error).
- **OAuth tokens OK 3/3** (último watchdog 10:00: gmail:principal, gmail:secundaria, drive:principal). Gmail collector **NO está en MISSING_TOKEN** — corre OK. STATE.md previo (línea 12, 20) era incorrecto: los tokens están vivos, lo que fallaba era el flujo de validación previa. **Esto RESUELVE el P0 "Gmail collector MISSING_TOKEN"** — los tokens tienen 23 días, están operativos.
- **Dashboard health OK:** `/api/health` 200, v9.0.0. Uvicorn uptime ~33 min (reiniciado por watchdog 10:12 tras el run de tests). Memoria 99 MB estable.
- **SSH a GitHub sigue roto** (`Host key verification failed`). Imposible saber si `de0b244` y `5d150ea` están pusheados a `origin/main`.
- **Ramas stale (sin cambios desde último run):**
  - `origin/feat/dashboard-v6-premium` (40 ahead, 5 behind) — sigue stale.
  - `origin/feat/lastapp-official-mcp` (96 ahead, 0 behind, sin actividad) — sigue stale.
  - `origin/feat/lastapp-integration` — referencia eliminada localmente.

Run log: L1 (2026-08-19 10:45). 0 P0 cerrados. 1 P0 vigente: working tree con 5 archivos (más grande y más reciente que en el run 05:43 — sesión posthoc continúa). 1 P0 escalado: SSH known_hosts. 1 P0 resuelto: Gmail OAuth era falso positivo, tokens OK. Pendiente crítico: revisar y gate de la sesión posthoc no humana; commit + push con aprobación humana; arreglar SSH fingerprint para verificar push de los 2 commits PYG.
