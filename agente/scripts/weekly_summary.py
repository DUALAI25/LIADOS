import os
import logging
import requests
import psycopg2
import psycopg2.extras

from db_connection import get_conn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def main():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT
            COALESCE(SUM(total_amount) FILTER (WHERE type='expense'), 0) AS total_expense,
            COALESCE(SUM(total_amount) FILTER (WHERE type='income'), 0) AS total_income,
            COUNT(*) FILTER (WHERE type='expense') AS expense_count,
            COUNT(*) FILTER (WHERE type='income') AS income_count
        FROM invoices
        WHERE invoice_date >= CURRENT_DATE - INTERVAL '7 days'
          AND status NOT IN ('duplicate', 'rejected')
    """)
    week = cur.fetchone()

    cur.execute("""
        SELECT c.name, SUM(i.total_amount) as total
        FROM invoices i
        JOIN categories c ON i.category_id = c.id
        WHERE i.invoice_date >= CURRENT_DATE - INTERVAL '7 days'
          AND i.status NOT IN ('duplicate', 'rejected')
          AND i.type = 'expense'
        GROUP BY c.name ORDER BY total DESC LIMIT 3
    """)
    top_cats = cur.fetchall()

    cur.execute("""
        SELECT v.name, SUM(i.total_amount) as total
        FROM invoices i
        JOIN vendors v ON i.vendor_id = v.id
        WHERE i.invoice_date >= CURRENT_DATE - INTERVAL '7 days'
          AND i.status NOT IN ('duplicate', 'rejected')
          AND i.type = 'expense'
        GROUP BY v.name ORDER BY total DESC LIMIT 3
    """)
    top_vendors = cur.fetchall()

    cur.execute("""
        SELECT COUNT(*) AS pending_count FROM invoices
        WHERE status = 'pending' AND type = 'expense'
    """)
    pending = cur.fetchone()
    pending_count = pending['pending_count'] if pending else 0

    conn.close()

    msg = (
        f"📊 *Resumen Semanal*\n\n"
        f"*Gastos:* {week['expense_count']} facturas — {week['total_expense']:.2f}€\n"
        f"*Ingresos:* {week['income_count']} facturas — {week['total_income']:.2f}€\n"
        f"*Neto:* {week['total_income'] - week['total_expense']:.2f}€\n\n"
    )

    if top_cats:
        msg += "*Top categorías (gastos):*\n"
        for c in top_cats:
            msg += f"  • {c['name']}: {c['total']:.2f}€\n"

    if top_vendors:
        msg += "\n*Top proveedores:*\n"
        for v in top_vendors:
            msg += f"  • {v['name']}: {v['total']:.2f}€\n"

    msg += f"\n*Pendientes de clasificar:* {pending_count}"

    logger.info("Resumen semanal generado")
    logger.info(f"Resumen:\n{msg}")

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if token and chat_id:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': msg, 'parse_mode': 'Markdown'}
        )
        logger.info("Resumen enviado por Telegram")


if __name__ == '__main__':
    main()
