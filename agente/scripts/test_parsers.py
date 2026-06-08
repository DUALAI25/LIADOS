"""
test_parsers.py — Tests para lógica pura (sin DB ni red)

Cubre:
- invoice_parser: normalización de datos
- invoice_parser: mapeo de categorías
- storage: filesystem save/get

Ejecutar:
    cd /home/openclaw/liados
    python3 -m pytest agente/scripts/test_parsers.py -v

    O sin pytest:
    python3 agente/scripts/test_parsers.py
"""
import os
import sys
import tempfile
import shutil
from pathlib import Path

# Hacer los scripts importables
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))


def test_normalize_category():
    """Verifica el mapeo de categorías"""
    from invoice_parser import _normalize_category

    # Categorías válidas
    assert _normalize_category('marketing') == 'marketing'
    assert _normalize_category('Marketing') == 'marketing'
    assert _normalize_category('MARKETING') == 'marketing'
    assert _normalize_category('  viajes  ') == 'viajes'

    # Sinónimos
    assert _normalize_category('Restaurante') == 'hosteleria'
    assert _normalize_category('comida') == 'hosteleria'
    assert _normalize_category('taxi') == 'viajes'
    assert _normalize_category('gasolina') == 'viajes'
    assert _normalize_category('publicidad') == 'marketing'
    assert _normalize_category('luz') == 'suministros'
    assert _normalize_category('internet') == 'teleco'
    assert _normalize_category('banco') == 'bancario'

    # Desconocidas → 'otros'
    assert _normalize_category('xyz inventado') == 'otros'
    assert _normalize_category(None) == 'otros'
    assert _normalize_category('') == 'otros'

    print('  ✅ test_normalize_category')


def test_coerce_number():
    """Verifica la coerción segura de números"""
    from invoice_parser import _coerce_number

    assert _coerce_number('100.50') == 100.50
    assert _coerce_number(100) == 100.0
    assert _coerce_number('0') == 0.0
    assert _coerce_number(None) is None
    assert _coerce_number('') is None
    assert _coerce_number('abc') is None
    assert _coerce_number('100,50') is None  # No soporta coma decimal
    assert _coerce_number('-50.25') == -50.25

    print('  ✅ test_coerce_number')


def test_coerce_date():
    """Verifica la validación de fechas"""
    from invoice_parser import _coerce_date

    assert _coerce_date('2026-05-15') == '2026-05-15'
    assert _coerce_date('  2026-05-15  ') == '2026-05-15'
    assert _coerce_date('15/05/2026') is None  # Formato incorrecto
    assert _coerce_date('2026-13-01') is None  # Mes inválido (regex pasa pero semánticamente mal)
    assert _coerce_date(None) is None
    assert _coerce_date('') is None
    assert _coerce_date(12345) is None

    print('  ✅ test_coerce_date')


def test_normalize_parsed_data():
    """Verifica la limpieza completa del JSON parseado"""
    from invoice_parser import _normalize_parsed_data

    raw = {
        'invoice_number': 'F-2026/001',
        'invoice_date': '2026-05-15',
        'vendor_name': '  Distribuidora ABC  ',
        'vendor_tax_id': 'B12345678',
        'description': 'Productos',
        'base_amount': '100.50',
        'tax_amount': '21.10',
        'total_amount': '121.60',
        'currency': 'eur',
        'category': 'Restaurante',
        'confidence': '0.95'
    }
    result = _normalize_parsed_data(raw)

    assert result['invoice_number'] == 'F-2026/001'
    assert result['vendor_name'] == 'Distribuidora ABC'  # trim
    assert result['currency'] == 'EUR'  # uppercase
    assert result['category'] == 'hosteleria'  # sinónimo
    assert result['base_amount'] == 100.5  # float
    assert result['confidence_score'] == 0.95
    assert result['due_date'] is None  # opcional, no en input

    # Datos vacíos → None para campos opcionales
    empty = _normalize_parsed_data({})
    assert empty is not None
    assert empty['invoice_number'] is None
    assert empty['vendor_name'] is None
    assert empty['total_amount'] is None
    assert empty['currency'] == 'EUR'  # default
    assert empty['category'] == 'otros'  # default
    assert empty['confidence_score'] == 0.5  # default

    # Input inválido también devuelve defaults
    invalid_result = _normalize_parsed_data(None)
    assert invalid_result is not None
    assert invalid_result['currency'] == 'EUR'

    invalid_result2 = _normalize_parsed_data('string')
    assert invalid_result2 is not None
    assert invalid_result2['category'] == 'otros'

    print('  ✅ test_normalize_parsed_data')


def test_storage_filesystem():
    """Verifica save/get en filesystem local (sin MinIO)"""
    # Usar directorio temporal
    tmp_dir = tempfile.mkdtemp(prefix='liados-test-')
    os.environ['DATA_DIR'] = tmp_dir
    os.environ.pop('MINIO_ENDPOINT', None)  # Forzar fallback a filesystem

    # Reimportar para que tome los nuevos env vars
    import importlib
    import storage
    importlib.reload(storage)

    # Reset MinIO client
    storage._MINIO_CLIENT = None

    # Guardar archivo
    content = b'PDF fake content for testing'
    result = storage.save_raw_file(content, 'test.pdf', invoice_id='inv-123')

    assert result['local_path']
    assert result['content_hash']
    assert result['minio_url'] is None  # No MinIO
    assert Path(result['local_path']).exists()
    assert Path(result['local_path']).read_bytes() == content

    # Recuperar por hash
    found = storage.get_local_file(result['content_hash'])
    assert found is not None
    assert found == Path(result['local_path'])

    # Hash inexistente
    missing = storage.get_local_file('0' * 32)
    assert missing is None

    # Stats
    stats = storage.get_storage_stats()
    assert stats['raw_files'] == 1
    assert stats['minio_enabled'] is False

    # Limpieza
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print('  ✅ test_storage_filesystem')


def test_gmail_collector_accounts_parsing():
    """Verifica el parseo de GMAIL_ACCOUNTS"""
    # Mock psycopg2 para evitar import error
    import sys
    import types
    if 'psycopg2' not in sys.modules:
        psycopg2_mock = types.ModuleType('psycopg2')
        psycopg2_mock.connect = lambda **kwargs: None
        sys.modules['psycopg2'] = psycopg2_mock
        # Mock también el submódulo extras (usado por weekly_summary)
        extras_mock = types.ModuleType('psycopg2.extras')
        extras_mock.RealDictCursor = object
        sys.modules['psycopg2.extras'] = extras_mock

    import gmail_collector

    # Crear un .env temporal
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix='liados-test-env-')
    env_file = Path(tmp_dir) / '.env'
    env_file.write_text('GMAIL_ACCOUNTS=principal,secundaria,tercera\n')

    # Patch el WORKSPACE del collector
    original_workspace = gmail_collector.WORKSPACE
    original_env_file = gmail_collector.ENV_FILE
    gmail_collector.WORKSPACE = Path(tmp_dir)
    gmail_collector.ENV_FILE = env_file

    try:
        accounts = gmail_collector.get_gmail_accounts()
        assert accounts == ['principal', 'secundaria', 'tercera'], f"Got: {accounts}"
    finally:
        gmail_collector.WORKSPACE = original_workspace
        gmail_collector.ENV_FILE = original_env_file
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Sin GMAIL_ACCOUNTS
    tmp_dir2 = tempfile.mkdtemp(prefix='liados-test-env2-')
    env_file2 = Path(tmp_dir2) / '.env'
    env_file2.write_text('OTRA_COSA=foo\n')
    gmail_collector.WORKSPACE = Path(tmp_dir2)
    gmail_collector.ENV_FILE = env_file2

    try:
        accounts = gmail_collector.get_gmail_accounts()
        assert accounts == [], f"Expected [], got: {accounts}"
    finally:
        gmail_collector.WORKSPACE = original_workspace
        gmail_collector.ENV_FILE = original_env_file
        shutil.rmtree(tmp_dir2, ignore_errors=True)

    print('  ✅ test_gmail_collector_accounts_parsing')


def run_all():
    """Ejecuta todos los tests."""
    print("=" * 60)
    print("🧪 TESTS — Liados (lógica pura, sin DB ni red)")
    print("=" * 60)

    tests = [
        test_normalize_category,
        test_coerce_number,
        test_coerce_date,
        test_normalize_parsed_data,
        test_storage_filesystem,
        test_gmail_collector_accounts_parsing,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__}: {e.__class__.__name__}: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Resultado: {passed}/{len(tests)} tests pasados")
    if failed == 0:
        print("✅ TODOS LOS TESTS OK")
    else:
        print(f"❌ {failed} tests fallaron")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(run_all())
