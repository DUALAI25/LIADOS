import os
import json
import logging
import psycopg2
import psycopg2.extras
from datetime import datetime

logger = logging.getLogger(__name__)

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', '5432')),
        dbname=os.getenv('DB_NAME', 'desliado'),
        user=os.getenv('DB_USER', 'desliado'),
        password=os.getenv('DB_PASSWORD', 'desliado_pass_2026')
    )

def save_invoice(data, source, source_id, inv_type='expense', minio_url=None):
    conn = get_conn()
    cur = conn.cursor()

    vendor_id = _get_or_create_vendor(cur, data)

    cur.execute("""
        INSERT INTO invoices (
            type, source, source_id, source_account, invoice_number, invoice_date, due_date,
            vendor_id, vendor_name, vendor_tax_id,
            base_amount, tax_amount, total_amount, currency,
            category_id, category_raw, description, tags,
            status, raw_file_url, parsed_json, content_hash, confidence_score
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            (SELECT id FROM categories WHERE name = %s LIMIT 1),
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (source, source_id) DO UPDATE SET
            invoice_number = EXCLUDED.invoice_number,
            total_amount = EXCLUDED.total_amount,
            status = CASE WHEN invoices.status = 'pending' THEN EXCLUDED.status ELSE invoices.status END,
            updated_at = NOW()
        RETURNING id
    """, (
        inv_type, source, source_id, data.get('source_account'),
        data.get('invoice_number'),
        data.get('invoice_date'),
        data.get('due_date'),
        vendor_id,
        data.get('vendor_name'),
        data.get('vendor_tax_id'),
        data.get('base_amount'),
        data.get('tax_amount'),
        data.get('total_amount'),
        data.get('currency', 'EUR'),
        data.get('category'),
        data.get('category'),
        data.get('description'),
        data.get('tags'),
        'classified' if data.get('category') else 'pending',
        minio_url,
        json.dumps(data),
        data.get('content_hash'),
        data.get('confidence_score', 0.5)
    ))

    invoice_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return invoice_id

def _get_or_create_vendor(cur, data):
    name = data.get('vendor_name')
    tax_id = data.get('vendor_tax_id')
    if not name:
        return None

    # 1. Buscar coincidencia exacta (nombre + tax_id)
    if tax_id:
        cur.execute(
            "SELECT id FROM vendors WHERE name = %s AND tax_id = %s",
            (name, tax_id)
        )
        row = cur.fetchone()
        if row:
            return row[0]

    # 2. Buscar solo por nombre
    cur.execute(
        "SELECT id FROM vendors WHERE name = %s LIMIT 1",
        (name,)
    )
    row = cur.fetchone()
    if row:
        # Si encontró por nombre pero no por tax_id, actualizar tax_id
        if tax_id:
            cur.execute(
                "UPDATE vendors SET tax_id = %s, updated_at = NOW() WHERE id = %s AND tax_id IS NULL",
                (tax_id, row[0])
            )
        return row[0]

    # 3. Crear nuevo proveedor
    cur.execute(
        "INSERT INTO vendors (name, tax_id) VALUES (%s, %s) RETURNING id",
        (name, tax_id)
    )
    return cur.fetchone()[0]

def save_payment(invoice_id, payment_date, amount, source, source_detail=None, invoice_number=None):
    conn = get_conn()
    cur = conn.cursor()

    # Buscar invoice_id por número si no se pasó directamente
    if not invoice_id and invoice_number:
        cur.execute(
            "SELECT id FROM invoices WHERE invoice_number = %s ORDER BY created_at DESC LIMIT 1",
            (invoice_number,)
        )
        row = cur.fetchone()
        if row:
            invoice_id = row[0]
        else:
            logger.warning(f"No se encontró invoice para número {invoice_number}")
            conn.close()
            return None

    if not invoice_id:
        logger.warning("save_payment: invoice_id es None y no se pudo resolver")
        conn.close()
        return None

    cur.execute("""
        INSERT INTO payments (invoice_id, payment_date, amount, source, source_detail)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (invoice_id, payment_date, amount, source, source_detail))
    conn.commit()
    conn.close()
    return invoice_id

def log_agent(source, level, message, details=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_logs (source, level, message, details) VALUES (%s, %s, %s, %s)",
        (source, level, message, json.dumps(details) if details else None)
    )
    conn.commit()
    conn.close()

def update_last_sync(source, status='ok'):
    conn = get_conn()
    cur = conn.cursor()

    # Actualizar contador de items procesados
    cur.execute(
        "UPDATE sync_control SET last_sync = NOW(), status = %s, "
        "items_processed = items_processed + 1 WHERE source = %s",
        (status, source)
    )
    conn.commit()
    conn.close()

def get_last_sync(source):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT last_sync FROM sync_control WHERE source = %s",
        (source,)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else datetime(2000, 1, 1)
