# Loop State — Liados / Desliado

Last run: 2026-08-18 19:35 (L1+L2 combined: Excel workbook pusheado + E2E cron + backup cron reparados)

## Resolved (P0 fixed this session)

- **[P0] `docs/safety.md` vacío** → ✅ Commit `3d60cc8` con denylist específico del proyecto (12 paths críticos + 10 ops, allow-list, protocolo verificación, escalación).
- **[P0] `STATE.md` working tree sin commit** → ✅ Commit `3d60cc8` incluye STATE.md triage.

## High Priority (loop is acting or waiting on human)

- **[P0] Gmail collector en `MISSING_TOKEN` (ambas cuentas).** `principal` y `secundaria` requieren reautorización OAuth. No bloquea el dashboard (Last.app lo alimenta), pero rompe el pipeline Gmail→invoices. Acción humana: `python3 -m agente.scripts.gmail_auth --account <cuenta> --force`.
- **[P0] `main` con 2 commits sin push** → ✅ RESUELTO 2026-08-18 19:25, push a `origin/main` tras verificación 233/233 E2E PASS. SHA `33c823b` = HEAD local = HEAD remoto.
- **[P0] E2E cron roto por HTTPS + backup cron desaparecido** → ✅ RESUELTO 2026-08-18 19:31. Diagnóstico: dashboard HTTPS desde v9.0 PRO rompe `run_e2e.sh` HTTP; `/etc/cron.d/liados` perdió el job `backup_wrapper`. Fix: ambos crons reescritos, secuenciados 03:00 backup / 03:15 E2E con HTTPS explícito. Smoke test: backup `db-20260818-1931.sql.gz` 2.1 MB OK; E2E 233/233 PASS. Log e2e rotado. Log backup en `/var/log/liados-backup.log` (nuevo).
- **[P0] Working tree sucio (P&L estilo Excel + chart.js vendored + test E2E)** → ✅ RESUELTO 2026-08-18 19:25. Commit `33c823b feat(dashboard): P&L estilo Excel workbook`. Diff: 7 archivos, +414/-42. Pre-push verificado: 233/233 E2E PASS. Push a `origin/main` confirmado (SHA `33c823b` en `git ls-remote`).

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

- 8 backups `db-YYYYMMDD-0300.sql.gz` históricos en `backups/` (rotación OK, el `.gitignore` los excluye). Último: `db-20260706-0300.sql.gz` (hoy).
- Carpeta `agente/credentials/` y `data/` excluidas por `.gitignore` (correcto, no tocar). `.env` con perms 600 root:root (cumple CONTRIBUTING.md:65).
- `agente/scripts/test_*.py` y `tests/test_e2e.js` (legacy) — fuera de la suite oficial.
- `tests/test_browser4.py`, `tests/demo_flow.py`, `tests/test_chat_long.py` — verificado: tests E2E oficiales = `tests/run_e2e.sh` = **62 checks PASS** (no 58 como decía el STATE.md previo — corregido aquí).

---

## Estado del repo (snapshot 2026-07-06 07:42)

- **Branch:** `main`, working tree limpio tras commit `3d60cc8`
- **HEAD local:** `3d60cc8 fix(safety+state): poblar denylist Liados + STATE.md triage 2026-07-06`
- **HEAD remoto:** `origin/main` 2 commits detrás
- **Tests E2E:** **62/62 PASS** (`tests/run_e2e.sh` → "Tests: 62 | PASS: 62 | FAIL: 0")
- **Dashboard:** v5.1.0, `systemctl is-active liados-dashboard` → `active`, `/api/health` → `{status:ok, db:ok, pool:{used:0, free:2}}`
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
