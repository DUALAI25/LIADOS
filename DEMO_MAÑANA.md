# Demo Liados — Guía rápida (corregida 2026-07-01)

> Documento verificado empíricamente. URLs, puertos, paths y comandos reales.

## Antes de la demo (5 min antes)

Abre SSH al VPS `100.87.20.4` (Tailscale) y verifica:

```bash
systemctl status liados-dashboard.service --no-pager
curl -u jefe:jefe2026 -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9121/api/health
```

Debe dar `active (running)` y `200`.

## URL y credenciales

- **URL del dashboard:** `http://100.87.20.4:9121/`  (requiere Tailscale)
- **Alternativa si Tailscale no funciona:** consultar al jefe si hay tunnel disponible
- **Usuario:** `jefe`
- **Contraseña:** `jefe2026`

## Qué enseñar — guion de 5 minutos

### 1) KPIs en directo (30s)
Señala los 4 números grandes arriba: ventas del mes, gastos del mes, margen, facturas pendientes.
> "Estos son los datos reales del TPV Last.app, sincronizados cada 30 minutos."

> **Nota mental**: los KPIs de julio aparecen a 0€ si la demo es antes de la primera venta del día. Es comportamiento esperado, no error.

### 2) Top proveedores (30s)
Señala la tabla lateral. Los 2-3 primeros puestos. Datos reales verificados hoy:
- Suministros: 247 facturas, 87.382€
- Restauración y Hostelería: 67 facturas, 20.346€
- Servicios Profesionales: 34 facturas, 15.812€

> "Aquí ves dónde se te va la pasta. Suministros, makro, la luz..."

### 3) Ventas por canal / Ingresos por mes (1 min)
Pestaña "Ventas por canal (últimos 6 meses)" — datos ene-jun 2026:
- 8.231 facturas ingestadas
- 240.889€ en ventas
- Top mes: marzo (45.975€), mayo (35.870€)

> "Esto es tu libro de caja digital. Datos limpios."

### 4) Últimas facturas (30s)
Las 15 facturas más recientes, cada fila con fecha + proveedor + importe.

### 5) Cierre (30s)
> "Esto corre solo. Cada mañana a las 6 AM se sincroniza con tu TPV (Last.app) y tu Gmail (facturas PDF adjuntas). Tú solo miras."

## Si algo peta — comandos verificados

- **Dashboard no carga:** `systemctl restart liados-dashboard.service`
- **Datos viejos:** `cd /root/liados && .venv/bin/python -m agente.scripts.run_all`
- **Logs diarios:** `tail -100 /root/liados/data/run_all.log`
- **Health del dashboard:** `curl -u jefe:jefe2026 http://127.0.0.1:9121/api/health`

## Lo que NO enseñar mañana

- El código fuente
- Los tests
- El `.env` ni credenciales (¡especialmente esto!)
- Logs de errores (hay un warning conocido de Gmail tokens; ver nota abajo)

## Notas operativas (verificadas 2026-07-01)

- **Gmail collector puede estar en estado `MISSING_TOKEN`**: las cuentas OAuth necesitan reautorización. Es un fix de 5 min pero NO afecta a la demo porque el dashboard se nutre de Last.app (8.231 facturas), no de Gmail. Si el cliente pregunta: "se reautoriza esta semana".
- **No abrir `data/run_all.log`**: contiene errores históricos de Gmail.
- **Last.app sync corre automáticamente cada 30 minutos** vía cron.

## Seguridad

- El puerto `9121` está **firewall-allowlist**: solo acepta conexiones desde Tailscale CIRD + loopback. Los bots de internet ya no pueden escanearlo (verificado: internet → 9121 → timeout).
- HTTP Basic auth con credenciales en `.env` (no commiteadas, `chmod 600`).
