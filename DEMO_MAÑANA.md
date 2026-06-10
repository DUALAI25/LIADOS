# Demo Liados — Guía rápida (11:30 AM)

## Antes de la demo (5 min antes)

1. Abre terminal en el VPS y verifica que el dashboard está vivo:
   ```
   systemctl --user status liados-dashboard
   curl -s -o /dev/null -w "%{http_code}\n" -u jefe:jefe2026 http://localhost:9120/
   ```
   Debe dar `active (running)` y `200`.

## URL y credenciales

- **Dashboard:** http://185.195.13.45:9120/
- **Usuario:** jefe
- **Contraseña:** jefe2026

## Qué enseñar — guion de 5 minutos

### 1) KPIs en directo (30s)
Señala los 4 números grandes arriba: ventas del mes, gastos del mes, margen, facturas pendientes.
> "Estos son los datos reales de esta semana, actualizados a las 6 de la mañana."

### 2) Top proveedores (30s)
Señala la tabla lateral. Los 2-3 primeros puestos.
> "Aquí ves dónde se te va la pasta. DOMINGO ALCARAZ, Makro, la luz..."

### 3) Facturas recientes (30s)
Tabla inferior. Cada fila = factura real del TPV o de Gmail.
> "Esto es tu libro de caja digital."

### 4) EL MOMENTO ESTELAR — el chat (3 min)
Click en el icono 💬 abajo a la derecha. Escribe una de estas:

- **A:** ¿Cuánto llevo gastado este mes?
- **B:** ¿Cuál es mi proveedor más caro?
- **C:** ¿Qué facturas están pendientes de pago?

La respuesta llega en 3-5 segundos. IA leyendo base de datos real.

### 5) Cierre (30s)
> "Esto corre solo. Cada mañana a las 6 AM se sincroniza con tu TPV y tu Gmail. Tú solo miras."

## Si algo peta

- **Dashboard no carga:** `systemctl --user restart liados-dashboard`
- **Chat no responde:** mira `journalctl --user -u liados-dashboard -n 50`
- **Datos viejos:** `cd /root/liados && .venv/bin/python -m agente.scripts.run_all`
- **Logs diarios:** `tail -100 /root/liados/data/run_all.log`

## Lo que NO enseñar mañana

- El código fuente
- Los tests
- El `.env` ni credenciales
- Workflows de n8n
