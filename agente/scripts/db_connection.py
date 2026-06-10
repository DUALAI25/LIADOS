"""Conexion a la BD. UNICA fuente de verdad para todos los scripts."""
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
    return psycopg2.connect(
        host=required['host'],
        port=int(required['port']),
        dbname=required['dbname'],
        user=required['user'],
        password=required['password'],
    )
