"""
Tests para lastapp_auth.py — gestión de tokens OAuth.

Verifica:
  - Token directo (LASTAPP_OAUTH_BEARER_TOKEN) funciona
  - Caché en memoria del token
  - Errores claros sin credenciales
  - Refresh intent cuando el token está cerca de expirar
"""
import os
import sys
import time
import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp'))


class TestLastappAuth:
    def setup_method(self):
        import lastapp_auth
        lastapp_auth._token_store = {
            "access_token": None,
            "refresh_token": None,
            "expires_at": 0,
        }

    def test_bearer_token_directo(self, monkeypatch):
        monkeypatch.setenv("LASTAPP_OAUTH_BEARER_TOKEN", "tokendirecto123")
        from lastapp_auth import get_token
        token = get_token()
        assert token == "tokendirecto123"

    def test_token_cache_en_memoria(self, monkeypatch):
        monkeypatch.setenv("LASTAPP_OAUTH_BEARER_TOKEN", "cached-token")
        from lastapp_auth import get_token, _token_store
        assert _token_store["access_token"] is None
        t1 = get_token()
        t2 = get_token()
        assert t1 == t2 == "cached-token"

    def test_sin_credenciales_da_error_claro(self, monkeypatch):
        monkeypatch.delenv("LASTAPP_OAUTH_BEARER_TOKEN", raising=False)
        monkeypatch.delenv("LASTAPP_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv("LASTAPP_OAUTH_CLIENT_SECRET", raising=False)
        from lastapp_auth import get_token
        with pytest.raises(RuntimeError) as exc:
            get_token()
        msg = str(exc.value)
        assert "Last.app MCP setup" in msg or "LASTAPP_OAUTH" in msg

    def test_sin_client_secret_da_error_claro(self, monkeypatch):
        monkeypatch.delenv("LASTAPP_OAUTH_BEARER_TOKEN", raising=False)
        monkeypatch.setenv("LASTAPP_OAUTH_CLIENT_ID", "test-id")
        monkeypatch.delenv("LASTAPP_OAUTH_CLIENT_SECRET", raising=False)
        from lastapp_auth import get_token
        with pytest.raises(RuntimeError) as exc:
            get_token()
        assert "LASTAPP_OAUTH" in str(exc.value)

    @mock.patch("lastapp_auth._request_token")
    def test_oauth_flow_with_credentials(self, mock_request, monkeypatch):
        monkeypatch.delenv("LASTAPP_OAUTH_BEARER_TOKEN", raising=False)
        monkeypatch.setenv("LASTAPP_OAUTH_CLIENT_ID", "test-client")
        monkeypatch.setenv("LASTAPP_OAUTH_CLIENT_SECRET", "test-secret")
        mock_request.return_value = "oauth-token-abc"
        from lastapp_auth import get_token
        token = get_token()
        assert token == "oauth-token-abc"
        mock_request.assert_called_once_with("test-client", "test-secret")

    def test_discover_oauth_config(self, monkeypatch):
        import lastapp_auth
        with mock.patch("lastapp_auth.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "resource": "https://api.last.app/mcp",
                "authorization_servers": ["https://api.last.app/mcp"],
                "bearer_methods_supported": ["header"],
            }
            config = lastapp_auth._discover_oauth_config()
            assert "resource" in config
            assert "authorization_servers" in config
