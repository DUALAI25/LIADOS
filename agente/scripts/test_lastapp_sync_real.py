"""
test_lastapp_sync_real.py — Tests para lastapp_sync.py contra API real

Mockea requests.get para verificar:
- Query params correctos (locationId, startDate, endDate)
- Importes divididos por 100 (centimos -> EUR)
- Facturas deleted filtradas

Ejecutar:
    python3 agente/scripts/test_lastapp_sync_real.py
"""
import unittest
from unittest.mock import MagicMock, patch
import sys
import types
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Mock psycopg2
psycopg2_mock = types.ModuleType('psycopg2')
psycopg2_mock.connect = MagicMock()
extras_mock = types.ModuleType('psycopg2.extras')
extras_mock.RealDictCursor = object
psycopg2_mock.extras = extras_mock
sys.modules['psycopg2'] = psycopg2_mock
sys.modules['psycopg2.extras'] = extras_mock

# Mock dedup_checker (no DB real)
dedup_mock = types.ModuleType('dedup_checker')
dedup_mock.is_duplicate_by_number = MagicMock(return_value=False)
sys.modules['dedup_checker'] = dedup_mock

# Mock db_writer methods
def fake_save_invoice(data, source, source_id, inv_type='expense', minio_url=None):
    return 'inv-uuid-123'

def fake_get_last_sync(source):
    from datetime import datetime
    return datetime(2026, 6, 1)

FakeResponse = MagicMock()

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
    'deleted': False,
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


class TestLastappSyncBills(unittest.TestCase):

    def setUp(self):
        import os
        os.environ['DB_HOST'] = 'localhost'
        os.environ['DB_PORT'] = '5432'
        os.environ['DB_NAME'] = 'test'
        os.environ['DB_USER'] = 'test'
        os.environ['DB_PASSWORD'] = 'test'

    @patch('db_writer.get_conn')
    @patch('db_writer.save_invoice')
    @patch('db_writer.get_last_sync')
    @patch('requests.get')
    def test_fetch_all_uses_correct_params(self, mock_get, mock_last_sync, mock_save_inv, mock_get_conn):
        """_fetch_all llama con los query params correctos."""
        import lastapp_sync

        mock_last_sync.return_value = __import__('datetime').datetime(2026, 6, 1)
        mock_save_inv.return_value = 'inv-uuid-1'

        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        import os
        os.environ['LASTAPP_API_TOKEN'] = 'test-token'
        os.environ['LASTAPP_ORGANIZATION_ID'] = 'org-1'
        os.environ['LASTAPP_LOCATION_ID'] = 'loc-1'

        headers = lastapp_sync._build_headers()
        result = lastapp_sync._fetch_all(headers, 'https://api.last.app/v2/bills', {
            'locationId': 'loc-1',
            'startDate': '2026-06-01',
            'endDate': '2026-06-10',
        })

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertEqual(call_args[0][0], 'https://api.last.app/v2/bills')
        self.assertEqual(call_args[1]['params']['locationId'], 'loc-1')
        self.assertEqual(call_args[1]['params']['startDate'], '2026-06-01')
        self.assertEqual(call_args[1]['params']['endDate'], '2026-06-10')

    @patch('lastapp_sync.save_invoice')
    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_bill_amounts_divided_by_100(self, mock_headers, mock_fetch, mock_last_sync, mock_save_inv):
        """Importes en centimos se dividen por 100 para guardar en EUR."""
        import lastapp_sync
        from datetime import datetime

        mock_headers.return_value = {'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_save_inv.return_value = 'inv-uuid-1'

        mock_fetch.side_effect = [
            [BILL_FIXTURE],   # bills
            [],                # payments
        ]

        import os
        os.environ['LASTAPP_LOCATION_ID'] = 'loc-1'

        lastapp_sync.main()

        # Verificar que save_invoice recibio los importes / 100
        call_kwargs = mock_save_inv.call_args[1]
        data = mock_save_inv.call_args[0][0]
        self.assertAlmostEqual(data['total_amount'], 13.00)
        self.assertAlmostEqual(data['base_amount'], 11.82)
        self.assertAlmostEqual(data['tax_amount'], 1.18)
        self.assertEqual(data['invoice_number'], 'LS1-7061')
        self.assertEqual(data['vendor_name'], 'Vamos al lio S.L.')
        self.assertEqual(data['vendor_tax_id'], 'B22774590')

    @patch('lastapp_sync.save_invoice')
    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_deleted_bills_are_filtered(self, mock_headers, mock_fetch, mock_last_sync, mock_save_inv):
        """Facturas con deleted=true NO se guardan."""
        import lastapp_sync
        from datetime import datetime

        mock_headers.return_value = {'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_save_inv.return_value = 'inv-uuid-1'

        mock_fetch.side_effect = [
            [BILL_DELETED],    # solo una factura deleted
            [],                # payments
        ]

        import os
        os.environ['LASTAPP_LOCATION_ID'] = 'loc-1'

        lastapp_sync.main()

        # save_invoice NO debe ser llamada porque la factura esta deleted
        mock_save_inv.assert_not_called()

    @patch('lastapp_sync.save_payment')
    @patch('lastapp_sync.save_invoice')
    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_payments_uses_correct_query_params(
        self, mock_headers, mock_fetch, mock_last_sync, mock_save_inv, mock_save_pay
    ):
        """Payments usa locationId + startDate + endDate como query params."""
        from datetime import datetime

        mock_headers.return_value = {
            'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_save_inv.return_value = 'inv-uuid-1'
        mock_save_pay.return_value = 'pay-uuid-1'

        calls = []
        def capture_fetch(*args, **kwargs):
            calls.append((args, kwargs))
            if '/bills' in args[1]:
                return [BILL_FIXTURE]
            if '/payments' in args[1]:
                return [PAYMENT_FIXTURE]
            return []
        mock_fetch.side_effect = capture_fetch

        import os
        os.environ['LASTAPP_LOCATION_ID'] = 'loc-1'

        import lastapp_sync
        lastapp_sync.main()

        pay_call = [c for c in calls if '/payments' in c[0][1]]
        self.assertEqual(len(pay_call), 1)
        pay_params = pay_call[0][0][2]
        self.assertEqual(pay_params['locationId'], 'loc-1')
        self.assertIn('startDate', pay_params)
        self.assertIn('endDate', pay_params)

    @patch('lastapp_sync.save_payment')
    @patch('lastapp_sync.save_invoice')
    @patch('lastapp_sync.get_last_sync')
    @patch('lastapp_sync._fetch_all')
    @patch('lastapp_sync._build_headers')
    def test_payment_links_by_billId_not_number(
        self, mock_headers, mock_fetch, mock_last_sync, mock_save_inv, mock_save_pay
    ):
        """Pago enlaza por billId (UUID directo), no por invoice_number."""
        from datetime import datetime

        mock_headers.return_value = {
            'Authorization': 'Bearer x', 'organizationID': 'o', 'locationID': 'l'}
        mock_last_sync.return_value = datetime(2026, 6, 1)
        mock_save_inv.return_value = 'inv-uuid-1'
        mock_save_pay.return_value = 'pay-uuid-1'

        mock_fetch.side_effect = [
            [],                # bills (vacio, no importa)
            [PAYMENT_FIXTURE], # payments
        ]

        import os
        os.environ['LASTAPP_LOCATION_ID'] = 'loc-1'

        import lastapp_sync
        lastapp_sync.main()

        mock_save_pay.assert_called_once_with(
            invoice_id='bill-uuid-1',
            payment_date='2026-06-01T11:29:05.000Z',
            amount=13.00,
            source='card',
            source_detail=None,
        )


if __name__ == '__main__':
    unittest.main()
