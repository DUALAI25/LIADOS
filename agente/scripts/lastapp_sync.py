import os
import requests
import logging
from datetime import datetime

from db_writer import save_invoice, save_payment, update_last_sync, get_last_sync, log_agent
from dedup_checker import is_duplicate_by_number

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

API_URL = os.getenv('LASTAPP_API_URL', 'https://api.last.app/v2')
API_TOKEN = os.getenv('LASTAPP_API_TOKEN')


def main():
    if not API_TOKEN:
        logger.error("LASTAPP_API_TOKEN no configurado")
        return

    headers = {'Authorization': f'Bearer {API_TOKEN}'}
    last_sync = get_last_sync('erp')
    since = last_sync.strftime('%Y-%m-%dT%H:%M:%SZ')

    processed = 0
    errors = 0

    bills = _fetch_all(headers, f'{API_URL}/bills', {'since': since})
    logger.info(f"Lastapp: {len(bills)} facturas nuevas")

    for bill in bills:
        try:
            number = bill.get('number') or bill.get('id')
            total = float(bill.get('total', 0) or 0)

            if is_duplicate_by_number(number, total, bill.get('customerName', '')):
                logger.info(f"  Duplicado: {number}")
                continue

            data = {
                'invoice_number': number,
                'invoice_date': bill.get('date') or bill.get('createdAt'),
                'due_date': bill.get('dueDate'),
                'vendor_name': bill.get('customerName'),
                'vendor_tax_id': bill.get('customerTaxId'),
                'base_amount': float(bill.get('subtotal', 0) or 0),
                'tax_amount': float(bill.get('tax', 0) or 0),
                'total_amount': total,
                'currency': bill.get('currency', 'EUR'),
                'description': bill.get('description', ''),
                'confidence_score': 1.0,
            }
            inv_id = save_invoice(data, source='erp', source_id=bill.get('id'), inv_type='income')
            logger.info(f"  Guardada: {number} -> {inv_id}")
            processed += 1
        except Exception as e:
            logger.error(f"  Error con factura {bill.get('id')}: {e}")
            errors += 1

    payments = _fetch_all(headers, f'{API_URL}/payments', {'since': since})
    logger.info(f"Lastapp: {len(payments)} pagos nuevos")
    for pay in payments:
        try:
            save_payment(
                invoice_id=None,
                invoice_number=pay.get('invoiceNumber') or pay.get('invoice_number'),
                payment_date=pay.get('date'),
                amount=float(pay.get('amount', 0) or 0),
                source=pay.get('method', 'tarjeta'),
                source_detail=pay.get('detail')
            )
            processed += 1
        except Exception as e:
            logger.error(f"  Error con pago {pay.get('id')}: {e}")
            errors += 1

    log_agent('lastapp_sync', 'info' if errors == 0 else 'warning',
              f"Procesadas {processed} facturas, {errors} errores")
    update_last_sync('erp', status='error' if errors > 0 else 'ok')
    logger.info(f"Lastapp: {processed} procesadas, {errors} errores")


def _fetch_all(headers, url, params):
    results = []
    page = 1
    while True:
        params['page'] = page
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = data.get('data', data.get('results', data.get('items', [])))
            results.extend(items)
            pagination = data.get('pagination', data.get('meta', {}))
            total_pages = pagination.get('totalPages', pagination.get('lastPage', 1))
            if page >= total_pages:
                break
            page += 1
        except Exception as e:
            logger.error(f"Error fetching page {page}: {e}")
            break
    return results


if __name__ == '__main__':
    main()
