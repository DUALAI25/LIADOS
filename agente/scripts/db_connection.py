"""Conexion a la BD. UNICA fuente de verdad para todos los scripts.

Fix C-3 v2 (2026-07-06): psycopg2 2.9+ hace `__exit__` read-only en la
connection, por lo que monkey-patching falla con AttributeError. Solución:
devolver un wrapper `_ConnCtx` con `__enter__/__exit__` que propaga el
context manager y cierra la conexión siempre. Mantiene la API exacta
(los callers usan `with conn:` sin notar el wrapper).
"""
import os
import psycopg2


def get_conn():
    """Conexion a la BD. Falla rapido si falta cualquier variable de entorno.

    Variables requeridas (sin defaults para evitar secretos en el codigo):
        DB_HOST, DB_NAME, DB_USER, DB_PASSWORD
    Opcionales:
        DB_PORT (default 5432, estandar)
    """
    required = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT', '5432'),
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno para la BD: "
            + ', '.join('DB_' + k.upper() for k in missing)
            + ". Configuralas en .env (ver .env.example)."
        )
    raw_conn = psycopg2.connect(
        host=required['host'],
        port=int(required['port']),
        dbname=required['dbname'],
        user=required['user'],
        password=required['password'],
    )

    # C-3 fix: close connection on context manager exit.
    # psycopg2 2.9+ hace `__exit__` read-only en el connection, así que
    # monkey-patching falla. Solución: wrapper de context manager que
    # propaga transaccionalmente y cierra siempre.
    class _ConnCtx:
        def __init__(self, c):
            self._c = c
        def __enter__(self):
            return self._c
        def __exit__(self, exc_type, exc, tb):
            try:
                self._c.__exit__(exc_type, exc, tb)
            finally:
                self._c.close()
        def __getattr__(self, name):
            return getattr(self._c, name)

    return _ConnCtx(raw_conn)
