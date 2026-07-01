# Tests E2E — Dashboard Liados v5

Tests que validan el flujo completo del dashboard con un navegador real (Playwright + node).

## Requisitos

```bash
pip install playwright
playwright install chromium
```

Opcional (para test_e2e.js):
- node v18+

## Tests disponibles

### 1. `test_e2e.js` — Test HTTP puro con Node

```bash
node test_e2e.js
```

Verifica que los 12 endpoints del dashboard responden 200 con auth, y 401 sin auth.

### 2. `test_browser4.py` — Test E2E con Playwright (RECOMENDADO)

```bash
python3 test_browser4.py
```

Carga el dashboard con un navegador Chromium real, verifica:
- Hero se renderiza con datos
- 4 KPI cards
- 3 canvas graficos
- 33+ barras de datos
- Sin errores en console

### 3. `demo_flow.py` — Test del flujo completo de demo

```bash
python3 demo_flow.py
```

Simula todo lo que el cliente va a hacer:
1. Carga dashboard
2. Abre chat con `C`
3. Cierra y abre search con `/`
4. Verifica exports CSV
5. Prueba atajos de teclado

### 4. `test_chat_long.py` — Test del chat IA

```bash
python3 test_chat_long.py
```

Envia preguntas al chat y verifica el reply completo.

## Credenciales

- URL: `http://100.87.20.4:9121/` (vía Tailscale)
- User: `jefe`
- Pass: `jefe2026`

## Status (2026-07-01)

| Test | Status |
|------|--------|
| Carga dashboard | OK |
| Hero, KPIs, charts | OK |
| Chat | OK (3-12s) |
| Search | OK (21 resultados para ENVASES) |
| Export CSV | OK (4 enlaces) |
| Atajos ?/t/r | OK |

Demo READY.