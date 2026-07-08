# Scripts legacy (deprecated)

Estos scripts fueron exploratorios durante la integración con Last.app (junio 2026).
Están **deprecated** y no se usan en ningún cron, systemd unit ni import.

| Script | Qué hacía | Reemplazo actual |
|---|---|---|
| `analytics_pull.py` | Queries CubeJS para analytics del bar | `agente/scripts/lastapp_sync.py` + tabla `lastapp_analytics_cache` |
| `analytics_pull_v2.py` | Reintento de analytics con granularity arreglado | idem |
| `derive_analytics.py` | Derivaba ventas por día/hora desde `bills.json` local | `dashboard/app.py` calcula on-the-fly |
| `analytics_final.py` | Otro reintento de analytics | idem |
| `lastapp_full_pull.py` | Pull masivo Last.app (headers por endpoint) | `agente/scripts/lastapp_sync.py` |
| `ingest_lastapp.py` | Ingesta JSON → Postgres con COPY | `agente/scripts/lastapp_sync.py` |

Se conservan en `scripts/_legacy/` para referencia histórica. Si en 90 días nadie
los ha necesitado, borrar definitivamente.
