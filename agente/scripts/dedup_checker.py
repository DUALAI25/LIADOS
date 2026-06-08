"""
dedup_checker.py — Detección de facturas duplicadas

Dos estrategias:
1. Por hash MD5 del contenido (mismo PDF = duplicado seguro)
2. Por número + monto + vendor (mismo número con datos similares = probable duplicado)
"""
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
    """¿Existe ya una factura con este hash de contenido?"""
    if not content_hash:
        return False
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM invoices WHERE content_hash = %s", (content_hash,))
        result = cur.fetchone()
        return result is not None
    finally:
        conn.close()


def is_duplicate_by_number(invoice_number, amount, vendor_name):
    """
    ¿Existe una factura con el mismo número + monto + vendor?

    Útil para casos donde el mismo PDF llega 2 veces con adjuntos
    distintos (ej: reenviado por el proveedor con otra cabecera).
    """
    if not invoice_number or not amount:
        return False
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Buscamos por número + monto + vendor similar (case-insensitive)
        cur.execute(
            """SELECT id FROM invoices
               WHERE invoice_number = %s
               AND total_amount = %s
               AND vendor_name ILIKE %s
               AND status != 'duplicate'""",
            (invoice_number, amount, vendor_name or '')
        )
        result = cur.fetchone()
        return result is not None
    finally:
        conn.close()


def mark_as_duplicate(source, source_id):
    """Marca una factura como duplicada (por source + source_id)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE invoices
               SET status = 'duplicate', updated_at = NOW()
               WHERE source = %s AND source_id = %s""",
            (source, source_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_duplicate_stats():
    """Retorna estadísticas de duplicados (útil para el dashboard)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'duplicate') AS total_duplicates,
                COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE status = 'classified') AS classified,
                COUNT(*) AS total
            FROM invoices
        """)
        row = cur.fetchone()
        if not row:
            return {'total': 0, 'duplicates': 0, 'pending': 0, 'classified': 0}
        return {
            'total': row[3] or 0,
            'duplicates': row[0] or 0,
            'pending': row[1] or 0,
            'classified': row[2] or 0,
        }
    finally:
        conn.close()
