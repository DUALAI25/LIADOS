"""
Tests de las credenciales de BD en db_writer.py.

Verifica que NO haya defaults inseguros y que los errores sean claros.
"""
import os
import sys
import types
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Mock psycopg2 antes de importar db_writer
psycopg2_mock = types.ModuleType('psycopg2')
psycopg2_mock.connect = None  # NO llamado
extras_mock = types.ModuleType('psycopg2.extras')
extras_mock.RealDictCursor = object
psycopg2_mock.extras = extras_mock
sys.modules['psycopg2'] = psycopg2_mock
sys.modules['psycopg2.extras'] = extras_mock


def test_no_hardcoded_password_in_get_conn():
    """db_writer.get_conn NO debe tener password hardcodeado como default."""
    import db_writer
    import inspect
    source = inspect.getsource(db_writer.get_conn)
    assert "desliado_pass_2026" not in source, "PASS HARDCODEADA ENCONTRADA"
    assert "desliado_pass" not in source, "PASS por defecto encontrada"


def test_get_conn_fails_without_db_password(monkeypatch):
    """Sin DB_PASSWORD en env, get_conn debe fallar con RuntimeError claro."""
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.delenv("DB_PORT", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    import db_writer
    with pytest.raises(RuntimeError) as exc_info:
        db_writer.get_conn()
    msg = str(exc_info.value)
    assert "DB_PASSWORD" in msg, f"Mensaje no menciona DB_PASSWORD: {msg}"


def test_get_conn_fails_without_db_host(monkeypatch):
    """Sin DB_HOST en env, get_conn debe fallar."""
    monkeypatch.setenv("DB_HOST", "")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "test")
    monkeypatch.setenv("DB_USER", "test")
    monkeypatch.setenv("DB_PASSWORD", "test")

    import db_writer
    with pytest.raises(RuntimeError) as exc_info:
        db_writer.get_conn()
    assert "DB_HOST" in str(exc_info.value)
