# Loop State — Liados / Desliado

Last run: 2026-07-06 (initial triage, L1 report-only)

## High Priority (loop is acting or waiting on human)

- **[P0] `docs/safety.md` está vacío.** El denylist referenciado por `AGENTS.md` y `LOOP.md` ("high-risk paths require human review") no tiene reglas. Acción humana: poblar el denylist con paths sensibles (credenciales, infra, deploy) antes de habilitar L2.
- **[P0] Gmail collector en `MISSING_TOKEN` (ambas cuentas).** `principal` y `secundaria` requieren reautorización OAuth. No bloquea el dashboard (Last.app lo alimenta), pero rompe el pipeline Gmail→invoices. Acción humana: `python3 -m agente.scripts.gmail_auth --account <cuenta> --force`.
- **[P0] `main` está 1 commit adelante de `origin/main` sin push.** El bootstrap `17ba733 loop-engineering: bootstrap daily-triage L3 (100/100)` es local-only. Por regla de AGENTS no se hace push sin aprobación humana. Acción humana: revisar y `git push` cuando proceda.
- **[P0] `STATE.md` tiene cambios no commiteados en el working tree.** El HEAD commiteado dice "# Loop State — My Project / Last run: never" — el contenido real de triage nunca llegó a un commit. Riesgo: el próximo `git checkout` o `git pull` podría sobrescribir el estado. Acción humana: revisar `git diff STATE.md` y commitear (sin push, según regla).

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

## Estado del repo (snapshot 2026-07-06)

- **Branch:** `main`, working tree tiene STATE.md modificado sin commit
- **HEAD local:** `17ba733 loop-engineering: bootstrap daily-triage L3 (100/100)` (no pusheado)
- **HEAD remoto:** `origin/main` 1 commit detrás
- **Tests E2E:** **62/62 PASS** (`tests/run_e2e.sh` → "Tests: 62 | PASS: 62 | FAIL: 0")
- **Dashboard:** v5.1.0, `systemctl is-active liados-dashboard` → `active`, `/api/health` → `{status:ok, db:ok, pool:{used:0, free:2}}`
- **Stack:** Python 3 + FastAPI 5.1.0 + Postgres 16 (nativo) + MinIO + OpenCode Go (LLM) + 2× MCP server (invoices + lastapp)
- **Deploy:** systemd `liados-dashboard.service` `:9121` + cron 03:00 (backup + E2E)
- **Loop runs históricos en `loop-run-log.md`:** 0 (este es el primero, no se ha añadido entrada al log todavía — acción humana o de un futuro run L2)

## Próximo run

Cuando el humano lo dispare, el loop debe:
1. Verificar si `docs/safety.md` ya tiene denylist poblado.
2. Comprobar si Gmail tokens se reautorizaron (¿`MISSING_TOKEN` persiste?).
3. Re-verificar que el commit `17ba733` ya está en `origin/main` (push humano).
4. Confirmar que el working tree de `STATE.md` quedó commiteado.
5. Re-correr E2E para confirmar 62/62 (puede subir si se mergean ramas stale).
6. Considerar merge o cierre de las 2 ramas remotas `feat/lastapp-*` (stale).

---

Run log: 2026-07-06 — L1 report-only, sin acciones de código, 0 sub-agent spawns, 0 tokens de sub-agent. Cambios a STATE.md pendientes de commit humano.
