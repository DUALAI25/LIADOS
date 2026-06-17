"""Queries CubeJS para extraer analytics completas del bar Liados.

Guarda cada resultado en /tmp/lastapp_pull/analytics/ como JSON.
"""
import os
import json
import time
import requests
from pathlib import Path

# Cargar .env
env_path = Path("/root/liados/.env")
with env_path.open() as f:
    for ln in f:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if "=" in ln:
            k, v = ln.split("=", 1)
            os.environ[k] = v.strip().strip('"').strip("'")

TOKEN = os.environ["LASTAPP_OAUTH_BEARER_TOKEN"]
LOC_ID = os.environ["LASTAPP_LOCATION_ID"]
ORG_ID = os.environ["LASTAPP_ORGANIZATION_ID"]

OUT_DIR = Path("/tmp/lastapp_pull/analytics")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cube_query(query, chart_type="bar"):
    """Ejecuta queryCubeJS via MCP. Devuelve lista de filas."""
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    r = requests.post(
        "https://api.last.app/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "queryCubeJS",
                "arguments": {"query": query, "chartType": chart_type},
            },
        },
        timeout=60,
    )
    if not r.ok:
        log(f"  HTTP {r.status_code}: {r.text[:200]}")
        return None
    text = r.text
    data_lines = [ln[6:] for ln in text.split("\n") if ln.startswith("data: ")]
    if not data_lines:
        log(f"  No SSE data: {text[:200]}")
        return None
    try:
        payload = json.loads(data_lines[0])
        if "error" in payload:
            log(f"  MCP error: {str(payload['error'])[:200]}")
            return None
        text_content = payload["result"]["content"][0]["text"]
        result_set = json.loads(text_content)
        return result_set.get("resultSet", {}).get("data", [])
    except Exception as e:
        log(f"  Parse error: {e}")
        return None


def save(name, data):
    if data is None:
        log(f"  {name}: SKIP (no data)")
        return
    path = OUT_DIR / f"{name}.json"
    with path.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    log(f"  {name}: {len(data)} rows -> {path.name}")


def main():
    log("=== CUBEJS ANALYTICS PULL ===")

    # 1. Tendencia de ventas diaria (todos los tiempos)
    log("[1/8] Ventas diarias (todos los tiempos)")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "day",
        }],
        "order": [["Bills.creationTime", "asc"]],
    })
    save("ventas_diarias", rows)

    # 2. Ventas por mes (ultimo ano)
    log("[2/8] Ventas mensuales")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total", "Bills.tax"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "month",
        }],
        "order": [["Bills.creationTime", "asc"]],
    })
    save("ventas_mensuales", rows)

    # 3. Ventas por dia de la semana
    log("[3/8] Ventas por dia de la semana")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "week",
        }],
        "order": [["Bills.count", "desc"]],
    })
    save("ventas_por_dia_semana", rows)

    # 4. Ventas por hora del dia
    log("[4/8] Ventas por hora del dia")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "hour",
        }],
        "order": [["Bills.creationTime", "asc"]],
    })
    save("ventas_por_hora", rows)

    # 5. Ventas por fuente/canal
    log("[5/8] Ventas por fuente/canal")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "dimensions": ["Bills.source"],
        "order": [["Bills.total", "desc"]],
    })
    save("ventas_por_canal", rows)

    # 6. Top 50 productos vendidos (todos los tiempos)
    log("[6/8] Top 50 productos")
    rows = cube_query({
        "measures": ["SoldProducts.count", "SoldProducts.totalAmount"],
        "dimensions": ["SoldProducts.name", "SoldProducts.category"],
        "order": [["SoldProducts.count", "desc"]],
        "limit": 50,
    })
    save("top_50_productos", rows)

    # 7. Top productos por mes (ultimos 6 meses, agrupado)
    log("[7/8] Top productos por mes (ultimos 6 meses)")
    rows = cube_query({
        "measures": ["SoldProducts.count"],
        "dimensions": ["SoldProducts.name", "SoldProducts.creationMonth"],
        "order": [["SoldProducts.count", "desc"]],
        "limit": 100,
    })
    save("productos_por_mes", rows)

    # 8. Metodos de pago
    log("[8/8] Metodos de pago")
    rows = cube_query({
        "measures": ["Payments.count", "Payments.amount"],
        "dimensions": ["Payments.type"],
        "order": [["Payments.amount", "desc"]],
    })
    save("metodos_pago", rows)

    log("DONE")


if __name__ == "__main__":
    main()
