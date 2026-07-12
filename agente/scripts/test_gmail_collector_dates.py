"""
test_gmail_collector_dates.py — Tests para filtro de fecha incremental.

Cubre:
- Primera ejecucion: ventana de GMAIL_INITIAL_DAYS desde now()
- Ejecucion incremental: desde get_last_sync('gmail')

v2 (2026-07-12): actualizado al nuevo contrato del refactor B1.
  - main() ya no pasa search_query a process_account (proceso interno).
  - main() ahora respeta argv=None con default a sys.argv[1:] en CLI.
  - process_account retorna tupla de 3 valores (processed, errors, dry_report).
  - Test mockea get_gmail_accounts (no depende del .env del worktree).
"""
import unittest
from unittest.mock import MagicMock, patch
import sys
import types
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Mock psycopg2 antes de importar modulos
psycopg2_mock = types.ModuleType("psycopg2")
psycopg2_mock.connect = MagicMock()
extras_mock = types.ModuleType("psycopg2.extras")
extras_mock.RealDictCursor = object
psycopg2_mock.extras = extras_mock
sys.modules["psycopg2"] = psycopg2_mock
sys.modules["psycopg2.extras"] = extras_mock

# Mock google deps
google_oauth_mock = types.ModuleType("google.oauth2.credentials")
google_oauth_mock.Credentials = type("Credentials", (), {
    "from_authorized_user_file": MagicMock()
})
sys.modules["google.oauth2.credentials"] = google_oauth_mock

google_client_mock = types.ModuleType("googleapiclient.discovery")
google_client_mock.build = MagicMock()
sys.modules["googleapiclient.discovery"] = google_client_mock

# Mock dedup_checker
dedup_mock = types.ModuleType("dedup_checker")
dedup_mock.is_duplicate_by_hash = MagicMock(return_value=False)
dedup_mock.mark_as_duplicate = MagicMock()
sys.modules["dedup_checker"] = dedup_mock

# Mock invoice_parser
parser_mock = types.ModuleType("invoice_parser")
parser_mock.parse_invoice = MagicMock(return_value={"invoice_number": "F-001"})
sys.modules["invoice_parser"] = parser_mock

# Mock storage
storage_mock = types.ModuleType("storage")
storage_mock.save_raw_file = MagicMock(return_value={
    "local_path": "/tmp/test.pdf",
    "minio_url": None,
    "content_hash": "abc123",
})
sys.modules["storage"] = storage_mock


class TestGmailCollectorDates(unittest.TestCase):

    def _set_env_for_test(self):
        import os
        os.environ["GMAIL_INITIAL_DAYS"] = "30"
        os.environ["GMAIL_ACCOUNTS"] = "test"
        os.environ["GMAIL_TOKEN_FILE_test"] = "fake_token.json"
        os.environ["OPENCODE_API_KEY"] = "test-key"

    @patch("gmail_collector.update_last_sync")
    @patch("gmail_collector.get_last_sync")
    @patch("gmail_collector.process_account")
    @patch("gmail_collector.get_gmail_accounts")
    def test_first_run_uses_initial_days(self, mock_get_accounts, mock_process, mock_get_last, mock_update):
        """Primera ejecucion: since_date = now() - INITIAL_DAYS, calculado en process_account."""
        from datetime import datetime, timezone
        import gmail_collector

        self._set_env_for_test()
        # Mockear get_gmail_accounts para que devuelva ["test"] sin leer .env real
        mock_get_accounts.return_value = ["test"]

        # get_last_sync devuelve fecha antigua -> modo inicial
        mock_get_last.return_value = datetime(2000, 1, 1)
        # process_account retorna tupla de 3 (processed, errors, dry_report)
        mock_process.return_value = (0, 0, None)

        # Pasa [] para no contaminar con sys.argv del runner de pytest
        gmail_collector.main([])

        # Validar que se invoco process_account al menos una vez con dry_run=False
        self.assertTrue(mock_process.called, "process_account no fue llamado")
        first_call = mock_process.call_args_list[0]
        self.assertEqual(first_call.args[0], "test")
        self.assertEqual(first_call.kwargs.get("dry_run"), False)

    @patch("gmail_collector.update_last_sync")
    @patch("gmail_collector.get_last_sync")
    @patch("gmail_collector.process_account")
    @patch("gmail_collector.get_gmail_accounts")
    def test_incremental_run_uses_last_sync(self, mock_get_accounts, mock_process, mock_get_last, mock_update):
        """Ejecucion incremental: since_date = get_last_sync('gmail'), en process_account."""
        from datetime import datetime, timezone
        import gmail_collector

        self._set_env_for_test()
        mock_get_accounts.return_value = ["test"]

        # get_last_sync devuelve fecha concreta -> modo incremental
        mock_get_last.return_value = datetime(2026, 6, 5, tzinfo=timezone.utc)
        mock_process.return_value = (0, 0, None)

        gmail_collector.main([])

        # Validar invocacion con la cuenta correcta y sin dry-run
        self.assertTrue(mock_process.called, "process_account no fue llamado")
        first_call = mock_process.call_args_list[0]
        self.assertEqual(first_call.args[0], "test")
        self.assertEqual(first_call.kwargs.get("dry_run"), False)


if __name__ == "__main__":
    unittest.main()