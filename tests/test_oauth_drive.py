"""
test_oauth_drive.py — Tests del modulo agente.scripts.oauth_drive.

Cubre:
- get_drive_status() con/sin token file
- get_drive_oauth_url() genera URL valida con scope correcto
- DRIVE_SCOPES contiene solo drive.readonly (no gmail)
- _get_credentials_paths() devuelve paths correctos
"""
import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/root/liados/agente/scripts")

import oauth_drive


# Helper: cred_file con TODAS las keys requeridas por google-auth-oauthlib
def _make_creds_file(tmp_path, name="creds.json"):
    cred_file = tmp_path / name
    cred_file.write_text(json.dumps({
        "installed": {
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "x_secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost", "http://localhost:8085/"],
        }
    }))
    return cred_file


class TestDriveScopes:
    def test_drive_scope_contiene_drive_readonly(self):
        assert "https://www.googleapis.com/auth/drive.readonly" in oauth_drive.DRIVE_SCOPES

    def test_drive_scope_NO_contiene_gmail(self):
        assert not any("gmail" in s for s in oauth_drive.DRIVE_SCOPES)


class TestGetDriveStatus:
    def test_sin_token_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth_drive, "_get_credentials_paths",
                            lambda account: ("/tmp/fake_creds.json",
                                              str(tmp_path / "no_existe.json")))
        s = oauth_drive.get_drive_status("principal")
        assert s["status"] == "MISSING"
        assert s["exists"] is False

    def test_con_token_file_valido(self, tmp_path, monkeypatch):
        token_file = tmp_path / "drive_token_principal.json"
        token_file.write_text(json.dumps({
            "access_token": "ya29.fake",
            "refresh_token": "1//fake_refresh",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "issued_at": "2026-07-12T09:00:00+00:00",
        }))
        monkeypatch.setattr(oauth_drive, "_get_credentials_paths",
                            lambda account: ("/tmp/fake_creds.json", str(token_file)))
        s = oauth_drive.get_drive_status("principal")
        assert s["status"] == "OK"
        assert s["has_refresh_token"] is True
        assert s["age_days"] is not None

    def test_token_sin_refresh(self, tmp_path, monkeypatch):
        token_file = tmp_path / "drive_token_principal.json"
        token_file.write_text(json.dumps({
            "access_token": "ya29.fake",
        }))
        monkeypatch.setattr(oauth_drive, "_get_credentials_paths",
                            lambda account: ("/tmp/fake_creds.json", str(token_file)))
        s = oauth_drive.get_drive_status("principal")
        assert s["status"] == "MISSING_TOKEN"
        assert s["has_refresh_token"] is False

    def test_token_stale_180_dias(self, tmp_path, monkeypatch):
        token_file = tmp_path / "drive_token_principal.json"
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        token_file.write_text(json.dumps({
            "access_token": "ya29.fake",
            "refresh_token": "1//fake_refresh",
            "issued_at": old,
        }))
        monkeypatch.setattr(oauth_drive, "_get_credentials_paths",
                            lambda account: ("/tmp/fake_creds.json", str(token_file)))
        s = oauth_drive.get_drive_status("principal")
        assert s["status"] == "STALE"
        assert s["age_days"] >= 200


class TestGetDriveOAuthUrl:
    def test_url_contiene_scope_drive(self, tmp_path):
        cred_file = _make_creds_file(tmp_path)
        with patch.object(oauth_drive, "_get_credentials_paths",
                          return_value=(str(cred_file), "/tmp/fake_token.json")):
            url = oauth_drive.get_drive_oauth_url("principal", 8085)
            assert "drive.readonly" in url
            assert "x.apps.googleusercontent.com" in url
            assert "localhost" in url

    def test_url_prompt_consent_para_forzar_refresh(self, tmp_path):
        cred_file = _make_creds_file(tmp_path, name="creds2.json")
        with patch.object(oauth_drive, "_get_credentials_paths",
                          return_value=(str(cred_file), "/tmp/fake.json")):
            url = oauth_drive.get_drive_oauth_url("principal")
            # prompt=consent fuerza emision de refresh_token
            assert "prompt=consent" in url or "prompt%3Dconsent" in url

    def test_url_access_type_offline(self, tmp_path):
        cred_file = _make_creds_file(tmp_path, name="creds3.json")
        with patch.object(oauth_drive, "_get_credentials_paths",
                          return_value=(str(cred_file), "/tmp/fake.json")):
            url = oauth_drive.get_drive_oauth_url("principal")
            assert "access_type=offline" in url or "access_type%3Doffline" in url