# Loop Run Log — YOUR_PROJECT

Append one entry per run. Prune entries older than 30 days.

## Format

```json
{
  "run_id": "2026-06-09T08:15:00Z",
  "pattern": "daily-triage",
  "duration_s": 45,
  "items_found": 4,
  "actions_taken": 1,
  "escalations": 0,
  "tokens_estimate": 52000,
  "outcome": "report-only | fix-proposed | escalated | no-op"
}
```

## Recent Runs

<!-- Loop appends below this line -->

```json
{
  "run_id": "2026-08-18T19:20:00Z",
  "pattern": "daily-triage",
  "duration_s": 180,
  "items_found": 4,
  "actions_taken": 0,
  "escalations": 2,
  "tokens_estimate": 70000,
  "outcome": "report-only",
  "notes": "P0 nuevos: E2E cron roto (HTTPS vs HTTP), backup cron desaparecido, working tree sucio en main con rediseño P&L Excel sin commit. STATE.md actualizado."
}
```
```json
{
  "run_id": "2026-08-19T00:25:00Z",
  "pattern": "daily-triage",
  "duration_s": 240,
  "items_found": 3,
  "actions_taken": 0,
  "escalations": 2,
  "tokens_estimate": 85000,
  "outcome": "report-only",
  "notes": "P0 nuevo: working tree sucio post-commit 83342e7 (sesion posthoc 22:00 Aug 18 edita 4 archivos borrando Hoja5/ribbon/formula bar/row-num/col-letters sin commit). P0 vigente: Gmail OAuth MISSING_TOKEN. Side-effect: git ls-remote falla por Host key verification (SSH fingerprint GitHub no aceptado). Crons backup + E2E programados 03:00/03:15 hoy. STATE.md actualizado; sin push, sin reinicios, sin ediciones de codigo."
}
```
```json
{
  "run_id": "2026-08-19T05:43:00Z",
  "pattern": "daily-triage",
  "duration_s": 280,
  "items_found": 4,
  "actions_taken": 0,
  "escalations": 2,
  "tokens_estimate": 95000,
  "outcome": "report-only",
  "notes": "Verificacion 5h despues del run de 00:25. Hallazgos: (1) Working tree sucio PERSISTE: 4 archivos modificados 22:00 Aug 18 sin commit, revertiendo parcialmente el diseno Excel workbook commiteado en 83342e7 (borrando cr-formula-row, cr-row-num, cr-col-letters, cr-statusbar, cr-sheet-nav, cr-zoom, cr-sheet-add, y la pestana 'Hoja5'). (2) SSH known_hosts a GitHub ROTO (Host key verification failed) - 83342e7 puede estar sin push. (3) Cron backup 03:00 OK primer run automatico real (db-20260819-0300.sql.gz 2.1 MB). (4) Cron E2E 03:15 OK 233/233 PASS contra main committed (HEAD=83342e7). (5) Gmail collector OK (1.6s), Gmail age cron 08:00 hoy deberia escribir (sigue estancado en 2026-08-10). (6) OAuth watchdog 3/3 tokens OK. (7) Dashboard health v9.0.0 OK. (8) Run_all collector 05:30 OK Last.app 0.9s + Gmail 1.6s + Drive 7.5s. P0 vigente: Gmail OAuth MISSING_TOKEN. STATE.md actualizado; sin push, sin reinicios, sin ediciones de codigo."
}
```
```json
{
  "run_id": "2026-08-19T15:50:00Z",
  "pattern": "daily-triage",
  "duration_s": 320,
  "items_found": 4,
  "actions_taken": 0,
  "escalations": 3,
  "tokens_estimate": 105000,
  "outcome": "report-only",
  "notes": "P0 detectado: REGRESION EN MAIN COMMITEADO - 2 unit tests fallan (test_marketplace_legal_names_are_grouped_as_commissions y TestClassification::test_marketplace_legal_names_land_in_commissions) porque commit 3925344 (Jarvis, pusheado) amplio desglose_pyg_rules.py incluyendo 'Restauracion y Hosteleria' en aprovisionamientos, lo que rompe la clasificacion de Glovo (categoria_raw='Restauracion y Hosteleria' -> aprovisionamientos en vez de comisiones). El cron E2E (test_api.py, 233 checks) NO cubre estos tests, por eso la regresion es invisible a la verificacion automatica. P0 nuevo: working tree con 5 archivos (taxonomy.py nuevo 14KB + v2 schema layer en desglose_pyg.py + refactor de rules.py + 2 tests nuevos), mtimes 11:29 Aug 19, sesion posthoc continua - 4to dia consecutivo. Estado git: local HEAD = origin/main = 3925344 (cache refs confirma sincronizacion, pero git ls-remote falla por SSH key). SSH a github: Permission denied (publickey) para hermes-liados user. Crons OK: backup 03:00 2.2MB, E2E 03:15 233/233 PASS contra 3925344, gmail-age 08:00 OK 23d tokens, oauth-watchdog hourly 3/3 OK, drive 15:00 principal OK. Tunnel tracker timer activo cada 5min, URL estable (state file stale por diseno - solo escribe en cambios). Dashboard v9.0.0 /api/health OK, uvicorn 4h20m uptime 106MB. Pendiente: revertir cambio en desglose_pyg_rules.py (quitar 'Restauracion y Hosteleria' de aprovisionamientos categories o agregar excepcion vendor para Glovo/Uber Eats), revisar y gate de sesion posthoc, arreglar SSH fingerprint para push verificado, decidir destino de los 5 archivos del working tree. STATE.md actualizado; sin push, sin reinicios, sin ediciones de codigo."
}
```
```json
{
  "run_id": "2026-08-20T01:55:00Z",
  "pattern": "daily-triage",
  "duration_s": 240,
  "items_found": 4,
  "actions_taken": 0,
  "escalations": 4,
  "tokens_estimate": 88000,
  "outcome": "report-only",
  "notes": "L1 ejecutada por cron (modo report-only, sin ediciones de codigo, sin push, sin reinicios). REGRESION PYG PERSISTE en main (3925344) - pytest verificado en vivo: 2 failed, 84 passed en test_cuenta_resultados.py y test_desglose_pyg.py (mismas tests que runs 15:50 y 20:55, sin cambios). Cron E2E (test_api.py 233 checks) sigue sin detectar la regresion. Working tree crece: +908/-115 vs HEAD 3925344; 5 archivos del dia anterior (taxonomy.py nuevo 369 lineas, desglose_pyg.py +451, desglose_pyg_rules.py +379/-115, test_desglose_pyg_v2.py 582 lineas, smoke_desglose_pyg_v2.py 133 lineas) + STATE.md y loop-run-log.md de este run. Sesion posthoc no humana 5to dia consecutivo sin gate humano. Git state estable: local HEAD 3925344 = origin/main (cache refs). git ls-remote falla: Permission denied (publickey) para hermes-liados. SSH fingerprint github sigue roto. Diagnostico regresion confirmado nivel codigo: desglose_pyg_rules.py:84 anadio 'Restauracion y Hosteleria' a aprovisionamientos.categories; como BUCKETS[0]=aprovisionamientos, classify_factura() evalua ese bucket ANTES de llegar a comisiones (l305 con vendors Glovo/Uber). Fix minimo: revertir inclusion o anadir vendor-first check antes de category match - requiere worktree (regla L2). Crons automaticos OK: backup 03:00 db-20260819 2.2MB, E2E 03:15 233/233 PASS, gmail-age 08:00 OK 23d, oauth-watchdog 01:00 3/3 OK, drive 01:30 principal OK 0 archivos. Dashboard v9.0.0 /api/health OK, uvicorn 14h26m uptime 107MB RSS. Watchdog systemd timers OK (1min/5min). Tunnel tracker state file stale 37h por diseno (solo escribe en cambios URL). STATE.md actualizado con entrada de este run; sin push, sin reinicios destructivos, sin ediciones de codigo."
}
