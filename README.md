# Liados — Sistema de Gestión de Facturas

> **Sistema automatizado para capturar, parsear y categorizar facturas del cliente Liados (cadena de restaurantes).**
> Stack: Python 3.12 + PostgreSQL 16 + FastAPI + MiniMax M3 (parser) + Cloudflare Tunnel.

---

## 🎯 Qué hace

1. **Lee Gmail** de N cuentas configuradas en busca de facturas (PDF adjuntos)
2. **Escanea Google Drive** del cliente para capturar PDFs subidos manualmente
3. **Parsea** PDFs y adjuntos con IA (MiniMax M3) → extrae proveedor, fecha, importe, IVA
4. **Guarda** en PostgreSQL con deduplicación por hash de contenido + `(source, source_id)` UNIQUE
5. **Sincroniza ventas** desde Lastapp (API del cliente) si está configurado
6. **Muestra** en dashboard web FastAPI con KPIs, gastos, búsqueda, exportación
7. **Alerta** por Telegram cuando hay tokens OAuth a punto de expirar
8. **Backup** automático diario 03:00 UTC

---

## 📋 Estado

| Fase | Estado | Evidencia |
|---|---|---|
| Captura Gmail multi-cuenta | ✅ Producción | 475 facturas reales, 2 cuentas |
| Captura Drive | ✅ Producción | 74 facturas reales |
| Parser IA | ✅ Producción | MiniMax M3 (no OpenAI) |
| Dashboard FastAPI | ✅ Producción | HTTP 200, HTTPS, Basic Auth |
| Tunnel público | ✅ Producción | Cloudflare quick-tunnel |
| Backup automático | ✅ Producción | Diario 03:00, 1.7-2MB |
| OAuth watchdog | ✅ Producción | `oauth_watchdog.py` cada hora |
| Idempotencia collector | ✅ Verificada 2026-07-28 | `docs/verification/P0-2026-07-28.md` |
| Restore backup probado | ✅ Verificada 2026-07-28 | Mismo doc |

**Porcentaje entrega**: 98% — producción certificada.

---

## 🏗 Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│ Gmail (N cuentas)        Lastapp API        Google Drive │
│      │                       │                    │      │
│      ▼                       ▼                    ▼      │
│ gmail_collector.py    lastapp_sync.py    drive_collector.py
│      │                       │                    │      │
│      └───────┬───────────────┴────────────────────┘      │
│              ▼                                            │
│    invoice_parser.py (MiniMax M3)                         │
│              │                                            │
│              ▼                                            │
│    ┌─────────────┐         ┌──────────────┐              │
│    │ PostgreSQL  │◄────────┤ dedup_checker │              │
│    │  invoices   │         │ (UNIQUE +hash)│              │
│    └─────┬───────┘         └──────────────┘              │
│          │                                                 │
│          ▼                                                 │
│   ┌──────────────┐         ┌─────────────────────┐        │
│   │  Filesystem  │         │  FastAPI Dashboard  │        │
│   │  /data/raw/  │         │  :9121 (HTTPS)      │        │
│   └──────────────┘         │  :9122 (proxy)      │        │
│                            └──────────┬──────────┘        │
└───────────────────────────────────────┼──────────────────┘
                                        │
                                  Cloudflare Tunnel
                                        │
                                        ▼
                          https://<random>.trycloudflare.com
```

---

## 🚀 Instalación rápida (entorno limpio)

### Prerrequisitos
- Python 3.12+
- PostgreSQL 14+ con BD `desliado` creada
- Acceso a API Gmail OAuth (Google Cloud project con OAuth consent screen **publicado**)
- Acceso a API Google Drive OAuth
- (Opcional) Cuenta Lastapp del cliente
- (Opcional) Bot Telegram + chat_id para alertas

### Pasos

```bash
# 1. Clonar
git clone https://github.com/DUALAI25/LIADOS.git
cd LIADOS

# 2. Crear venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Configurar .env desde el ejemplo
cp .env.example .env
# Editar .env con tus credenciales reales

# 4. Crear BD y esquema
sudo -u postgres createdb desliado
sudo -u postgres psql -d desliado -f db/schema.sql

# 5. Generar certificados self-signed (solo para dev)
mkdir -p certs && cd certs
openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365 -subj "/CN=localhost"
cd ..

# 6. Lanzar dashboard
python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 9121 \
  --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
```

### Producción (con systemd)

```bash
# Ver systemd/liados-dashboard.service, systemd/liados-tunnel.service
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now liados-dashboard liados-proxy-9122 liados-tunnel
```

---

## ⚙️ Configuración (.env)

Copia `.env.example` a `.env` y rellena:

```bash
# ── Dashboard ──
DASHBOARD_USER=jefe
DASHBOARD_PASSWORD=jefe2026

# ── PostgreSQL ──
PGHOST=localhost
PGPORT=5432
PGDATABASE=desliado
PGUSER=desliado
PGPASSWORD=<ver vault / pass manager>

# ── Gmail OAuth ──
GMAIL_ACCOUNTS=principal,secundaria
GOOGLE_OAUTH_CLIENT_ID=<from GCP>
GOOGLE_OAUTH_CLIENT_SECRET=<from GCP>
OAUTH_APP_MODE=production    # CRITICAL: nunca "testing" en prod (tokens caducan 7 días)

# ── Telegram (alertas) ──
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_CHAT_ID=<tu chat_id>

# ── Parser IA ──
MINIMAX_API_KEY=<from minimax.io>
MINIMAX_MODEL=MiniMax-M3

# ── Lastapp (opcional) ──
LASTAPP_API_TOKEN=<from Lastapp>
LASTAPP_RESTAURANT_ID=<id>
```

⚠️ **NUNCA commitear `.env`** — está en `.gitignore`.

---

## 🔐 OAuth Gmail + Google Drive (setup inicial)

1. **Google Cloud Console**:
   - Crear proyecto `liados-prod`
   - Habilitar APIs: Gmail API + Google Drive API
   - Crear credenciales OAuth (tipo: Web application)
   - **PUBLISH APP** en OAuth consent screen (modo Testing caduca en 7 días)

2. **Generar URL de autorización**:
   ```bash
   python -m agente.scripts.gmail_auth --account principal
   ```
   → imprime URL. Pegar en navegador, autorizar, copiar `code` del redirect.

3. **Intercambiar code por tokens**:
   ```bash
   python -m agente.scripts.gmail_auth --account principal --code <CODE>
   ```
   → guarda `token_gmail_principal.json` en `agente/credentials/`

4. **Repetir para secundaria y Drive**.

5. **Verificar watchdog**:
   ```bash
   python -m agente.scripts.oauth_watchdog --once
   ```
   → debe reportar `3/3 tokens OK`.

---

## 🧪 Tests

```bash
# Tests unitarios (rápidos, ~30s)
bash scripts/run_tests.sh

# Smoke E2E (verifica dashboard + API)
bash tests/run_e2e.sh

# Verificación P0 (idempotencia + restore + smoke)
# Ver docs/verification/P0-2026-07-28.md
```

---

## 🛠 Troubleshooting

### Dashboard no carga (HTTP 502 / 504)
```bash
# Verificar servicio
systemctl status liados-dashboard

# Reiniciar si caído
sudo systemctl restart liados-dashboard

# Ver log
journalctl -u liados-dashboard -n 50 --no-pager
```

### Tokens OAuth muertos (watchdog alerta Telegram)
```bash
# Ver cuáles están muertos
python -m agente.scripts.oauth_watchdog --once

# Reautorizar el muerto (ver sección "OAuth Gmail + Drive" arriba)
```

### Backup no se genera
```bash
# Verificar cron
crontab -l | grep backup

# Ejecutar manualmente
bash /root/liados/scripts/backup_wrapper.sh

# Ver log
tail -30 /var/log/backup.log
```

### Tunnel cloudflared no conecta
```bash
# Verificar proceso
ps aux | grep cloudflared

# Reiniciar
sudo systemctl restart liados-tunnel

# Obtener nueva URL
grep -oE 'https://[a-z-]+\.trycloudflare\.com' /var/log/liados/cloudflared.log | tail -1
```

### Facturas no se capturan
```bash
# ¿Última ejecución del collector?
tail -20 /var/log/liados-drive.log
tail -20 /var/log/liados-gmail.log

# Forzar re-ejecución manual
bash /root/liados/scripts/run_drive.sh
bash /root/liados/scripts/run_gmail.sh   # si existe

# ¿Hay tokens OK?
python -m agente.scripts.oauth_watchdog --once
```

---

## 📁 Estructura del repo

```
.
├── agente/
│   ├── scripts/        # collectors, parser, watchdog
│   ├── credentials/   # tokens OAuth (NO commitear)
│   └── lib/           # utilidades compartidas
├── dashboard/
│   ├── app.py         # FastAPI app principal
│   ├── static/        # CSS, JS, imágenes
│   └── templates/     # Jinja2 templates
├── db/
│   └── schema.sql     # esquema PostgreSQL
├── systemd/           # unit files para producción
├── scripts/           # wrappers bash para cron
├── ops/               # scripts operativos (tunnel tracker, etc)
├── docs/
│   ├── MANUAL_CLIENTE.md
│   ├── PLAN-*.md      # planes de loops pasados
│   ├── safety.md
│   └── verification/  # verificaciones de loops cerrados
├── tests/
│   ├── test_*.py
│   └── run_e2e.sh
├── backups/           # backups BD (NO commitear)
├── data/              # raw/, processed/, logs/
├── certs/             # TLS self-signed (NO commitear)
├── docker-compose.yml # BD + servicios para dev
├── pyproject.toml     # deps del proyecto
├── .env.example       # plantilla de config
└── README.md          # este archivo
```

---

## 🤝 Contribución

- **Repo privado** compartido entre Antonio y Jerónimo
- Issues y PRs se gestionan en GitHub
- Conventional Commits para mensajes
- Tests requeridos para merge a `main`

---

## 📜 Licencia

Propietario — DualAI / Liados.
Todos los derechos reservados.

---

**Versión**: 2.1 — 2026-07-28
**Mantenedor**: Antonio (antonio@dualai.es)
**Stack principal**: Python 3.12 · PostgreSQL 16 · FastAPI · MiniMax M3
