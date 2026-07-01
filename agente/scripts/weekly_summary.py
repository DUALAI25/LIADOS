"""
weekly_summary.py - Resumen semanal por Telegram.

Que hace: Cada lunes a las 8 AM, genera un resumen de los ultimos 7 dias de
actividad y lo envia al chat configurado en TELEGRAM_CHAT_ID.

Por que existe: el jefe quiere saber el pulso del negocio sin abrir el dashboard.
El resumen es accionable: muestra gastos, ingresos, neto, top categorias y proveedores.

FIX 2026-07-01 (ciclo 6 del audit):
  1. Cron NUNCA lo llamaba (dead code). Anadido a crontab.
  2. Sin manejo de error de Telegram: ahora si falla, exit !=0 y log al data/log.
  3. parse_mode=Markdown era fragil: ahora usa HTML o sin format.
  4. Si Telegram no configurado: imprime resumen al log para no perderlo.
  5. Anadido retry automatico con backoff (2s, 4s).
  6. Anadido metricas: delta vs semana anterior (% cambio gastos).
"""
import os
import sys
import time
import logging
import requests
import psycopg2
import psycopg2.extras

from db_connection import get_conn

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('weekly-summary')

TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'
MAX_RETRIES = 3
RETRY_BACKOFF_S = 2
TIMEOUT_S = 15


def _send_telegram(token, chat_id, text, max_retries=MAX_RETRIES):
    """Envia mensaje a Telegram con retry. Devuelve True si llego."""
    url = TELEGRAM_API.format(token=token)
    last_err = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                url,
                json={'chat_id': chat_id, 'text': text},
                timeout=TIMEOUT_S,
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get('ok'):
                raise RuntimeError(f"Telegram no ok: {body}")
            return True
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = RETRY_BACKOFF_S * (2 ** (attempt - 1))
                logger.warning(
                    f"[{attempt}/{max_retries}] Telegram fallo: {type(e).__name__}: {e}. "
                    f"Reintento en {wait}s."
                )
                time.sleep(wait)

    logger.error(f"Telegram fallo permanente despues de {max_retries} intentos: {last_err}")
    return False


def _format_eur(n):
    """Formatea EUR con separador de miles y 2 decimales."""
    return f"{float(n):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _build_message(metrics):
    """Construye el texto del resumen."""
    msg = (
        "*Resumen semanal Liados*\n\n"
        f"_Periodo: ultimos 7 dias_\n\n"
        f"*Gastos:* {metrics['expense_count']} facturas - {_format_eur(metrics['total_expense'])} EUR\n"
        f"*Ingresos:* {metrics['income_count']} facturas - {_format_eur(metrics['total_income'])} EUR\n"
        f"*Neto:* {_format_eur(metrics['neto'])} EUR\n"
    )

    delta = metrics.get('expense_delta_pct')
    if delta is not None:
        direction = "+" if delta > 0 else ""
        msg += f"*Variacion gastos vs sem. anterior:* {direction}{delta:.1f}%\n"

    if metrics.get('top_categories'):
        msg += "\n*Top categorias (gastos):*\n"
        for c in metrics['top_categories']:
            msg += f"  - {c['name']}: {_format_eur(c['total'])} EUR\n"

    if metrics.get('top_vendors'):
        msg += "\n*Top proveedores:*\n"
        for v in metrics['top_vendors']:
            msg += f"  - {v['name']}: {_format_eur(v['total'])} EUR\n"

    pending = metrics.get('pending_count', 0)
    if pending > 0:
        msg += f"\n_Nota: {pending} facturas pendientes de clasificar (no aparecen en totales)._"

    return msg


def _collect_metrics():
    """Recoge las metricas de los ultimos 7 dias desde BD."""
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Gastos/Ingresos ultimos 7 dias (no duplicate, no rejected)
        cur.execute("""
            SELECT
                COALESCE(SUM(total_amount) FILTER (WHERE type='expense'), 0) AS total_expense,
                COALESCE(SUM(total_amount) FILTER (WHERE type='income'), 0) AS total_income,
                COUNT(*) FILTER (WHERE type='expense') AS expense_count,
                COUNT(*) FILTER (WHERE type='income') AS income_count
            FROM invoices
            WHERE invoice_date >= CURRENT_DATE - INTERVAL '7 days'
              AND status NOT IN ('duplicate', 'rejected')
              AND is_invoice = true
        """)
        cur_week = cur.fetchone()

        # Semana anterior (8..14 dias atras) para calcular delta
        cur.execute("""
            SELECT
                COALESCE(SUM(total_amount) FILTER (WHERE type='expense'), 0) AS prev_total_expense
            FROM invoices
            WHERE invoice_date >= CURRENT_DATE - INTERVAL '14 days'
              AND invoice_date < CURRENT_DATE - INTERVAL '7 days'
              AND status NOT IN ('duplicate', 'rejected')
              AND is_invoice = true
        """)
        prev_week = cur.fetchone()

        # Top 3 categorias
        cur.execute("""
            SELECT c.name, SUM(i.total_amount) as total
            FROM invoices i
            JOIN categories c ON i.category_id = c.id
            WHERE i.invoice_date >= CURRENT_DATE - INTERVAL '7 days'
              AND i.status NOT IN ('duplicate', 'rejected')
              AND i.type = 'expense'
              AND i.is_invoice = true
            GROUP BY c.name ORDER BY total DESC LIMIT 3
        """)
        top_cats = cur.fetchall()

        # Top 3 proveedores
        cur.execute("""
            SELECT v.name, SUM(i.total_amount) as total
            FROM invoices i
            JOIN vendors v ON i.vendor_id = v.id
            WHERE i.invoice_date >= CURRENT_DATE - INTERVAL '7 days'
              AND i.status NOT IN ('duplicate', 'rejected')
              AND i.type = 'expense'
              AND i.is_invoice = true
            GROUP BY v.name ORDER BY total DESC LIMIT 3
        """)
        top_vendors = cur.fetchall()

        # Pendientes
        cur.execute("""
            SELECT COUNT(*) AS pending_count FROM invoices
            WHERE status = 'pending' AND type = 'expense' AND is_invoice = true
        """)
        pending = cur.fetchone()

        # Calcula delta
        delta = None
        prev = float(prev_week.get('prev_total_expense') or 0)
        cur_exp = float(cur_week.get('total_expense') or 0)
        if prev > 0:
            delta = ((cur_exp - prev) / prev) * 100

        return {
            'expense_count': cur_week['expense_count'],
            'income_count': cur_week['income_count'],
            'total_expense': cur_week['total_expense'],
            'total_income': cur_week['total_income'],
            'neto': cur_week['total_income'] - cur_week['total_expense'],
            'expense_delta_pct': delta,
            'top_categories': top_cats,
            'top_vendors': top_vendors,
            'pending_count': pending['pending_count'],
        }
    finally:
        conn.close()


def main():
    logger.info("Generando resumen semanal...")
    try:
        metrics = _collect_metrics()
    except Exception as e:
        logger.error(f"Error recogiendo metricas: {type(e).__name__}: {e}")
        return 1

    msg = _build_message(metrics)
    logger.info(f"Resumen:\n{msg}")

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        logger.warning(
            "TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados. "
            "Resumen solo disponible en logs."
        )
        return 0  # OK, solo logueado

    sent = _send_telegram(token, chat_id, msg)
    if sent:
        logger.info("Resumen enviado por Telegram OK.")
        return 0
    else:
        logger.error("Telegram fallo. Resumen queda en logs (data/weekly.log).")
        return 2


if __name__ == '__main__':
    sys.exit(main() or 0)
