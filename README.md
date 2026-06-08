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
| **Fase 3** — Dashboard Streamlit | ⏳ Pendiente |
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
   ┌─────▼──────┐
   │ MinIO/FS   │  (PDFs originales)
   └────────────┘
         │
   ┌─────▼──────────┐
   │ weekly_summary │  (Telegram opcional)
   └────────────────┘
```

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

### 3. Levantar infraestructura (Docker)

```bash
bash setup.sh
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
| **Lastapp** | `LASTAPP_API_TOKEN` | https://developers.last.app/ |
| **PostgreSQL** | `DB_PASSWORD` | docker-compose.yml lo autogenera |
| **MinIO** (opcional) | `MINIO_*` | docker-compose.yml lo autogenera |
| **Telegram** (opcional) | `TELEGRAM_BOT_TOKEN`<br>`TELEGRAM_CHAT_ID` | @BotFather |

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

## 📜 Licencia

Privado — DualAI / Antonio Serrano.
