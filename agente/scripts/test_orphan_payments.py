"""
test_orphan_payments.py — Tests para la lógica de pagos huérfanos

Cubre:
- save_orphan_payment: inserción exitosa retorna UUID
- save_orphan_payment: duplicado idempotente retorna None
- save_orphan_payment: marcado como DEPRECATED para Last.app

Ejecutar:
    python3 agente/scripts/test_orphan_payments.py
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

    def test_save_orphan_payment_is_marked_deprecated(self):
        """save_orphan_payment debe estar marcado como no-usar-desde-Last.app."""
        from db_writer import save_orphan_payment
        doc = save_orphan_payment.__doc__
        self.assertIn("DEPRECATED", doc)
        self.assertIn("Last.app", doc)


if __name__ == '__main__':
    unittest.main()
