"""Pull masivo Last.app - v2 (con headers por endpoint)."""
import os
import sys
import json
import time
import requests
from datetime import date, timedelta
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

API_TOKEN = os.environ["LASTAPP_API_TOKEN"]  # noqa
ORG_ID = os.environ["LASTAPP_ORGANIZATION_ID"]  # noqa
LOC_ID = os.environ["LASTAPP_LOCATION_ID"]
BASE = os.environ.get("LASTAPP_API_URL", "https://api.last.app/v2")

OUT_DIR = Path("/tmp/lastapp_pull")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def base_headers():
    return {
        "Authorization": "Bearer " + API_TOKEN,
        "Content-Type": "application/json",
    }


def save_json(name, data):
    path = OUT_DIR / f"{name}.json"
    with path.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    log(f"  saved {path} ({len(data) if isinstance(data, list) else 'dict'} items)")


def fetch_all_pages(endpoint, params_base, extra_headers, page_size=100, label="items"):
    items = []
    offset = 0
    page = 0
    t0 = time.time()
    while True:
        page += 1
        params = {**params_base, "limit": page_size, "offset": offset}
        headers = {**base_headers(), **extra_headers}
        r = requests.get(
            f"{BASE}{endpoint}",
            headers=headers,
            params=params,
            timeout=30,
        )
        if not r.ok:
            log(f"  HTTP {r.status_code}: {r.text[:200]}")
            break
        batch = r.json()
        if not batch:
            break
        items.extend(batch)
        offset += len(batch)
        if len(batch) < page_size:
            break
        time.sleep(0.1)
    elapsed = time.time() - t0
    log(f"  {label}: {len(items)} ({page} pages, {elapsed:.1f}s)")
    return items


def pull_bills():
    log("=== BILLS ===")
    today = date.today()
    all_bills = []
    for year_offset in range(0, 5):
        chunk_end = today - timedelta(days=365 * year_offset)
        chunk_start = chunk_end - timedelta(days=364)
        log(f"Chunk {year_offset}: {chunk_start} -> {chunk_end}")
        bills = fetch_all_pages(
            "/bills",
            {
                "locationId": LOC_ID,
                "startDate": chunk_start.isoformat(),
                "endDate": chunk_end.isoformat(),
            },
            extra_headers={"locationID": LOC_ID},
            label=f"bills-{year_offset}",
        )
        if not bills:
            break
        all_bills.extend(bills)
    seen = set()
    unique = []
    for b in all_bills:
        if b["id"] not in seen:
            seen.add(b["id"])
            unique.append(b)
    log(f"Bills unicos: {len(unique)} (de {len(all_bills)} fetched)")
    save_json("bills", unique)
    return unique


def pull_payments():
    log("=== PAYMENTS ===")
    today = date.today()
    all_payments = []
    for year_offset in range(0, 5):
        chunk_end = today - timedelta(days=365 * year_offset)
        chunk_start = chunk_end - timedelta(days=364)
        log(f"Chunk {year_offset}: {chunk_start} -> {chunk_end}")
        pays = fetch_all_pages(
            "/payments",
            {
                "locationId": LOC_ID,
                "startDate": chunk_start.isoformat(),
                "endDate": chunk_end.isoformat(),
            },
            extra_headers={"locationID": LOC_ID},
            label=f"payments-{year_offset}",
        )
        if not pays:
            break
        all_payments.extend(pays)
    seen = set()
    unique = []
    for p in all_payments:
        if p["id"] not in seen:
            seen.add(p["id"])
            unique.append(p)
    log(f"Payments unicos: {len(unique)}")
    save_json("payments", unique)
    return unique


def pull_customers():
    log("=== CUSTOMERS ===")
    customers = fetch_all_pages(
        "/customers",
        {"organizationId": ORG_ID},
        extra_headers={"organizationID": ORG_ID},
        label="customers",
    )
    save_json("customers", customers)
    return customers


def pull_location():
    log("=== LOCATION ===")
    r = requests.get(
        f"{BASE}/locations/{LOC_ID}",
        headers={**base_headers(), "locationID": LOC_ID},
        timeout=30,
    )
    log(f"  HTTP {r.status_code}")
    if r.ok:
        save_json("location", r.json())


if __name__ == "__main__":
    log("START Last.app full pull v2")
    log(f"Org: {ORG_ID}")
    log(f"Loc: {LOC_ID}")
    bills = pull_bills()
    payments = pull_payments()
    customers = pull_customers()
    pull_location()
    log("DONE")
    log(f"Resumen: {len(bills)} bills, {len(payments)} payments, {len(customers)} customers")
