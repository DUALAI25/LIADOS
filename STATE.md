# Loop State — Liados / Desliado

Last run: 2026-07-06 07:42 (P0-1 + P0-3 resueltos)

## Resolved (P0 fixed this session)

- **[P0] `docs/safety.md` vacío** → ✅ Commit `3d60cc8` con denylist específico del proyecto (12 paths críticos + 10 ops, allow-list, protocolo verificación, escalación).
- **[P0] `STATE.md` working tree sin commit** → ✅ Commit `3d60cc8` incluye STATE.md triage.

## High Priority (loop is acting or waiting on human)

- **[P0] Gmail collector en `MISSING_TOKEN` (ambas cuentas).** `principal` y `secundaria` requieren reautorización OAuth. No bloquea el dashboard (Last.app lo alimenta), pero rompe el pipeline Gmail→invoices. Acción humana: `python3 -m agente.scripts.gmail_auth --account <cuenta> --force`.
- **[P0] `main` está 2 commits adelante de `origin/main` sin push.** Commits nuevos: `17ba733 loop-engineering: bootstrap daily-triage L3 (100/100)` + `3d60cc8 fix(safety+state): poblar denylist Liados + STATE.md triage`. Por regla de safety.md, push requiere aprobación humana explícita.

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

Run log: L1 report-only (2026-07-06 07:42). Sin auto-fix L2 (pendiente habilitar tras resolver P0 Gmail tokens + decisión push).
