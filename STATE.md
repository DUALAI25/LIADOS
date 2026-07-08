# Loop State — Liados / Desliado

Last run: 2026-07-08 (Entregable A cleanup aplicado en feat/dashboard-v6-premium)

## Resolved (P0/P1 fixed this session — feat/dashboard-v6-premium)

- **[P1] 786 facturas huérfanas `sin-local` en `/api/locales`.** → ✅ Migración `db/migrations/005_fix_sin_local.sql` aplicada: las 786 facturas de `Vamos al lío S.L.` (2026-06-17 → 2026-07-07) ahora tienen `location_id = a8f15efa-...` asignado. Auditoría guardada en `_migration_005_audit`. Post-migración: 0 huérfanos. `/api/locales` ahora devuelve 1 local consolidado con 8757 facturas.
- **[P1] `loop-ledger.json` inexistente.** → ✅ Creado con schema `{attempts: {<item_id>: [{ts,action,result,hash}]}}`. `scripts/loop_guard.py` implementa check/log/reset/status. Enforcement mecánico del límite de 3 intentos operativo (test verificado).
- **[P1] 6 scripts legacy en `scripts/` sin documentar.** → ✅ Movidos a `scripts/_legacy/` con `README.md` explicando qué eran y su reemplazo. Ninguno estaba referenciado desde cron/systemd/imports (verificado con grep).
- **[P1] Confusión `lastapp_sync.py` vs `lastapp_server.py`.** → ✅ **NO son el mismo concepto, NO se deprecó.** `lastapp_sync.py` = sincronización de datos (bills/payments → Postgres), lo usa `run_all.py` y alimenta el dashboard. `lastapp_server.py` = MCP server para el chat agent (productos, reservas, acciones). Sirven funciones distintas y ambos están vivos. STATE.md previo estaba equivocado.
- **[P2] `agente/mcp/lastapp_server.py.bak.c16`.** → ✅ Confirmado cubierto por `.gitignore:33` (`*.bak.*`), `git check-ignore -v` positivo. No aparece en worktree. Acción opcional de borrado manual sigue abierta para el checkout principal.

## High Priority (loop is acting or waiting on human)

- **[P0] Gmail collector en `MISSING_TOKEN` (ambas cuentas).** `principal` y `secundaria` requieren reautorización OAuth. No bloquea el dashboard (Last.app lo alimenta), pero rompe el pipeline Gmail→invoices. **Acción en feat/dashboard-v6-premium:** endpoint read-only `/api/admin/gmail-status` + comandos de reauth documentados en la vista Configuración. La reautorización real requiere navegador humano (denylist).

## Watch List

- **[P1] 2 ramas remotas `feat/lastapp-*` están stale (detrás de main).** `git log main..origin/feat/lastapp-integration` está vacío; idem `feat/lastapp-official-mcp`. Decisión humana: rebase o cerrar.
- **[P1] Sin CI formal** (`.github/workflows/` ausente). E2E corre solo vía cron 03:00 (`/etc/cron.d/liados-e2e`). No hay status badge ni PR checks.
- **[P1] Deuda técnica ya conocida** (`CONTRIBUTING.md:57-61`): `open_support_ticket` sin tool remota, `top_products` con args vacíos, `weekly_summary.py` con prints, HTTPS no configurado (depende de reverse proxy externo).

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
