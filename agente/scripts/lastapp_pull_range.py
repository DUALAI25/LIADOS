"""Pull one-shot de Last.app en un rango de fechas explicito.

Uso: python -m agente.scripts.lastapp_pull_range 2026-06-17 2026-06-22

NO actualiza sync_control.last_sync.
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

# Cargar .env del workspace
WORKSPACE = Path(__file__).resolve().parent.parent.parent
env_file = WORKSPACE / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from lastapp_sync import _build_headers, _fetch_all, _sanitize_error, _save_bill_to_lastapp_table

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def main():
    if len(sys.argv) != 3:
        print("Uso: python -m agente.scripts.lastapp_pull_range <startDate> <endDate>")
        sys.exit(2)

    start_date = sys.argv[1]
    end_date = sys.argv[2]

    try:
        datetime.strptime(start_date, '%Y-%m-%d')
        datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError as e:
        logger.error("Fecha invalida: %s", e)
        sys.exit(2)

    if start_date > end_date:
        logger.error("startDate > endDate, abortando")
        sys.exit(2)

    try:
        headers = _build_headers()
    except RuntimeError as e:
        logger.error(_sanitize_error(e))
        return 1

    location_id = os.getenv('LASTAPP_LOCATION_ID')
    if not location_id:
        logger.error("Falta LASTAPP_LOCATION_ID en .env")
        return 1

    api_url = os.getenv('LASTAPP_API_URL', 'https://api.last.app/v2')

    logger.info("=== Pull one-shot %s -> %s ===", start_date, end_date)

    bill_params = {
        'locationId': location_id,
        'startDate': start_date,
        'endDate': end_date,
    }
    bills = _fetch_all(headers, api_url + '/bills', bill_params)
    logger.info("API devolvio %d facturas en rango %s - %s", len(bills), start_date, end_date)

    processed = 0
    errors = 0
    for bill in bills:
        try:
            if bill.get('deleted'):
                continue
            _save_bill_to_lastapp_table(bill)
            processed += 1
        except Exception as e:
            errors += 1
            logger.error("Error procesando factura %s: %s", bill.get('id'), _sanitize_error(e))

    logger.info("=== Pull one-shot terminado: %d procesadas, %d errores ===", processed, errors)
    return 0 if errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
