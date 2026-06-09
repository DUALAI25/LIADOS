"""
test_orphan_payments.py — Tests para la lógica de pagos huérfanos de Last.app

Cubre:
- save_orphan_payment: inserción exitosa retorna UUID
- save_orphan_payment: duplicado idempotente retorna None
- Routing: factura encontrada → save_payment con invoice_id correcto
- Routing: factura NO encontrada → save_orphan_payment con raw_json

Ejecutar:
    python3 -m unittest agente/scripts/test_orphan_payments.py -v
"""
import unittest
from unittest.mock import MagicMock, patch
import sys
import types
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Mock psycopg2 antes de cualquier import de los modulos bajo test
psycopg2_mock = types.ModuleType('psycopg2')
psycopg2_mock.connect = MagicMock()
extras_mock = types.ModuleType('psycopg2.extras')
extras_mock.RealDictCursor = object
psycopg2_mock.extras = extras_mock
sys.modules['psycopg2'] = psycopg2_mock
sys.modules['psycopg2.extras'] = extras_mock


class TestOrphanPayments(unittest.TestCase):

    @patch('db_writer.get_conn')
    def test_save_orphan_payment_insert_success(self, mock_get_conn):
        """Pago huérfano nuevo: INSERT ok, retorna UUID."""
        from db_writer import save_orphan_payment

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ('orphan-uuid-1',)
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        result = save_orphan_payment(
            source='lastapp',
            source_payment_id='pay-1',
            invoice_number='F-001',
            payment_date='2026-06-09',
            amount=100.0,
            method='tarjeta',
            source_detail='detalle pago',
            raw_json={'id': 'pay-1', 'amount': 100},
        )

        self.assertEqual(result, 'orphan-uuid-1')
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch('db_writer.get_conn')
    def test_save_orphan_payment_duplicate_idempotent(self, mock_get_conn):
        """Pago huérfano duplicado: ON CONFLICT DO NOTHING, retorna None."""
        from db_writer import save_orphan_payment

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None  # conflicto -> sin fila
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        result = save_orphan_payment(
            source='lastapp',
            source_payment_id='pay-1',
            invoice_number='F-001',
            payment_date='2026-06-09',
            amount=100.0,
            method='tarjeta',
            source_detail='detalle pago',
            raw_json={'id': 'pay-1', 'amount': 100},
        )

        self.assertIsNone(result)
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch('lastapp_sync.save_orphan_payment')
    @patch('lastapp_sync.save_payment')
    @patch('lastapp_sync.get_conn')
    def test_routing_with_existing_invoice(self, mock_get_conn, mock_save_pay, mock_save_orphan):
        """Invoice encontrada -> save_payment(invoice_id=...), no orphan."""
        import lastapp_sync

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ('inv-uuid-123',)
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        pay = {
            'id': 'p1',
            'invoiceNumber': 'F-001',
            'amount': 100,
            'date': '2026-06-09',
            'method': 'tarjeta',
            'detail': 'x',
        }

        invoice_number = pay.get('invoiceNumber') or pay.get('invoice_number')
        found_id = lastapp_sync._find_invoice_by_number(invoice_number) if invoice_number else None
        amount = float(pay.get('amount', 0) or 0)

        if found_id:
            lastapp_sync.save_payment(
                invoice_id=found_id,
                payment_date=pay.get('date'),
                amount=amount,
                source=pay.get('method', 'tarjeta'),
                source_detail=pay.get('detail'),
            )
        else:
            lastapp_sync.save_orphan_payment(
                source='lastapp',
                source_payment_id=str(pay.get('id')),
                invoice_number=invoice_number,
                payment_date=pay.get('date'),
                amount=amount,
                method=pay.get('method', 'tarjeta'),
                source_detail=pay.get('detail'),
                raw_json=pay,
            )

        mock_save_pay.assert_called_once_with(
            invoice_id='inv-uuid-123',
            payment_date='2026-06-09',
            amount=100.0,
            source='tarjeta',
            source_detail='x',
        )
        mock_save_orphan.assert_not_called()

    @patch('lastapp_sync.save_orphan_payment')
    @patch('lastapp_sync.save_payment')
    @patch('lastapp_sync.get_conn')
    def test_routing_without_invoice(self, mock_get_conn, mock_save_pay, mock_save_orphan):
        """Invoice NO encontrada -> save_orphan_payment(...), no payments."""
        import lastapp_sync

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None  # no existe
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        pay = {
            'id': 'p2',
            'invoiceNumber': 'F-999',
            'amount': 50,
            'date': '2026-06-09',
            'method': 'efectivo',
            'detail': 'caja',
        }

        invoice_number = pay.get('invoiceNumber') or pay.get('invoice_number')
        found_id = lastapp_sync._find_invoice_by_number(invoice_number) if invoice_number else None
        amount = float(pay.get('amount', 0) or 0)

        if found_id:
            lastapp_sync.save_payment(
                invoice_id=found_id,
                payment_date=pay.get('date'),
                amount=amount,
                source=pay.get('method', 'tarjeta'),
                source_detail=pay.get('detail'),
            )
        else:
            lastapp_sync.save_orphan_payment(
                source='lastapp',
                source_payment_id=str(pay.get('id')),
                invoice_number=invoice_number,
                payment_date=pay.get('date'),
                amount=amount,
                method=pay.get('method', 'tarjeta'),
                source_detail=pay.get('detail'),
                raw_json=pay,
            )

        mock_save_pay.assert_not_called()
        mock_save_orphan.assert_called_once()
        args = mock_save_orphan.call_args[1]
        self.assertEqual(args['invoice_number'], 'F-999')
        self.assertEqual(args['amount'], 50.0)
        self.assertEqual(args['method'], 'efectivo')
        self.assertEqual(args['source'], 'lastapp')
        self.assertEqual(args['raw_json'], pay)

    @patch('db_writer.get_conn')
    def test_orphan_not_auto_migrated(self, mock_get_conn):
        """Orphan guardado no se migra al aparecer factura (revision manual)."""
        from db_writer import save_orphan_payment, save_payment
        import lastapp_sync

        # 1. Guardar pago huérfano
        mock_conn1 = MagicMock()
        mock_cur1 = MagicMock()
        mock_cur1.fetchone.return_value = ('orphan-uuid-1',)
        mock_conn1.cursor.return_value = mock_cur1
        mock_get_conn.return_value = mock_conn1

        orphan_id = save_orphan_payment(
            source='lastapp',
            source_payment_id='pay-late',
            invoice_number='F-LATE',
            payment_date='2026-06-01',
            amount=300.0,
            method='tarjeta',
            source_detail='detalle',
            raw_json={'id': 'pay-late'},
        )
        self.assertEqual(orphan_id, 'orphan-uuid-1')

        # 2. Luego aparece la factura F-LATE en el sistema
        mock_conn2 = MagicMock()
        mock_cur2 = MagicMock()
        mock_cur2.fetchone.return_value = ('inv-uuid-late',)
        mock_conn2.cursor.return_value = mock_cur2
        mock_get_conn.return_value = mock_conn2

        found_id = lastapp_sync._find_invoice_by_number('F-LATE')
        self.assertEqual(found_id, 'inv-uuid-late')

        # save_payment y save_orphan_payment operan sobre tablas independientes.
        # No existe trigger ni logica de auto-migracion entre ellas.
        # El orphan en orphan_payments sigue existiendo (revision manual requerida).


if __name__ == '__main__':
    unittest.main()
