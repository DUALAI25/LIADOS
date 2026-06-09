import os
import requests
import logging
from datetime import datetime

from db_writer import save_invoice, save_payment, update_last_sync, get_last_sync, log_agent
from dedup_checker import is_duplicate_by_number

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

API_URL = os.getenv('LASTAPP_API_URL', 'https://api.last.app/v2')


def _build_headers():
    """Headers comunes para todas las llamadas a Last.app.

    Last.app v2 exige, ademas de Authorization, un header organizationID
    en cada peticion. locationID es opcional (si se omite, devuelve datos
    de todos los locales de la organizacion).
    """
    token = os.getenv('LASTAPP_API_TOKEN')
    org_id = os.getenv('LASTAPP_ORGANIZATION_ID')
    location_id = os.getenv('LASTAPP_LOCATION_ID')

    if not token:
        raise RuntimeError("Falta LASTAPP_API_TOKEN en .env")
    if not org_id:
        raise RuntimeError("Falta LASTAPP_ORGANIZATION_ID en .env")
    headers = {
        'Authorization': 'Bearer ' + token,
        'organizationID': org_id,
    }
    if location_id:
        headers['locationID'] = location_id
    return headers


def main():
    try:
        headers = _build_headers()
    except RuntimeError as e:
        logger.error(str(e))
        return 1

    last_sync = get_last_sync('erp')
    since = last_sync.strftime('%Y-%m-%dT%H:%M:%SZ')

    processed = 0
    errors = 0

    bills = _fetch_all(headers, API_URL + '/bills', {'since': since})
    logger.info("Lastapp: " + str(len(bills)) + " facturas nuevas")

    for bill in bills:
        try:
            number = bill.get('number') or bill.get('id')
            total = float(bill.get('total', 0) or 0)

            if is_duplicate_by_number(number, total, bill.get('customerName', '')):
                logger.info("  Duplicado: " + str(number))
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
            logger.info("  Guardada: " + str(number) + " -> " + str(inv_id))
            processed += 1
        except Exception as e:
            logger.error("  Error con factura " + str(bill.get('id')) + ": " + str(e))
            errors += 1

    payments = _fetch_all(headers, API_URL + '/payments', {'since': since})
    logger.info("Lastapp: " + str(len(payments)) + " pagos nuevos")
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
            logger.error("  Error con pago " + str(pay.get('id')) + ": " + str(e))
            errors += 1

    log_agent('lastapp_sync', 'info' if errors == 0 else 'warning',
              "Procesadas " + str(processed) + " facturas, " + str(errors) + " errores")
    update_last_sync('erp', status='error' if errors > 0 else 'ok')
    logger.info("Lastapp: " + str(processed) + " procesadas, " + str(errors) + " errores")
    return 0 if errors == 0 else 1


def _fetch_all(headers, url, params):
    """Hace paginacion completa de un endpoint.
    Returns: lista completa de items
    """
    results = []
    page = 1
    while True:
        # Copia params para no contaminar entre paginas
        page_params = dict(params)
        page_params['page'] = page
        try:
            resp = requests.get(url, headers=headers, params=page_params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = data.get('data', data.get('results', data.get('items', [])))
            results.extend(items)

            # Detectar si hay mas paginas
            if not items:
                break  # pagina vacia = fin

            pagination = data.get('pagination', data.get('meta', {}))
            total_pages = pagination.get('totalPages', pagination.get('lastPage', 1))

            if page >= total_pages:
                break
            page += 1
        except requests.exceptions.RequestException as e:
            logger.error("Error fetching " + url + " page " + str(page) + ": " + str(e))
            break
        except Exception as e:
            logger.error("Error inesperado en " + url + " page " + str(page) + ": " + str(e))
            break
    return results


if __name__ == '__main__':
    import sys
    sys.exit(main())
