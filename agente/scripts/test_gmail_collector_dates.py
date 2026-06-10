"""
test_gmail_collector_dates.py — Tests para filtro de fecha incremental

Cubre:
- Primera ejecucion: ventana de GMAIL_INITIAL_DAYS desde now()
- Ejecucion incremental: desde get_last_sync('gmail')

Ejecutar:
    python3 agente/scripts/test_gmail_collector_dates.py
"""
import unittest
from unittest.mock import MagicMock, patch
import sys
import types
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Mock psycopg2 antes de importar modulos
psycopg2_mock = types.ModuleType('psycopg2')
psycopg2_mock.connect = MagicMock()
extras_mock = types.ModuleType('psycopg2.extras')
extras_mock.RealDictCursor = object
psycopg2_mock.extras = extras_mock
sys.modules['psycopg2'] = psycopg2_mock
sys.modules['psycopg2.extras'] = extras_mock

# Mock google deps
google_oauth_mock = types.ModuleType('google.oauth2.credentials')
google_oauth_mock.Credentials = type('Credentials', (), {
    'from_authorized_user_file': MagicMock()
})
sys.modules['google.oauth2.credentials'] = google_oauth_mock

google_client_mock = types.ModuleType('googleapiclient.discovery')
google_client_mock.build = MagicMock()
sys.modules['googleapiclient.discovery'] = google_client_mock

# Mock dedup_checker
dedup_mock = types.ModuleType('dedup_checker')
dedup_mock.is_duplicate_by_hash = MagicMock(return_value=False)
dedup_mock.mark_as_duplicate = MagicMock()
sys.modules['dedup_checker'] = dedup_mock

# Mock invoice_parser
parser_mock = types.ModuleType('invoice_parser')
parser_mock.parse_invoice = MagicMock(return_value={'invoice_number': 'F-001'})
sys.modules['invoice_parser'] = parser_mock

# Mock storage
storage_mock = types.ModuleType('storage')
storage_mock.save_raw_file = MagicMock(return_value={
    'local_path': '/tmp/test.pdf',
    'minio_url': None,
    'content_hash': 'abc123',
})
sys.modules['storage'] = storage_mock


class TestGmailCollectorDates(unittest.TestCase):

    def _set_env_for_test(self):
        import os
        os.environ['GMAIL_INITIAL_DAYS'] = '30'
        os.environ['GMAIL_ACCOUNTS'] = 'test'
        os.environ['GMAIL_TOKEN_FILE_test'] = 'fake_token.json'
        os.environ['OPENCODE_API_KEY'] = 'test-key'

    @patch('gmail_collector.update_last_sync')
    @patch('gmail_collector.get_last_sync')
    @patch('gmail_collector.process_account')
    def test_first_run_uses_initial_days(self, mock_process, mock_get_last, mock_update):
        """Primera ejecucion: since_date = now() - INITIAL_DAYS."""
        from datetime import datetime, timedelta, timezone
        import gmail_collector

        self._set_env_for_test()

        # get_last_sync devuelve fecha antigua -> modo inicial
        mock_get_last.return_value = datetime(2000, 1, 1)
        mock_process.return_value = (0, 0)

        gmail_collector.main()

        # Verificar que search_query incluye after: con fecha correcta
        call_kwargs = mock_process.call_args[1]
        search_query = call_kwargs['search_query']
        self.assertIn('after:', search_query)

        # La fecha debe ser aproximadamente 30 dias atras
        expected_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y/%m/%d')
        self.assertIn(expected_date, search_query)

    @patch('gmail_collector.update_last_sync')
    @patch('gmail_collector.get_last_sync')
    @patch('gmail_collector.process_account')
    def test_incremental_run_uses_last_sync(self, mock_process, mock_get_last, mock_update):
        """Ejecucion incremental: since_date = get_last_sync('gmail')."""
        from datetime import datetime, timezone
        import gmail_collector

        self._set_env_for_test()

        # get_last_sync devuelve fecha concreta -> modo incremental
        mock_get_last.return_value = datetime(2026, 6, 5, tzinfo=timezone.utc)
        mock_process.return_value = (0, 0)

        gmail_collector.main()

        call_kwargs = mock_process.call_args[1]
        search_query = call_kwargs['search_query']
        self.assertIn('after:', search_query)
        self.assertIn('2026/06/05', search_query)


if __name__ == '__main__':
    unittest.main()
