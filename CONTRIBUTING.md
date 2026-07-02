# Contributing · Liados Dashboard

## Stack
- **Backend**: FastAPI + psycopg2 (Postgres) + httpx/MCP para Last.app
- **Frontend**: Vanilla JS + Chart.js (CDN) + design system propio en `static/tokens.css`
- **Chat AI**: OpenCode Go (deepseek-v4-flash) + 21 tools (6 facturas + 15 Last.app MCP)
- **ETL**: `agente/scripts/{gmail_collector,lastapp_sync,invoice_parser,dedup_checker}.py`
- **Tests**: `tests/test_api.py` (E2E sin navegador, 56 checks) + `tests/run_e2e.sh`
- **Deploy**: systemd (`liados-dashboard.service` en `:9121`) + cron (backup diario 03:00, E2E diario 03:00)

## Setup
```bash
# 1. Deps
pip install -r agente/requirements.txt

# 2. Config
cp .env.example .env
# editar: DASHBOARD_USER, DASHBOARD_PASSWORD, OPENCODE_API_KEY,
# LASTAPP_OAUTH_BEARER_TOKEN, DB_*

# 3. Levantar
systemctl restart liados-dashboard

# 4. Verificar
curl http://localhost:9121/api/health
bash tests/run_e2e.sh
```

## Estructura clave
- `dashboard/app.py` — API REST (28 endpoints) + HTML inline mínimo
- `dashboard/chat.py` — wrapper conversacional con SSE streaming
- `dashboard/agent.py` — NO TOCAR (define el system prompt + tools; cambios aquí rompen el chat)
- `dashboard/static/tokens.css` — design system (dark/light, colores, espaciado, tipografía)
- `dashboard/static/app.js` — toda la lógica del frontend (vanilla JS)
- `agente/mcp/invoices_server.py` — 6 tools sobre la BD local
- `agente/mcp/lastapp_server.py` — 15 tools sobre `api.last.app/mcp`

## Convenciones
- **NO modificar `dashboard/agent.py`** (rompe el chat). Para cambios, usar `dashboard/chat.py`.
- **SQL parametrizado siempre** (`%s` con psycopg2). Nunca `f"..."` con input del usuario.
- **Frontend sin frameworks** (vanilla JS). Para libs externas, evaluar tamaño vs valor.
- **Tokens/redes en `.env`** (nunca en código). `.env` está en `.gitignore`.
- **HTTP Basic Auth** en todos los endpoints (excepto `/static/*` y `/api/health`).
- **Tests E2E con `requests`** (sin browser). Para Playwright, `tests/demo_flow.py` (manual).

## Tests
- `bash tests/run_e2e.sh` → 56 checks (KPIs, charts, search, drill-down, export CSV, chat, auth, edge cases)
- `python3 tests/test_e2e.js` (legacy, no usado)
- Cron diario: `/etc/cron.d/liados-e2e` ejecuta tests a las 03:00

## Debug
- Logs: `journalctl -u liados-dashboard -f`
- Health: `curl http://localhost:9121/api/health`
- LLM errors: 429/503 son del upstream OpenCode Go (no es nuestro bug)
- BD pool: `{"checks":{"pool":{"used":N,"free":M}}}` en /api/health

## Pendiente (deuda técnica menor)
- `open_support_ticket` no tiene tool remota equivalente (Last.app no expone `createSupportTicket`).
- HTTPS no configurado (depende del reverse proxy del VPS, no del código).
- `top_products` mapea a `queryCubeJS` pero sin args específicos → devuelve error en runtime.
- `weekly_summary.py` aún imprime a stdout (algunos `print` antiguos).

## Seguridad
- Token GitHub personal: rotar si está expuesto.
- `.env` perms: 600, owned by root.
- HTTP Basic: usar HTTPS en producción (el dashboard NO cifra Basic Auth en tránsito).
