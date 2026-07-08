"""Deriva ventas por dia de semana y hora del dia localmente desde bills.json."""
import json
from datetime import datetime
from collections import defaultdict
from pathlib import Path

BILLS_PATH = Path("/tmp/lastapp_pull/bills.json")
OUT_DIR = Path("/tmp/lastapp_pull/analytics")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    with BILLS_PATH.open() as f:
        bills = json.load(f)

    print(f"Procesando {len(bills)} bills...")

    by_dow = defaultdict(lambda: {"count": 0, "total": 0})
    by_hour = defaultdict(lambda: {"count": 0, "total": 0})

    for b in bills:
        if b.get("deleted"):
            continue
        ct = b.get("creationTime", "")
        try:
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        except Exception:
            continue
        dow = dt.weekday()
        hour = dt.hour
        total = b.get("total", 0) or 0
        by_dow[dow]["count"] += 1
        by_dow[dow]["total"] += total
        by_hour[hour]["count"] += 1
        by_hour[hour]["total"] += total

    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    dow_rows = []
    for d in range(7):
        dow_rows.append({
            "Bills.creationDayOfWeek": d,
            "Bills.creationDayOfWeek.label": dias[d],
            "Bills.count": by_dow[d]["count"],
            "Bills.total": by_dow[d]["total"],
        })
    with (OUT_DIR / "ventas_por_dia_semana.json").open("w") as f:
        json.dump(dow_rows, f, indent=2)
    print(f"ventas_por_dia_semana: {sum(r['Bills.count'] for r in dow_rows)} bills")

    hour_rows = []
    for h in range(24):
        hour_rows.append({
            "Bills.creationHour": h,
            "Bills.count": by_hour[h]["count"],
            "Bills.total": by_hour[h]["total"],
        })
    with (OUT_DIR / "ventas_por_hora.json").open("w") as f:
        json.dump(hour_rows, f, indent=2)
    print(f"ventas_por_hora: {sum(r['Bills.count'] for r in hour_rows)} bills")

    print("DONE")


if __name__ == "__main__":
    main()
