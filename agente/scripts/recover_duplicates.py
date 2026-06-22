"""
recover_duplicates.py - 2026-06-22
Recupera facturas Gmail marcadas erroneamente como 'duplicate'.

Bug historico: gmail_collector llamaba mark_as_duplicate() incluso cuando
el duplicado era el mismo source_id re-procesado en runs incrementales.
Resultado: 323 facturas con content_hash UNICO marcadas como duplicate.

Este script:
1. Cuenta las facturas a recuperar (sanity check).
2. UPDATE: status='pending' para las 323 (solo source=gmail, status=duplicate,
   content_hash no nulo).
3. Re-parsea cada archivo PDF/imagen con la IA actual.
4. Actualiza la fila con el JSON parseado.
5. Reporta resultados.

Idempotente: si se ejecuta 2 veces, la 2a no hace nada (no hay duplicate).
"""
import os
import sys
import logging
from pathlib import Path

# Cargar .env
from dotenv import load_dotenv
load_dotenv('/root/liados/.env')

sys.path.insert(0, '/root/liados/agente/scripts')
from db_connection import get_conn
from invoice_parser import parse_invoice
from psycopg2.extras import Json

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('recover_dup')


def count_duplicates_to_recover():
    """Cuenta facturas a recuperar: status='duplicate' o 'pending' con hash."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM invoices
            WHERE source = 'gmail'
              AND status IN ('duplicate', 'pending')
              AND content_hash IS NOT NULL
        """)
        return cur.fetchone()[0]
    finally:
        conn.close()


def list_recoverable():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, content_hash, source_id, raw_file_url, parsed_json, status
            FROM invoices
            WHERE source = 'gmail'
              AND status IN ('duplicate', 'pending')
              AND content_hash IS NOT NULL
            ORDER BY created_at
        """)
        return cur.fetchall()
    finally:
        conn.close()


def reset_to_pending(invoice_id):
    """Resetea solo si está en 'duplicate' (las que ya están en 'pending' no necesitan reset)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE invoices
            SET status = 'pending', parsed_json = NULL, updated_at = NOW()
            WHERE id = %s AND status = 'duplicate'
        """, (invoice_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_parsed(invoice_id, parsed, raw_file_url=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE invoices SET
                vendor_name = %s,
                invoice_number = %s,
                invoice_date = %s,
                total_amount = %s,
                base_amount = %s,
                tax_amount = %s,
                currency = %s,
                description = %s,
                category_raw = %s,
                status = 'classified',
                parsed_json = %s,
                raw_file_url = COALESCE(%s, raw_file_url),
                updated_at = NOW()
            WHERE id = %s
        """, (
            parsed.get('vendor_name'),
            parsed.get('invoice_number'),
            parsed.get('invoice_date'),
            parsed.get('total_amount'),
            parsed.get('base_amount'),
            parsed.get('tax_amount'),
            parsed.get('currency', 'EUR'),
            parsed.get('description'),
            parsed.get('category_raw'),
            Json(parsed.get('raw', parsed)),
            raw_file_url,
            invoice_id,
        ))
        conn.commit()
    finally:
        conn.close()


def find_local_file(content_hash, raw_file_url):
    """Busca el archivo local por hash en /root/liados/data/invoices/raw/."""
    base = Path('/root/liados/data/invoices/raw')
    if not base.exists():
        return None
    # El filename incluye el hash como prefijo
    for p in base.rglob(content_hash + '*'):
        return p
    return None


def main():
    logger.info("=== recover_duplicates.py ===")
    n_to_recover = count_duplicates_to_recover()
    logger.info("Facturas a recuperar: %d", n_to_recover)
    if n_to_recover == 0:
        logger.info("Nada que hacer.")
        return 0

    rows = list_recoverable()
    logger.info("Listadas: %d", len(rows))

    reset = 0
    reparsed_ok = 0
    still_pending = 0
    errors = 0

    for i, (inv_id, content_hash, source_id, raw_file_url, parsed_json, current_status) in enumerate(rows, 1):
        if i % 25 == 0:
            logger.info("Progreso: %d/%d (ok=%d pending=%d err=%d)",
                        i, len(rows), reparsed_ok, still_pending, errors)

        if current_status == 'duplicate':
            if not reset_to_pending(inv_id):
                continue
            reset += 1
        # Si ya está 'pending', no reseteamos, solo intentamos re-parsear.

        local_path = find_local_file(content_hash, raw_file_url)
        if not local_path:
            logger.warning("  Archivo no encontrado para %s (id=%s)", content_hash, inv_id)
            still_pending += 1
            continue

        # Detectar MIME por extension
        ext = local_path.suffix.lower()
        mime_map = {
            '.pdf': 'application/pdf',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
        }
        mime_type = mime_map.get(ext, 'application/octet-stream')

        try:
            parsed = parse_invoice(str(local_path), mime_type, local_path.name)
        except Exception as e:
            logger.error("  parse error %s: %s", content_hash, e)
            errors += 1
            continue

        if parsed:
            try:
                update_parsed(inv_id, parsed, str(local_path))
                reparsed_ok += 1
            except Exception as e:
                logger.error("  update error %s: %s", inv_id, e)
                errors += 1
        else:
            still_pending += 1

    logger.info("=" * 60)
    logger.info("RESUMEN recovery:")
    logger.info("  Reseteadas a pending: %d", reset)
    logger.info("  Re-parseadas OK:      %d", reparsed_ok)
    logger.info("  Siguen pending:       %d (error vision/parsing)", still_pending)
    logger.info("  Errores:              %d", errors)
    logger.info("=" * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
