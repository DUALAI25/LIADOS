import os
import requests
import logging
from datetime import datetime, timezone

from db_writer import save_invoice, save_payment, save_orphan_payment, update_last_sync, get_last_sync, log_agent
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
    start_date = last_sync.strftime('%Y-%m-%d')
    end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    location_id = os.getenv('LASTAPP_LOCATION_ID')

    if not location_id:
        logger.error("Falta LASTAPP_LOCATION_ID en .env")
        return 1

    processed = 0
    errors = 0

    bill_params = {
        'locationId': location_id,
        'startDate': start_date,
        'endDate': end_date,
    }
    bills = _fetch_all(headers, API_URL + '/bills', bill_params)
    logger.info("Lastapp: %d facturas en rango %s - %s", len(bills), start_date, end_date)

    for bill in bills:
        try:
            if bill.get('deleted'):
                continue

            number = bill.get('number') or bill.get('id')
            total = float(bill['total']) / 100

            data = {
                'invoice_number': number,
                'invoice_date': bill.get('creationTime'),
                'due_date': bill.get('finalizingTime'),
                'vendor_name': (bill.get('company') or {}).get('name'),
                'vendor_tax_id': (bill.get('company') or {}).get('taxId'),
                'base_amount': float(bill.get('taxableBase', 0)) / 100,
                'tax_amount': float(bill.get('tax', 0)) / 100,
                'total_amount': total,
                'currency': 'EUR',
                'description': '',
                'confidence_score': 1.0,
            }
            inv_id = save_invoice(data, source='erp', source_id=bill.get('id'), inv_type='income')
            logger.info("  Guardada: %s -> %s (%.2f EUR)", number, str(inv_id), total)
            processed += 1
        except Exception as e:
            logger.error("  Error con factura %s: %s", str(bill.get('id')), str(e))
            errors += 1

    pay_params = {
        'locationId': location_id,
        'startDate': start_date,
        'endDate': end_date,
    }
    payments = _fetch_all(headers, API_URL + '/payments', pay_params)
    logger.info("Lastapp: %d pagos en rango %s - %s", len(payments), start_date, end_date)
    for pay in payments:
        try:
            if pay.get('deleted'):
                continue

            bill_id = pay.get('billId')
            amount = float(pay.get('amount', 0)) / 100
            payment_date = pay.get('creationTime')
            method = pay.get('type', 'tarjeta')
            source_payment_id = str(pay.get('id')) if pay.get('id') else None

            if bill_id:
                logger.info("  Pago enlazado: %s -> %s (%.2f EUR)", method, bill_id, amount)
                save_payment(
                    invoice_id=bill_id,
                    payment_date=payment_date,
                    amount=amount,
                    source=method,
                    source_detail=source_payment_id,
                )
            else:
                logger.warning("  Pago sin billId (omitido): %s", source_payment_id)
            processed += 1
        except Exception as e:
            logger.error("  Error con pago %s: %s", str(pay.get('id')), str(e))
            errors += 1

    log_agent('lastapp_sync', 'info' if errors == 0 else 'warning',
              "Procesadas " + str(processed) + " facturas, " + str(errors) + " errores")
    update_last_sync('erp', status='error' if errors > 0 else 'ok')
    logger.info("Lastapp: " + str(processed) + " procesadas, " + str(errors) + " errores")
    return 0 if errors == 0 else 1


def _fetch_all(headers, url, params):
    """Llama un endpoint de Last.app y devuelve el array de items.
    La API v2 devuelve array plano, sin paginacion.
    """
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        logger.warning("Respuesta inesperada de %s: %s", url, str(data)[:200])
        return []
    except requests.exceptions.RequestException as e:
        logger.error("Error fetching %s: %s", url, str(e))
        return []
    except Exception as e:
        logger.error("Error inesperado en %s: %s", url, str(e))
        return []


if __name__ == '__main__':
    import sys
    sys.exit(main())
