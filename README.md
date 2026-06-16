# Desliado — Sistema de Gestión de Facturas (Liados)

Sistema automatizado para capturar, parsear y categorizar facturas del cliente Liados (cadena de restaurantes).

## 🎯 Qué hace

1. **Lee Gmail** de N cuentas configuradas (actualmente 2) en busca de facturas
2. **Parsea** PDFs y adjuntos con IA (OpenCode Go, deepseek-v4-flash)
3. **Guarda** en PostgreSQL + MinIO (o filesystem local)
4. **Detecta duplicados** por hash de contenido y por número+monto+vendor
5. **Sincroniza ventas** desde Lastapp (API del cliente)
6. **Envía resumen semanal** por Telegram (opcional)

## 📋 Estado

| Fase | Estado |
|---|---|
| **Fase 0** — Setup base (Postgres + MinIO + scripts) | ✅ Completa |
| **Fase 1** — Multi-cuenta Gmail + auth paste-back | ✅ Completa |
| **Fase 2** — Bugfixes scripts (weekly, lastapp, collector) | ✅ Completa |
| **Fase 3** — Dashboard FastAPI + chat AI | ✅ Completa |
| **Fase 4** — Deploy producción + apagar n8n | ⏳ Pendiente |

## 🏗 Arquitectura

```
Gmail (N cuentas)        Lastapp API
    │                        │
    ▼                        ▼
gmail_collector.py    lastapp_sync.py
    │                        │
    └────┬───────────────────┘
         ▼
   invoice_parser.py (IA: OpenCode Go)
         │
         ▼
   ┌─────────────┐         ┌──────────────┐
   │ PostgreSQL  │◄────────┤ dedup_checker│
   │  invoices   │         └──────────────┘
   └─────┬───────┘
         │
   ┌─────▼──────┐        ┌──────────────────────┐
   │ Filesystem │        │ FastAPI Dashboard    │
   │ (PDFs)     │        │ /api/kpis + /api/chat│
   └────────────┘        └──────────┬───────────┘
         │                          │
   ┌─────▼──────────┐      ┌────────▼────────┐
   │ weekly_summary │      │ MCP servers     │
   │ (Telegram)     │      │ invoices+lastapp│
   └────────────────┘      └─────────────────┘
```

**Infraestructura actual (Jun 2026):**
- **PostgreSQL 16** corre de forma nativa en el host (`localhost:5432`).
- **MinIO** corre en Docker (`desliado-minio`) pero no está configurado en `.env`; el sistema usa filesystem local para PDFs.
- **OpenClaw Gateway** corre en Docker y ejecuta el cron cada 15 min sobre `/root/liados`.
- **Dashboard** corre como servicio systemd (`liados-dashboard`) en el puerto `9121`.

## 🚀 Setup rápido

### 1. Instalar dependencias

```bash
pip install -r agente/requirements.txt
```

### 2. Configurar `.env`

```bash
cp .env.example .env
# Editar con tus credenciales
```

### 3. Levantar infraestructura

PostgreSQL corre de forma nativa en el host. Solo MinIO se levanta con Docker:

```bash
# Si no está corriendo MinIO
docker compose up -d minio

# O para arrancar todo (servicios systemd + Docker)
bash scripts/start_all.sh
```

### 4. Autorizar cuentas Gmail

```bash
# Cuenta 1
python3 agente/scripts/gmail_auth.py --account principal
# → Abre URL, autoriza, pega la URL de callback

# Cuenta 2 (si tienes)
python3 agente/scripts/gmail_auth.py --account secundaria
```

### 5. Verificar

```bash
python3 agente/scripts/check_credentials.py
python3 agente/scripts/gmail_auth.py --list
```

### 6. Ejecutar collectors

```bash
# Gmail
python3 agente/scripts/gmail_collector.py

# Lastapp (ventas)
python3 agente/scripts/lastapp_sync.py
```

## 🔐 Credenciales necesarias

| Servicio | Variables | Cómo obtenerla |
|---|---|---|
| **Gmail (x N)** | `GMAIL_ACCOUNTS=cuenta1,cuenta2`<br>`GMAIL_CREDENTIALS_FILE_<cuenta>`<br>`GMAIL_TOKEN_FILE_<cuenta>` | Google Cloud Console → Gmail API → OAuth Desktop o Web |
| **OpenCode Go** | `OPENCODE_API_KEY` | https://opencode.ai/zen |
| **Last.app API** | `LASTAPP_API_TOKEN`<br>`LASTAPP_ORGANIZATION_ID`<br>`LASTAPP_LOCATION_ID` | https://developers.last.app/ |
| **Last.app MCP** | `LASTAPP_OAUTH_BEARER_TOKEN` o `LASTAPP_OAUTH_CLIENT_ID` + `LASTAPP_OAUTH_CLIENT_SECRET` | Ver sección abajo |
| **PostgreSQL** | `DB_*` | Instancia nativa en localhost:5432 |
| **Dashboard** | `DASHBOARD_USER`<br>`DASHBOARD_PASSWORD` | Configurable en `.env` |
| **Telegram** (opcional) | `TELEGRAM_BOT_TOKEN`<br>`TELEGRAM_CHAT_ID` | @BotFather |

## 🤖 Last.app MCP setup

El conector MCP oficial de Last.app permite al agente de chat consultar y actuar sobre la operativa real del restaurante: productos, reservas, ventas, impresoras, configuración y soporte.

Doc oficial: https://www.last.app/actualizaciones-de-producto/last-app-mcp-conecta-tu-ia-con-tu-restaurante

Endpoint MCP: `https://api.last.app/mcp`

### Autenticación

Last.app MCP usa OAuth 2.0 con grant type `authorization_code`. El token endpoint es `https://api.last.app/mcp/token` y el de autorización `https://api.last.app/mcp/authorize`.

**Método A — Token Bearer directo (el más rápido para empezar)**:

Si ya tienes un token Bearer de Last.app MCP (por haber configurado Claude Desktop, Cursor o similar), puedes usarlo directamente:

```bash
# En .env
LASTAPP_OAUTH_BEARER_TOKEN=eyJhbGciOi...tu_token_aqui
```

**Método B — OAuth interactivo**:

1. Obtén un `client_id` y `client_secret` de Last.app:
   - Actualmente el panel de admin (`admin.last.app`) no tiene sección pública para crear clientes MCP.
   - Contacta a soporte@last.app o a tu account manager solicitando credenciales OAuth para MCP.
   - Alternativa: extrae el `client_id` del tráfico de red al configurar Claude Desktop con Last.app MCP (dev tools → Network → buscar "authorize").

2. Configura en `.env`:
   ```bash
   LASTAPP_OAUTH_CLIENT_ID=tu_client_id
   LASTAPP_OAUTH_CLIENT_SECRET=tu_client_secret
   LASTAPP_OAUTH_SCOPE=mcp:read mcp:write
   LASTAPP_OAUTH_REDIRECT_URI=http://localhost:9999/callback
   ```

3. Al arrancar el agente, se abrirá el navegador para autorizar. El token se guarda en memoria del proceso.

### Arrancar el MCP server

```bash
python -m agente.mcp.lastapp_server
```

### Variables de entorno necesarias

```bash
# Mínimo (una de las dos):
LASTAPP_OAUTH_BEARER_TOKEN=...        # Método A: token directo
# o bien:
LASTAPP_OAUTH_CLIENT_ID=...           # Método B: OAuth interactivo
LASTAPP_OAUTH_CLIENT_SECRET=...

# Opcionales:
LASTAPP_OAUTH_TOKEN_URL=https://api.last.app/mcp/token
LASTAPP_OAUTH_AUTHORIZE_URL=https://api.last.app/mcp/authorize
LASTAPP_OAUTH_SCOPE=mcp:read mcp:write
LASTAPP_OAUTH_REDIRECT_URI=http://localhost:9999/callback
```

### Ejemplos de uso desde el chat del dashboard

Preguntas de lectura (ejecución directa):
- "¿Cuáles son mis 5 productos más vendidos esta semana?"
- "¿Qué reservas tengo mañana?"
- "¿Cuántas cancelaciones he tenido este mes?"
- "¿Qué impresoras tengo configuradas en Liados Centro?"
- "¿Qué integraciones tengo activas?"
- "Busca en la base de conocimiento cómo configurar una impresora"

### Acciones destructivas (flujo de confirmación)

Para acciones que modifican la operativa (cambiar disponibilidad, subir precios, abrir tickets), el sistema usa un patrón de confirmación en dos pasos:

1. El usuario pide una acción (ej: "marca la tarta de queso como no disponible")
2. El agente llama a la tool (ej: `set_product_unavailable`) y recibe un `confirmation_token`
3. El agente informa al usuario: "Esta acción requiere confirmación. ¿Confirmas?"
4. Si el usuario confirma, el agente llama a `confirm_action` con el token
5. La acción se ejecuta contra Last.app

Si pasan más de 5 minutos sin confirmar, el token expira y hay que repetir el proceso.

**Importante**: el frontend del dashboard debe mostrar un botón de confirmación cuando se reciba una respuesta con `status: "pending_confirmation"`. Esto asegura que siempre haya un humano en el loop para acciones destructivas.

### Descubrimiento de tools

Para ver qué tools expone realmente el MCP remoto de Last.app:

```bash
python -c "
from agente.mcp.lastapp_client import LastAppClient
from agente.mcp.lastapp_auth import get_token
c = LastAppClient(get_token)
c.initialize()
import json
tools = c.discover_tools()
for t in tools:
    print(f\"{t['name']}: {t.get('description','')[:100]}\")
"
```

El mapeo entre nuestras tools y las remotas está en el diccionario `TOOL_MAP` en `agente/mcp/lastapp_server.py`. Si los nombres no coinciden, se corrige automáticamente al arrancar.

## 📁 Estructura del repo

```
liados/
├── agente/
│   ├── mcp/
│   │   └── invoices_server.py    # MCP server (en desarrollo)
│   ├── openclaw.json             # Config MCP
│   ├── requirements.txt
│   └── scripts/
│       ├── gmail_auth.py         # ✅ OAuth unificado (paste-back, multi-cuenta)
│       ├── gmail_collector.py    # ✅ Multi-cuenta
│       ├── lastapp_sync.py       # ✅ Sync ventas Lastapp
│       ├── invoice_parser.py     # Parser IA (OpenCode Go)
│       ├── db_writer.py          # Escritura en DB (Postgres)
│       ├── dedup_checker.py      # Detección duplicados
│       ├── storage.py            # MinIO / filesystem
│       ├── weekly_summary.py     # Resumen semanal Telegram
│       └── check_credentials.py  # ✅ Validador de config
├── db/
│   ├── schema.sql                # ✅ Schema completo
│   └── migrations/
│       └── 001_add_source_account.sql
├── docker-compose.yml
├── setup.sh
├── .env.example                  # ✅ Multi-cuenta
└── README.md
```

## 🔄 Migración desde n8n

El cliente tenía 6 workflows en n8n (https://dualai2026-n8n.qooqoh.easypanel.host). Este repo los reemplaza:

| Workflow n8n | Reemplazo Python |
|---|---|
| Dashboard | Streamlit (pendiente) |
| Importación Histórica | `gmail_collector.py` (backfill) |
| Sync Sheets | `lastapp_sync.py` |
| Archivo Facturas | `storage.py` + `gmail_collector.py` |
| Sapito | Parser IA en `invoice_parser.py` |
| Error Handler | Try/except en cada script + `agent_logs` |

## 🐛 Troubleshooting

### "GMAIL_ACCOUNTS no configurado"
Añade en `.env`:
```
GMAIL_ACCOUNTS=principal,secundaria
```

### "Token no encontrado: agente/credentials/gmail_token_X.json"
Ejecuta:
```bash
python3 agente/scripts/gmail_auth.py --account X
```

### "Permission denied: storage.py"
Comprueba que `DATA_DIR` existe y es escribible:
```bash
mkdir -p data/invoices/{raw,processed,temp}
```

## 🛠 Comandos útiles

```bash
# Health check de todos los servicios
bash scripts/healthcheck.sh

# Arrancar/reiniciar todos los servicios
bash scripts/start_all.sh

# Ejecutar tests
bash scripts/run_tests.sh

# Gestión del dashboard (systemd)
systemctl status liados-dashboard
systemctl restart liados-dashboard
journalctl -u liados-dashboard -f

# Sincronización manual
.venv/bin/python -m agente.scripts.run_all
.venv/bin/python -m agente.scripts.lastapp_sync
.venv/bin/python -m agente.scripts.gmail_collector
```

## 📜 Licencia

Privado — DualAI / Antonio Serrano.

---

## 🎬 Demo rápida (3 pasos)

Para enseñar el sistema funcionando con datos realistas en 5 minutos:

```bash
# 1. Cargar 80 facturas demo (necesita DB 'desliado' viva)
cd /root/liados
.venv/bin/python -m agente.scripts.seed_demo --wipe

# 2. Probar el MCP server (6 tools disponibles)
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from agente.mcp.invoices_server import list_invoices, monthly_summary, vendor_summary
print(list_invoices(type='expense', limit=5))
print(monthly_summary(year=2026))
print(vendor_summary(limit=5))
"

# 3. Orquestador end-to-end en dry-run
.venv/bin/python -m agente.scripts.run_all --dry-run
```

### Datos que genera el seed
- **24 facturas expense** de 10 proveedores reales (Coca-Cola, Makro, Endesa, Telefónica, Mahou, Seguros Catalana Occidente, etc.)
- **56 facturas income** de 4 locales TPV (Liados Centro, Malasaña, La Latina, Chueca)
- **13 pagos** asociados a facturas pagadas
- **6 agent_logs** simulando actividad de los últimos 14 días
- **Margen neto mensual** entre 19k€ y 30k€ (realista para 4 locales)
