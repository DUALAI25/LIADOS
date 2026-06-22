"""
dedup_checker.py - Deteccion de facturas duplicadas

Dos estrategias:
1. Por hash MD5 del contenido (mismo PDF = duplicado seguro)
2. Por numero + monto + vendor (mismo numero con datos similares = probable duplicado)
"""
from db_connection import get_conn


def is_duplicate_by_hash(content_hash, current_source_id=None):
    """Existe ya una factura con este hash de contenido?

    Args:
        content_hash: hash MD5 del attachment
        current_source_id: si se pasa, se ignora cualquier fila con ese source_id
            (util cuando re-procesamos un email y queremos saber si OTRO email
             con el mismo adjunto ya lo guardo, no nosotros mismos).

    Returns:
        True si existe una fila con ese hash Y (sin current_source_id o con
        un source_id distinto al actual).
    """
    if not content_hash:
        return False
    conn = get_conn()
    try:
        cur = conn.cursor()
        if current_source_id is not None:
            cur.execute(
                "SELECT id FROM invoices WHERE content_hash = %s AND source_id != %s",
                (content_hash, current_source_id),
            )
        else:
            cur.execute(
                "SELECT id FROM invoices WHERE content_hash = %s",
                (content_hash,),
            )
        result = cur.fetchone()
        return result is not None
    finally:
        conn.close()


def is_duplicate_by_number(invoice_number, amount, vendor_name):
    """Existe una factura con el mismo numero + monto + vendor?

    Util para casos donde el mismo PDF llega 2 veces con adjuntos
    distintos (ej: reenviado por el proveedor con otra cabecera).
    """
    if not invoice_number or not amount:
        return False
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Buscamos por numero + monto + vendor similar (case-insensitive)
        cur.execute(
            """SELECT id FROM invoices
               WHERE invoice_number = %s
               AND total_amount = %s
               AND vendor_name ILIKE %s
               AND status != 'duplicate'""",
            (invoice_number, amount, vendor_name or ''),
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
            (source, source_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_duplicate_stats():
    """Retorna estadisticas de duplicados (util para el dashboard)."""
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
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))
    finally:
        conn.close()
