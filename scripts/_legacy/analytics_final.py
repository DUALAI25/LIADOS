"""Reintento: ventas por dia de semana + hora con formato alternativo."""
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

TOKEN = os.environ["LASTAPP_OAUTH_BEARER_TOKEN"]
LOC_ID = os.environ["LASTAPP_LOCATION_ID"]
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
    if not data:
        log(f"  {name}: SKIP")
        return
    with (OUT_DIR / f"{name}.json").open("w") as f:
        json.dump(data, f, indent=2, default=str)
    log(f"  {name}: {len(data)} rows")


def main():
    log("=== CUBEJS FINAL ===")

    # 1. Por dia de la semana
    log("[1/2] Por dia de la semana (creationDayOfWeek)")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "dimensions": ["Bills.creationDayOfWeek"],
        "order": [["Bills.creationDayOfWeek", "asc"]],
    })
    save("ventas_por_dia_semana", rows)

    # 2. Por hora del dia
    log("[2/2] Por hora del dia (creationHour)")
    rows = cube_query({
        "measures": ["Bills.count", "Bills.total"],
        "dimensions": ["Bills.creationHour"],
        "order": [["Bills.creationHour", "asc"]],
    })
    save("ventas_por_hora", rows)

    log("DONE")


if __name__ == "__main__":
    main()
