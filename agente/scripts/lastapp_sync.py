import os
import json
import requests
import logging
from pathlib import Path
from datetime import datetime, timezone

# Cargar .env del workspace (mismo patron que run_all.py)
WORKSPACE = Path(__file__).resolve().parent.parent.parent
env_file = WORKSPACE / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from db_writer import update_last_sync, get_last_sync, log_agent
from db_connection import get_conn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def _sanitize_error(e):
    """Limpia mensajes de error para evitar filtrar tokens de API."""
    msg = str(e)
    for needle in ('Bearer ', 'Authorization', 'api_key', 'bearer'):
        idx = msg.find(needle)
        if idx >= 0:
            msg = msg[:idx + len(needle)] + '[REDACTED]'
    return msg


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


def _save_bill_to_lastapp_table(bill):
    """Inserta una factura de Last.app en la tabla nativa lastapp_bills.

    FIX 2026-06-22: el sync original llamaba a save_invoice() que apunta a la
    tabla 'invoices' (legacy, sistema Gmail de gastos de proveedores). Esa tabla
    rechaza source='erp'+type='income' por check constraint, lo que provocaba
    que TODAS las ventas del bar fallaran silenciosamente. Las 8.011 facturas
    existentes en lastapp_bills vienen del pull masivo manual (commit 1f4f5a7
    del 17-06), NO del sync.

    lastapp_bills es la tabla correcta para ventas del TPV Last.app.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        bill_id = bill.get('id')
        if not bill_id:
            raise ValueError("Factura sin id de Last.app")

        company = bill.get('company') or {}
        customer = bill.get('customer') or {}

        cur.execute("""
            INSERT INTO lastapp_bills (
                id, number, creation_time, finalizing_time,
                total_cents, tax_cents, taxable_base_cents, tax_percentage,
                delivery_fee_cents, minimum_basket_surcharge_cents,
                terrace_surcharge_cents, discount_total_cents,
                company_name, company_tax_id, company_address,
                customer_name, customer_tax_id,
                deleted, location_id, organization_id, raw_json
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s::jsonb
            )
            ON CONFLICT (id) DO UPDATE SET
                number = EXCLUDED.number,
                total_cents = EXCLUDED.total_cents,
                tax_cents = EXCLUDED.tax_cents,
                taxable_base_cents = EXCLUDED.taxable_base_cents,
                raw_json = EXCLUDED.raw_json,
                deleted = EXCLUDED.deleted
            RETURNING id
        """, (
            bill_id,
            bill.get('number'),
            bill.get('creationTime'),
            bill.get('finalizingTime'),
            int(bill.get('total', 0)),
            int(bill.get('tax', 0)),
            int(bill.get('taxableBase', 0)),
            int(bill.get('taxPercentage', 0)),
            int(bill.get('deliveryFee', 0)),
            int(bill.get('minimumBasketSurcharge', 0)),
            int(bill.get('terraceSurcharge', 0)),
            int(bill.get('discountTotal', 0)),
            company.get('name'),
            company.get('taxId'),
            company.get('address'),
            customer.get('name'),
            customer.get('taxId'),
            bool(bill.get('deleted', False)),
            bill.get('locationId'),
            bill.get('organizationId'),
            json.dumps(bill),
        ))
        cur.fetchone()
        conn.commit()
        return bill_id
    finally:
        conn.close()


def main():
    try:
        headers = _build_headers()
    except RuntimeError as e:
        logger.error(_sanitize_error(e))
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

            bill_id = _save_bill_to_lastapp_table(bill)
            total = float(bill.get('total', 0)) / 100
            logger.info("  Guardada en lastapp_bills: %s (%.2f EUR)", bill_id, total)
            processed += 1
        except Exception as e:
            logger.error("  Error con factura %s: %s", str(bill.get('id')), _sanitize_error(e))
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

            if bill_id:
                internal = _find_bill_by_id(bill_id)
                if internal:
                    _save_payment_to_lastapp_table(
                        bill_id=internal,
                        payment_date=payment_date,
                        amount_cents=int(pay.get('amount', 0)),
                        method=method,
                        payment_id=pay.get('id'),
                        raw=pay,
                    )
                    logger.info("  Pago enlazado: %s -> %s (%.2f EUR)", method, bill_id, amount)
                else:
                    logger.warning("  Pago sin bill en BD (billId=%s): %s", bill_id, str(pay.get('id')))
            else:
                logger.warning("  Pago sin billId (omitido): %s", str(pay.get('id')))
            processed += 1
        except Exception as e:
            logger.error("  Error con pago %s: %s", str(pay.get('id')), _sanitize_error(e))
            errors += 1

    log_agent('lastapp_sync', 'info' if errors == 0 else 'warning',
              "Procesadas " + str(processed) + " facturas/pagos, " + str(errors) + " errores")
    update_last_sync('erp', status='error' if errors > 0 else 'ok')
    logger.info("Lastapp: " + str(processed) + " procesadas, " + str(errors) + " errores")
    return 0 if errors == 0 else 1


def _find_bill_by_id(bill_id):
    """Busca un bill por su UUID (id de Last.app) en lastapp_bills."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM lastapp_bills WHERE id = %s LIMIT 1", (bill_id,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _save_payment_to_lastapp_table(bill_id, payment_date, amount_cents, method, payment_id, raw):
    """Inserta un pago en lastapp_payments."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO lastapp_payments (
                id, bill_id, creation_time, amount_cents, tip_cents, type, raw_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                amount_cents = EXCLUDED.amount_cents,
                raw_json = EXCLUDED.raw_json
        """, (
            payment_id,
            bill_id,
            payment_date or datetime.now(timezone.utc),
            amount_cents,
            int(raw.get('tip', 0)),
            method,
            json.dumps(raw),
        ))
        conn.commit()
    finally:
        conn.close()


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
        logger.error("Error fetching %s: %s", url, _sanitize_error(e))
        return []
    except Exception as e:
        logger.error("Error inesperado en %s: %s", url, _sanitize_error(e))
        return []


if __name__ == '__main__':
    import sys
    sys.exit(main())
