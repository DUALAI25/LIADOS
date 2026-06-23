"""
test_lastapp_sync_real.py — Tests para lastapp_sync.py (refactor 2026-06-22)

El refactor del 22-06 cambió la API:
  - save_invoice(data, source, source_id, ...) → _save_bill_to_lastapp_table(bill)
  - save_payment(...) → _save_payment_to_lastapp_table(bill_id, ...)
  - _find_invoice_by_source_id(...) → _find_bill_by_id(bill_id)

Objetivo de los tests:
  - Query params correctos (locationId, startDate, endDate)
  - Importes se mantienen en CENTIMOS en la BD
  - Facturas deleted se filtran antes de persistir
  - Pagos sin billId se omiten
  - Pagos enlazan por billId (UUID de Last.app)

CRÍTICO: NO usar `sys.modules['db_writer'] = mock` a nivel de módulo.
Eso contamina los tests que se ejecutan DESPUÉS de este archivo en la misma
sesión pytest (e.g. test_orphan_payments.py, test_parsers.py que importan
gmail_collector → db_writer real).

En su lugar, importar lastapp_sync UNA SOLA VEZ y parchear sus atributos
con MagicMock localmente en cada test.

Ejecutar:
    python3 -m pytest agente/scripts/test_lastapp_sync_real.py
"""
import unittest
from unittest.mock import MagicMock, patch
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Importar lastapp_sync UNA VEZ al cargar el módulo. Esto importa db_writer
# y gmail_collector de forma natural. Los tests luego parchean los métodos
# específicos de lastapp_sync con @patch, sin tocar sys.modules.
import lastapp_sync  # noqa: E402

# Constants
BILL_FIXTURE = {
    'id': 'bill-uuid-1',
    'number': 'LS1-7061',
    'total': 1300,
    'tax': 118,
    'taxableBase': 1182,
    'taxPercentage': 10,
    'creationTime': '2026-06-01T11:29:05.000Z',
    'finalizingTime': '2026-06-01T11:29:05.000Z',
    'company': {'name': 'Vamos al lio S.L.', 'taxId': 'B22774590'},
    'customer': {'name': 'Cliente Mostrador'},
    'deleted': False,
    'locationId': 'loc-1',
    'organizationId': 'org-1',
}

BILL_DELETED = dict(BILL_FIXTURE, id='bill-deleted', number='LS1-DEL', deleted=True)

PAYMENT_FIXTURE = {
    'id': 'pay-uuid-1',
    'type': 'card',
    'amount': 1300,
    'billId': 'bill-uuid-1',
    'creationTime': '2026-06-01T11:29:05.000Z',
    'deleted': False,
    'tip': 0,
}

PAYMENT_DELETED = dict(PAYMENT_FIXTURE, id='pay-deleted', deleted=True)

PAYMENT_NO_BILLID = dict(PAYMENT_FIXTURE, id='pay-no-billid', billId=None)


def _set_env():
    os.environ['LASTAPP_API_TOKEN'] = 'test-token'
    os.environ['LASTAPP_ORGANIZATION_ID'] = 'org-1'
    os.environ['LASTAPP_LOCATION_ID'] = 'loc-1'


class TestLastappSyncFetchAll(unittest.TestCase):
    """Verifica que _fetch_all pasa los query params correctos a requests.get."""

    def setUp(self):
        _set_env()

    @patch('lastapp_sync.requests.get')
    def test_fetch_all_uses_correct_params(self, mock_get):
        """_fetch_all llama con los query params correctos."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        headers = lastapp_sync._build_headers()
        result = lastapp_sync._fetch_all(
            headers, 'https://api.last.app/v2/bills',
            {'locationId': 'loc-1', 'startDate': '2026-06-01', 'endDate': '2026-06-10'}
        )

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertEqual(call_args[0][0], 'https://api.last.app/v2/bills')
        self.assertEqual(call_args[1]['params']['locationId'], 'loc-1')
        self.assertEqual(call_args[1]['params']['startDate'], '2026-06-01')
        self.assertEqual(call_args[1]['params']['endDate'], '2026-06-10')


class TestLastappSyncBills(unittest.TestCase):
    """Verifica comportamiento de main() para facturas."""

    def setUp(self):
        _set_env()

    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._save_bill_to_lastapp_table')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_bill_amounts_stored_in_cents(
        self, mock_headers, mock_fetch, mock_save, mock_last_sync
    ):
        """Importes en centimos se mantienen en centimos en BD."""
        from datetime import datetime
        mock_headers.return_value = {'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_fetch.side_effect = [[BILL_FIXTURE], []]
        mock_save.return_value = 'bill-uuid-1'

        lastapp_sync.main()

        mock_save.assert_called_once()
        bill_arg = mock_save.call_args[0][0]
        self.assertEqual(bill_arg['total'], 1300)
        self.assertEqual(bill_arg['tax'], 118)
        self.assertEqual(bill_arg['taxableBase'], 1182)
        self.assertEqual(bill_arg['number'], 'LS1-7061')
        self.assertEqual(bill_arg['company']['name'], 'Vamos al lio S.L.')
        self.assertEqual(bill_arg['company']['taxId'], 'B22774590')

    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._save_bill_to_lastapp_table')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_deleted_bills_are_filtered(
        self, mock_headers, mock_fetch, mock_save, mock_last_sync
    ):
        """Facturas con deleted=true NO se persisten."""
        from datetime import datetime
        mock_headers.return_value = {'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_fetch.side_effect = [[BILL_DELETED], []]
        mock_save.return_value = 'bill-deleted'

        lastapp_sync.main()

        mock_save.assert_not_called()


class TestLastappSyncPayments(unittest.TestCase):
    """Verifica comportamiento de main() para pagos."""

    def setUp(self):
        _set_env()

    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._save_payment_to_lastapp_table')
    @patch('lastapp_sync._find_bill_by_id')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_payments_uses_correct_query_params(
        self, mock_headers, mock_fetch, mock_find_bill, mock_save_pay, mock_last_sync
    ):
        """Payments se consulta con locationId + startDate + endDate."""
        from datetime import datetime
        mock_headers.return_value = {
            'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_find_bill.return_value = 'inv-internal-uuid-1'

        calls = []
        def capture_fetch(headers, url, params):
            calls.append((url, params))
            if '/bills' in url:
                return []
            if '/payments' in url:
                return [PAYMENT_FIXTURE]
            return []
        mock_fetch.side_effect = capture_fetch
        mock_save_pay.return_value = 'pay-uuid-1'

        lastapp_sync.main()

        pay_call = [c for c in calls if '/payments' in c[0]]
        self.assertEqual(len(pay_call), 1)
        pay_params = pay_call[0][1]
        self.assertEqual(pay_params['locationId'], 'loc-1')
        self.assertIn('startDate', pay_params)
        self.assertIn('endDate', pay_params)

    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._save_payment_to_lastapp_table')
    @patch('lastapp_sync._find_bill_by_id')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_payment_links_by_billId(
        self, mock_headers, mock_fetch, mock_find_bill, mock_save_pay, mock_last_sync
    ):
        """Pago enlaza por billId (UUID de Last.app) buscando en lastapp_bills."""
        from datetime import datetime
        mock_headers.return_value = {
            'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_find_bill.return_value = 'inv-internal-uuid-from-bill'
        mock_fetch.side_effect = [[], [PAYMENT_FIXTURE]]
        mock_save_pay.return_value = 'pay-uuid-1'

        lastapp_sync.main()

        mock_find_bill.assert_called_with('bill-uuid-1')

        mock_save_pay.assert_called_once()
        kwargs = mock_save_pay.call_args.kwargs
        self.assertEqual(kwargs['bill_id'], 'inv-internal-uuid-from-bill')
        self.assertEqual(kwargs['amount_cents'], 1300)
        self.assertEqual(kwargs['method'], 'card')
        self.assertEqual(kwargs['payment_id'], 'pay-uuid-1')
        self.assertEqual(kwargs['payment_date'], '2026-06-01T11:29:05.000Z')

    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._save_payment_to_lastapp_table')
    @patch('lastapp_sync._find_bill_by_id')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_payment_without_billId_is_skipped(
        self, mock_headers, mock_fetch, mock_find_bill, mock_save_pay, mock_last_sync
    ):
        """Pago sin billId se omite (no se puede enlazar)."""
        from datetime import datetime
        mock_headers.return_value = {
            'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_fetch.side_effect = [[], [PAYMENT_NO_BILLID]]
        mock_save_pay.return_value = 'pay-uuid-1'

        lastapp_sync.main()

        mock_save_pay.assert_not_called()
        mock_find_bill.assert_not_called()

    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._save_payment_to_lastapp_table')
    @patch('lastapp_sync._find_bill_by_id')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_deleted_payments_are_filtered(
        self, mock_headers, mock_fetch, mock_find_bill, mock_save_pay, mock_last_sync
    ):
        """Pagos con deleted=true NO se persisten."""
        from datetime import datetime
        mock_headers.return_value = {
            'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_fetch.side_effect = [[], [PAYMENT_DELETED]]

        lastapp_sync.main()

        mock_save_pay.assert_not_called()


if __name__ == '__main__':
    unittest.main()