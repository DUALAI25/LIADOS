"""Ingesta Last.app JSON -> Postgres (bills, payments, customers).

Usa COPY via /tmp staging para velocidad (mejor que INSERT en batch).
Idempotente: ON CONFLICT DO UPDATE.
"""
import os
import json
import psycopg2
import psycopg2.extras
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

conn = psycopg2.connect(
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "5432")),
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
)
conn.autocommit = False
cur = conn.cursor()


def log(msg):
    print(f"[ingest] {msg}", flush=True)


def ingest_bills():
    log("Cargando bills.json...")
    with Path("/tmp/lastapp_pull/bills.json").open() as f:
        bills = json.load(f)
    log(f"  {len(bills)} bills a ingestar")

    rows = []
    for b in bills:
        company = b.get("company") or {}
        customer = b.get("customerCompany") or {}
        rows.append((
            b["id"],
            b.get("number"),
            b["creationTime"],
            b.get("finalizingTime"),
            int(b.get("total") or 0),
            int(b.get("tax") or 0),
            int(b.get("taxableBase") or 0),
            int(b.get("taxPercentage") or 0),
            int(b.get("deliveryFee") or 0),
            int(b.get("minimumBasketSurcharge") or 0),
            int(b.get("terraceSurcharge") or 0),
            int(b.get("discountTotal") or 0),
            company.get("name"),
            company.get("taxId"),
            company.get("address"),
            customer.get("name"),
            customer.get("taxId"),
            bool(b.get("deleted")),
            os.environ.get("LASTAPP_LOCATION_ID"),
            os.environ.get("LASTAPP_ORGANIZATION_ID"),
            json.dumps(b),
        ))

    log("  Insertando con execute_values...")
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO lastapp_bills (
            id, number, creation_time, finalizing_time,
            total_cents, tax_cents, taxable_base_cents, tax_percentage,
            delivery_fee_cents, minimum_basket_surcharge_cents,
            terrace_surcharge_cents, discount_total_cents,
            company_name, company_tax_id, company_address,
            customer_name, customer_tax_id,
            deleted, location_id, organization_id, raw_json
        ) VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            number = EXCLUDED.number,
            creation_time = EXCLUDED.creation_time,
            total_cents = EXCLUDED.total_cents,
            tax_cents = EXCLUDED.tax_cents,
            deleted = EXCLUDED.deleted,
            raw_json = EXCLUDED.raw_json,
            ingested_at = NOW()
        """,
        rows,
        template=None,
        page_size=500,
    )
    conn.commit()
    log(f"  OK: {len(rows)} bills procesados")


def ingest_payments():
    log("Cargando payments.json...")
    with Path("/tmp/lastapp_pull/payments.json").open() as f:
        pays = json.load(f)
    log(f"  {len(pays)} payments a ingestar")

    rows = []
    for p in pays:
        rows.append((
            p["id"],
            p.get("billId"),
            p.get("type"),
            int(p.get("amount") or 0),
            int(p.get("tip") or 0),
            p["creationTime"],
            p.get("userId"),
            p.get("tillId"),
            p.get("externalId"),
            bool(p.get("deleted")),
            json.dumps(p),
        ))

    log("  Insertando...")
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO lastapp_payments (
            id, bill_id, type, amount_cents, tip_cents,
            creation_time, user_id, till_id, external_id,
            deleted, raw_json
        ) VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            amount_cents = EXCLUDED.amount_cents,
            deleted = EXCLUDED.deleted,
            raw_json = EXCLUDED.raw_json,
            ingested_at = NOW()
        """,
        rows,
        page_size=500,
    )
    conn.commit()
    log(f"  OK: {len(rows)} payments")


def ingest_customers():
    log("Cargando customers.json...")
    with Path("/tmp/lastapp_pull/customers.json").open() as f:
        custs = json.load(f)
    log(f"  {len(custs)} customers")

    rows = []
    for c in custs:
        rows.append((
            c["id"],
            c.get("organizationId"),
            c.get("name"),
            c.get("surname"),
            c.get("phoneNumber"),
            c["creationTime"],
            c.get("updateTime"),
            c.get("source"),
            c.get("externalId"),
            json.dumps(c),
        ))

    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO lastapp_customers (
            id, organization_id, name, surname, phone_number,
            creation_time, update_time, source, external_id, raw_json
        ) VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            update_time = EXCLUDED.update_time,
            raw_json = EXCLUDED.raw_json,
            ingested_at = NOW()
        """,
        rows,
        page_size=500,
    )
    conn.commit()
    log(f"  OK: {len(rows)} customers")


def ingest_analytics_cache():
    log("Cargando analytics/*.json...")
    analytics_dir = Path("/tmp/lastapp_pull/analytics")
    rows = []
    for path in sorted(analytics_dir.glob("*.json")):
        if path.name in ("productos_por_mes.json", "ticket_medio_mensual.json"):
            # Skip empty files
            if path.stat().st_size <= 3:
                continue
        with path.open() as f:
            data = json.load(f)
        rows.append((path.stem, json.dumps(data)))
    log(f"  {len(rows)} metricas")

    for metric, data_json in rows:
        cur.execute(
            """
            INSERT INTO lastapp_analytics_cache (metric, data, computed_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (metric) DO UPDATE SET
                data = EXCLUDED.data,
                computed_at = NOW()
            """,
            (metric, data_json),
        )
    conn.commit()
    log("  OK")


def verify():
    log("=== VERIFICACION ===")
    cur.execute("SELECT COUNT(*) FROM lastapp_bills WHERE deleted = false")
    print(f"  Bills activas: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM lastapp_payments WHERE deleted = false")
    print(f"  Payments activos: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM lastapp_customers")
    print(f"  Customers: {cur.fetchone()[0]}")
    cur.execute("SELECT metric, jsonb_array_length(data) FROM lastapp_analytics_cache WHERE jsonb_typeof(data) = 'array'")
    print("  Analytics cache:")
    for m, n in cur.fetchall():
        print(f"    - {m}: {n} filas")


if __name__ == "__main__":
    ingest_bills()
    ingest_payments()
    ingest_customers()
    ingest_analytics_cache()
    verify()
    cur.close()
    conn.close()
    log("DONE")
