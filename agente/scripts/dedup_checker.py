import os
import psycopg2

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', '5432')),
        dbname=os.getenv('DB_NAME', 'desliado'),
        user=os.getenv('DB_USER', 'desliado'),
        password=os.getenv('DB_PASSWORD', 'desliado_pass_2026')
    )

def is_duplicate_by_hash(content_hash):
    if not content_hash:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM invoices WHERE content_hash = %s", (content_hash,))
    result = cur.fetchone()
    conn.close()
    return result is not None

def is_duplicate_by_number(invoice_number, amount, vendor_name):
    if not invoice_number or not amount:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT id FROM invoices
           WHERE invoice_number = %s
           AND total_amount = %s
           AND vendor_name ILIKE %s
           AND status != 'duplicate'""",
        (invoice_number, amount, vendor_name)
    )
    result = cur.fetchone()
    conn.close()
    return result is not None

def mark_as_duplicate(source, source_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE invoices SET status = 'duplicate', updated_at = NOW() WHERE source = %s AND source_id = %s",
        (source, source_id)
    )
    conn.commit()
    conn.close()
