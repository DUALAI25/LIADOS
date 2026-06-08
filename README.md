# Desliado — Sistema de Gestión de Facturas

## Fase 0 completada ✅

| Servicio | Estado | Acceso |
|----------|--------|--------|
| PostgreSQL 16 | ✅ OK | `localhost:5432` — db: `desliado`, user: `desliado` |
| MinIO | ✅ OK | API: `localhost:9000`, Consola: `http://localhost:9001` |
| Python venv | ✅ OK | `.venv/` con dependencias instaladas |
| Schema DB | ✅ OK | 7 tablas + vistas + índices |
| Bucket invoices | ✅ OK | `localhost/invoices` |

## Scripts disponibles

```
agente/scripts/
├── gmail_collector.py   # Consulta Gmail, descarga facturas, parsea con IA
├── lastapp_sync.py      # Sincroniza facturas desde API de Lastapp
├── invoice_parser.py    # Parsea PDFs/imágenes con deepseek-v4-flash (OpenCode Go)
├── db_writer.py         # Guarda en PostgreSQL + MinIO
├── dedup_checker.py     # Detecta duplicados por hash y número
├── weekly_summary.py    # Resumen semanal por Telegram
├── check_credentials.py # Verifica que todas las credenciales están configuradas
└── setup_gmail_auth.py  # Flujo OAuth de Gmail (genera gmail_token.json)
```

## Credenciales necesarias

| Servicio | Variable | Dónde conseguirla |
|----------|----------|-------------------|
| OpenCode Go | `OPENCODE_API_KEY` | https://opencode.ai/zen |
| Gmail | `GMAIL_CREDENTIALS_FILE` + `GMAIL_TOKEN_FILE` | Google Cloud Console → Gmail API |
| Lastapp | `LASTAPP_API_TOKEN` | https://developers.last.app/ |
| Telegram | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | @BotFather en Telegram |

**Coste estimado de OpenCode Go:** ~$0.04/mes para 100 facturas/mes (12× más barato que gpt-4o-mini).

## Próximos pasos (Fase 1)

1. ~~Editar `.env` con credenciales reales~~ (en curso)
2. Configurar Gmail API (Google Cloud Console → OAuth)
3. Obtener token API de Lastapp
4. Probar `gmail_collector.py` manualmente
5. Configurar crons en OpenClaw

## Comandos útiles

```bash
# Activar entorno
source .venv/bin/activate

# Probar collector manualmente
python3 agente/scripts/gmail_collector.py

# Ver logs de PostgreSQL
docker logs desliado-db

# Ver datos en DB
docker exec -it desliado-db psql -U desliado -d desliado

# Parar todo
docker compose down

# Ver estado
docker ps
```
