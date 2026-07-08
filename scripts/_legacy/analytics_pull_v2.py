"""Queries CubeJS v2 - arregla granularity con dateRange explicito."""
import os
import json
import time
import requests
from pathlib import Path

env_path = Path("/root/liados/.env")
with env_path.open() as f:
    for ln in f:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if "=" in ln:
            k, v = ln.split("=", 1)
            os.environ[k] = v.strip().strip('"').strip("'")

TOKEN = os.environ["LASTAPP_OAUTH_BEARER_TOKEN"]  # noqa
OUT_DIR = Path("/tmp/lastapp_pull/analytics")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cube_query(query, chart_type="bar"):
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    r = requests.post(
        "https://api.last.app/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "queryCubeJS",
                       "arguments": {"query": query, "chartType": chart_type}},
        },
        timeout=60,
    )
    if not r.ok:
        log(f"  HTTP {r.status_code}: {r.text[:200]}")
        return None
    text = r.text
    data_lines = [ln[6:] for ln in text.split("\n") if ln.startswith("data: ")]
    if not data_lines:
        return None
    try:
        payload = json.loads(data_lines[0])
        if "error" in payload:
            log(f"  MCP error: {str(payload['error'])[:300]}")
            return None
        text_content = payload["result"]["content"][0]["text"]
        result_set = json.loads(text_content)
        return result_set.get("resultSet", {}).get("data", [])
    except Exception as e:
        log(f"  Parse error: {e}")
        return None


def save(name, data):
    if data is None:
        log(f"  {name}: SKIP")
        return
    path = OUT_DIR / f"{name}.json"
    with path.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    log(f"  {name}: {len(data)} rows")


def main():
    log("=== CUBEJS ANALYTICS V2 ===")

    # 1. Ventas diarias con dateRange explicito
    log("[1/6] Ventas diarias (con dateRange)")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "day",
            "dateRange": ["2025-12-01", "2026-06-30"],
        }],
        "order": [["Bills.creationTime", "asc"]],
    })
    save("ventas_diarias", rows)

    # 2. Ventas mensuales
    log("[2/6] Ventas mensuales")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "month",
            "dateRange": ["2025-12-01", "2026-06-30"],
        }],
        "order": [["Bills.creationTime", "asc"]],
    })
    save("ventas_mensuales", rows)

    # 3. Ventas por dia de la semana
    log("[3/6] Ventas por dia de la semana")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "week",
        }],
        "order": [["Bills.count", "desc"]],
    })
    save("ventas_por_dia_semana", rows)

    # 4. Ventas por hora
    log("[4/6] Ventas por hora")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "hour",
        }],
        "order": [["Bills.creationTime", "asc"]],
    })
    save("ventas_por_hora", rows)

    # 5. Top 50 productos (sin SoldProducts.creationMonth, sin filtros raros)
    log("[5/6] Top 50 productos")
    rows = cube_query({
        "measures": ["SoldProducts.count"],
        "dimensions": ["SoldProducts.name"],
        "order": [["SoldProducts.count", "desc"]],
        "limit": 50,
    })
    save("top_50_productos", rows)

    # 6. Ticket medio por mes (medida: avg)
    log("[6/6] Ticket medio por mes")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total", "Bills.avgTicket"],
        "timeDimensions": [{
            "dimension": "Bills.creationTime",
            "granularity": "month",
            "dateRange": ["2025-12-01", "2026-06-30"],
        }],
        "order": [["Bills.creationTime", "asc"]],
    })
    save("ticket_medio_mensual", rows)

    log("DONE")


if __name__ == "__main__":
    main()
