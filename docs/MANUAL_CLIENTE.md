# Manual de Usuario — Liados (Sistema de Gestión de Facturas)

> **Para quién**: personal autorizado del cliente (administradores, contabilidad, dirección)
> **Qué es**: sistema automatizado que captura, parsea y categoriza facturas desde Gmail y Google Drive
> **Quién lo mantiene**: DualAI (Antonio + Jarvis)

---

## 1. Acceso al Dashboard

### URL de acceso
**https://echo-companies-typing-marie.trycloudflare.com**

> ⚠️ **Importante**: la URL puede cambiar tras un reinicio del servidor. Si no funciona,
> contacta con tu administrador (Antonio) — el sistema envía automáticamente un Telegram con la URL nueva.

### Credenciales
- **Usuario**: `jefe`
- **Contraseña**: `jefe2026`

El navegador te pedirá usuario y contraseña. Guárdalos si tu navegador lo permite (recomendado).

---

## 2. ¿Qué hace el sistema automáticamente?

El sistema trabaja en background las 24 horas. Tú no tienes que hacer nada para que funcione:

| Qué hace | Cada cuánto | Para qué |
|---|---|---|
| Lee Gmail buscando facturas nuevas | cada 30 min | Captura adjuntos PDF |
| Escanea Google Drive buscando facturas nuevas | cada 30 min | Captura PDFs subidos manualmente |
| Parsea cada factura con IA | tras captura | Extrae proveedor, fecha, importe, IVA |
| Guarda en base de datos | tras parseo | Para que las veas en el dashboard |
| Envía resumen por Telegram | diario (si configurado) | Aviso de facturas nuevas |
| Backup de la base de datos | diario 03:00 | Recuperación ante desastres |

**No necesitas hacer login cada día** — el sistema corre solo. Solo entras cuando quieres **consultar datos**.

---

## 3. Pantallas principales del dashboard

### 3.1 KPIs (página principal)
Métricas del mes en curso:
- **Ventas del mes** — total facturado a clientes
- **Gastos del mes** — total facturas recibidas de proveedores
- **Margen del mes** — ventas menos gastos
- **IVA del mes** — IVA repercutido menos IVA soportado

### 3.2 Gastos / Facturas
- Lista completa de facturas recibidas (proveedores)
- Filtros por fecha, proveedor, categoría
- Búsqueda libre por nombre de proveedor o número de factura
- Click en una factura → ver detalle y PDF

### 3.3 Locales (solo para restaurantes con múltiples sedes)
- Distribución de ventas por local
- Comparativa entre locales

### 3.4 Alertas
- Avisos de importes inusuales
- Facturas duplicadas detectadas
- Errores de procesamiento

---

## 4. Tareas habituales

### 4.1 Buscar una factura concreta
1. Ve a **Gastos**
2. Usa el buscador (arriba a la derecha): escribe nombre del proveedor o número de factura
3. Click en la fila → ver detalle

### 4.2 Reclasificar una factura
1. Abre la factura
2. Click en **"Reclasificar"**
3. Elige la categoría correcta
4. Confirma

> Esto es útil cuando una factura está clasificada como "Otros" y quieres moverla a "Suministros" o "Materias primas".

### 4.3 Ver el PDF original
1. Abre la factura
2. Click en **"Ver PDF"**
3. Se abre el PDF original tal como lo mandaron

### 4.4 Exportar datos a Excel/CSV
1. Ve a **Gastos** o **Ventas**
2. Click en el icono de **Exportar** (esquina superior derecha)
3. Elige el rango de fechas
4. Se descarga un CSV que puedes abrir en Excel

---

## 5. ¿Qué hago si algo falla?

### 5.1 El dashboard no carga (error 502 / 504 / página en blanco)
1. **Espera 1 minuto** y recarga (F5). Si persiste:
2. **Avisa a Antonio** (Telegram / WhatsApp). El problema suele ser:
   - El servidor se ha reiniciado (se recupera solo en 2-3 min)
   - El túnel cloudflared cambió de URL (Antonio te manda la nueva)
   - Algún servicio está caído (Antonio lo revisa y reinicia)

### 5.2 Una factura NO aparece
1. Verifica que el PDF está en tu Gmail o Drive
2. Espera **30 minutos** (el siguiente ciclo de captura)
3. Si sigue sin aparecer tras 1 hora, avisa a Antonio
   - Es posible que el PDF no tenga texto (es una imagen escaneada)
   - O que el proveedor tenga un formato que la IA no reconoce

### 5.3 Una factura está mal clasificada
1. Reclásala tú mismo (sección 4.2)
2. Si reclasificas muchas, avisa a Antonio — puede actualizar el clasificador IA

### 5.4 He subido un PDF pero el sistema dice "duplicado"
- El sistema detectó que ya tenía una factura con el mismo contenido (mismo PDF o muy similar)
- Si es legítimo (no es duplicado), abre la factura existente y reclasifícala

---

## 6. Lo que NO debes hacer

| ❌ No hagas | Por qué |
|---|---|
| Borrar PDFs originales del Gmail / Drive | El sistema los necesita para verificación |
| Mover PDFs a otra carpeta de Drive sin avisar | El sistema solo escanea las carpetas configuradas |
| Cambiar la contraseña del dashboard | Antonio necesita acceso para mantenimiento |
| Compartir credenciales con personas no autorizadas | El dashboard contiene datos fiscales sensibles |

---

## 7. Privacidad y seguridad

- Tus datos viven en un **servidor privado** (VPS propio del cliente)
- **HTTPS** cifra toda la comunicación
- **HTTP Basic Auth** protege el acceso
- Las contraseñas nunca se guardan en el navegador en texto plano
- Los **backups automáticos diarios** permiten recuperar datos ante cualquier problema

Si tienes dudas de seguridad, contacta con Antonio directamente.

---

## 8. Soporte y contacto

| Canal | Para qué | Tiempo de respuesta |
|---|---|---|
| **Telegram** (`@antonioserranomorales980`) | Avisos urgentes, caídas, dudas | 1-4 horas en horario laboral |
| **Email** (`antonio@dualai.es`) | Temas no urgentes, reportes | 24 horas |
| **Llamada** (previa coordinación) | Problemas críticos | Inmediato |

**Horario de soporte**: lunes a viernes, 09:00–18:00 (CET).
**Fuera de horario**: solo para caídas completas del sistema.

---

## 9. Cambios y actualizaciones

El sistema se actualiza regularmente para:
- Mejorar la clasificación de facturas
- Añadir nuevas categorías o proveedores
- Corregir bugs
- Añadir nuevas pantallas

Las actualizaciones se aplican sin interrumpir el servicio. Si necesitas una funcionalidad nueva, coméntaselo a Antonio.

---

**Versión del manual**: 1.0 — 2026-07-28
**Versión del sistema**: 2.1 (entrega certificada P0 cerrada)
