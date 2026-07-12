# Plan — Liados fixes 5P (2026-07-12)

## Contexto

Auditoría 12-07 08:35 UTC en VPS `100.87.20.4` (sandbox sin tocar producción
hasta validar todo). Sesión previa 6-jul dejó working tree sucio + tests rojos.

## Estado real verificado

| Métrica | Valor | Evidencia |
|---|---|---|
| Dashboard `:9121` | HTTP 200 | `curl http://127.0.0.1:9121/api/health` |
| `lastapp_bills` | 8.894 | SELECT count(*) |
| `invoices` | 481 | SELECT count(*) |
| `vendors` | 160 | SELECT count(*) |
| Tests pytest | **40/48 verde** (8 fallan) | `pytest agente/scripts/ --ignore=test_dedup_fix.py` |
| Working tree | 5 archivos sin commit (+1.914 líneas) | `git diff --stat` |
| Gmail `principal` | OK | log 12-07 08:27 → 3 facturas procesadas |
| Gmail `secundaria` | ❌ Token missing | `Token no encontrado: .../gmail_token_secundaria.json` |

## Los 5 P (síntomas detectados)

| ID | Síntoma | Severidad |
|---|---|---|
| P1 | Gmail `secundaria` sin token | 🔴 Acción humana |
| P2 | Working tree sucio (1.914 líneas, 5 archivos) | 🟠 Riesgo de pérdida |
| P3 | 6 tests `test_lastapp_client.py` rojos | 🟠 Regresión B3 |
| P4 | 2 tests `test_gmail_collector_dates.py` rojos | 🟠 Regresión B3 |
| P5 | 2 commits en main sin pushear | 🟢 Esperando OK |

## Diagnóstico raíz de los 8 tests rojos

### Test_lastapp_client.py (6 fallos)

`lastapp_client.py:135` (`_parse_response`):
```python
text = body.strip()
if text.startswith("event:") or text.startswith("data:") or "data:" in text.split("\n", 1)[0]:
```

Mock devuelve `text=""` (default MagicMock → str vacía), pero `text.split("\n", 1)[0]` devuelve `""` y `"data:" in ""` es `False` (string en string vacío). Parece correcto. Pero el assert dice que entró a la rama SSE con error.

Real: **el MagicMock default `.text` no devuelve `""`, devuelve OTRO MagicMock**. Cuando `_parse_response` accede a `.strip()` de un MagicMock, opera sobre MagicMock, `MagicMock.startswith(...)` devuelve MagicMock, `MagicMock or MagicMock or MagicMock` → `MagicMock` (truthy por defecto), así que ENTRA en la rama SSE. Luego `text.splitlines()` da lista de MagicMocks y cada uno `.startswith("data:")` da MagicMock, `.strip()` da MagicMock, etc. Todo se rompe.

**Fix**: el test debe setear `mock_post.return_value.text = ""` (string vacío real).

### Test_gmail_collector_dates.py (2 fallos)

`gmail_collector.py:412` `parser.parse_args(argv)` con `argv=sys.argv[1:]`. Test
llama `gmail_collector.main()` sin args → usa `sys.argv` que pytest contamina con
sus propios flags.

**Fix**: `parser.parse_args(argv if argv is not None else sys.argv[1:])` o
acepta `argv=None` y default a `[]`.

## Plan de acción (orden de ejecución)

### Fase 1 — Tests verde (sin tocar working tree)

1. Crear worktree `fix/liados-tests-2026-07-12`
2. Fix `lastapp_client.py` tests: añadir `mock_post.return_value.text = ""` y
   `mock_post.return_value.text = json.dumps(...)` para los casos que esperan
   body no vacío.
3. Fix `gmail_collector.py:412`: `parser.parse_args(argv if argv else [])`
   + cambiar test para llamar `gmail_collector.main([])`.
4. `pytest agente/scripts/ --ignore=test_dedup_fix.py -q` → **48/48 verde**
5. Commit atómico: `fix(tests): mock text='' + main([]) en B3 regresión`

### Fase 2 — Working tree v6.0.0

6. Verificar dashboard v6.0.0 levanta con los cambios uncommitted (smoke):
   - `curl /api/health` → version="6.0.0"
   - `curl /api/gastos?page=1&page_size=5 -u jefe:****` → 200 JSON
   - `curl /api/gastos/stats -u jefe:****` → 200 JSON
7. Si OK → commit `feat(dashboard): v6.0.0 — q_exec, gmail-status, anti-cache, UI v6`
8. Si falla → restaurar con `git restore .` y reportar al jefe

### Fase 3 — Push y pendientes

9. **Push a origin/main requiere OK del jefe** (safety.md). NO hacerlo sin
   aprobación explícita.
10. Recordar al jefe acción humana: reautorizar `gmail_secundaria`.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Fase 2 rompe dashboard | smoke test ANTES de commit. Si falla, `git restore .` |
| kimi-k2.7-code subagente con HTTP cuelga | ejecutar MANUALMENTE las queries SQL via psql/python (no delegate_task) |
| Push sin permiso | safety.md denylist respeta — espera OK |
| Fix en `gmail_collector.main` cambia CLI | revisar que el cron sigue funcionando (`run_daily.sh`) |

## Verificación

- `pytest -q agente/scripts/` → **48 passed**
- `curl http://127.0.0.1:9121/api/health` → status=ok version=6.0.0
- `curl http://127.0.0.1:9121/api/gastos?page=1&page_size=10 -u jefe:****` → 200
- `git log --oneline -3` muestra commits limpios

## Estado
EN PROGRESO