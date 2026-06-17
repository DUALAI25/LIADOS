"""
storage.py — Manejo de persistencia de archivos de facturas.

Guarda PDFs/imágenes de facturas:
- SIEMPRE en filesystem local (DATA_DIR/invoices/raw/...)
- SI MinIO está disponible y configurado, TAMBIÉN sube copia

Si MinIO falla, el sistema sigue funcionando con filesystem local.
"""
import os
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Configuración de rutas (filesystem SIEMPRE activo)
DATA_DIR = Path(os.getenv('DATA_DIR', '/root/liados/data'))
RAW_DIR = DATA_DIR / 'invoices' / 'raw'
PROCESSED_DIR = DATA_DIR / 'invoices' / 'processed'
TEMP_DIR = DATA_DIR / 'invoices' / 'temp'

# Crear directorios si no existen
for d in [RAW_DIR, PROCESSED_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _get_minio_client():
    """Crea cliente MinIO solo si está configurado y disponible.
    Returns: cliente MinIO o None si no está disponible
    """
    endpoint = os.getenv('MINIO_ENDPOINT')
    if not endpoint:
        return None

    try:
        from minio import Minio
        from minio.error import S3Error

        client = Minio(
            endpoint,
            access_key=os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
            secret_key=os.getenv('MINIO_SECRET_KEY', 'minioadmin'),
            secure=False
        )
        # Test: bucket_exists es la operación más barata
        bucket = os.getenv('MINIO_BUCKET', 'invoices')
        if not client.bucket_exists(bucket):
            try:
                client.make_bucket(bucket)
            except S3Error:
                return None
        return client
    except ImportError:
        logger.debug("Librería minio no instalada — solo filesystem local")
        return None
    except Exception as e:
        logger.debug(f"MinIO no disponible ({e.__class__.__name__}) — solo filesystem local")
        return None


# Cliente MinIO lazy: se inicializa al primer uso
_MINIO_CLIENT = None


def _ensure_minio():
    """Inicializa MinIO la primera vez, o devuelve None si no está"""
    global _MINIO_CLIENT
    if _MINIO_CLIENT is None:
        _MINIO_CLIENT = _get_minio_client()
    return _MINIO_CLIENT


BUCKET_NAME = os.getenv('MINIO_BUCKET', 'invoices')


def save_raw_file(content: bytes, filename: str, invoice_id: str = None) -> dict:
    """
    Guarda un archivo raw localmente y (si MinIO está disponible) en MinIO.

    Args:
        content: bytes del archivo
        filename: nombre original del adjunto
        invoice_id: ID de factura (opcional, se usa en ruta MinIO)

    Returns:
        dict con:
          - local_path: ruta local (SIEMPRE presente)
          - minio_url: URL en MinIO (None si MinIO no disponible)
          - content_hash: MD5 del contenido
    """
    content_hash = hashlib.md5(content).hexdigest()

    # Estructura: data/invoices/raw/YYYY/MM/hash_filename
    date_dir = datetime.now().strftime('%Y/%m')
    local_dir = RAW_DIR / date_dir
    local_dir.mkdir(parents=True, exist_ok=True)

    # Nombre único con hash para evitar colisiones
    safe_filename = f"{content_hash}_{filename}"
    local_path = local_dir / safe_filename

    # Guardar localmente (SIEMPRE)
    with open(local_path, 'wb') as f:
        f.write(content)

    logger.info(f"📁 Archivo guardado: {local_path}")

    # Intentar subir a MinIO (OPCIONAL)
    minio_url = None
    minio_client = _ensure_minio()
    if minio_client is not None:
        try:
            if invoice_id:
                minio_path = f"{date_dir}/{invoice_id}/{safe_filename}"
            else:
                minio_path = f"{date_dir}/{safe_filename}"

            minio_client.put_object(
                BUCKET_NAME,
                minio_path,
                data=content,
                length=len(content),
                content_type='application/pdf'
            )

            endpoint = os.getenv('MINIO_ENDPOINT', 'localhost:9000')
            minio_url = f"http://{endpoint}/{BUCKET_NAME}/{minio_path}"
            logger.info(f"☁️  Subido a MinIO: {minio_url}")

        except Exception as e:
            logger.warning(f"⚠️  MinIO falló ({e.__class__.__name__}: {e}) — usando solo filesystem local")
            minio_url = None
    else:
        logger.debug("MinIO no configurado — solo filesystem local")

    return {
        'local_path': str(local_path),
        'minio_url': minio_url,
        'content_hash': content_hash
    }


def get_local_file(content_hash: str) -> Optional[Path]:
    """
    Busca un archivo local por su hash en cualquier subcarpeta de fecha.

    Returns:
        Path al archivo, o None si no existe
    """
    if not RAW_DIR.exists():
        return None

    # Buscar recursivamente en RAW_DIR
    for file in RAW_DIR.rglob(f'{content_hash}_*'):
        if file.is_file():
            return file
    return None


def move_to_processed(local_path: Path) -> Optional[Path]:
    """
    Mueve un archivo de raw a processed manteniendo estructura de fecha.

    Returns:
        Path en processed, o None si el origen no existe
    """
    if not local_path or not local_path.exists():
        return None

    try:
        relative = local_path.relative_to(RAW_DIR)
    except ValueError:
        # El archivo no está en RAW_DIR, no lo movemos
        logger.warning(f"Archivo fuera de RAW_DIR, no se mueve: {local_path}")
        return local_path

    processed_path = PROCESSED_DIR / relative
    processed_path.parent.mkdir(parents=True, exist_ok=True)

    local_path.rename(processed_path)
    logger.info(f"📦 Movido a processed: {processed_path}")
    return processed_path


def cleanup_temp_files(max_age_hours: int = 24) -> int:
    """
    Limpia archivos temporales antiguos.

    Returns:
        Número de archivos eliminados
    """
    import time

    if not TEMP_DIR.exists():
        return 0

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    deleted = 0

    for file in TEMP_DIR.rglob('*'):
        if file.is_file():
            age = now - file.stat().st_mtime
            if age > max_age_seconds:
                try:
                    file.unlink()
                    deleted += 1
                    logger.info(f"🗑️  Temp eliminado: {file}")
                except OSError as e:
                    logger.warning(f"No se pudo eliminar {file}: {e}")

    return deleted


def get_storage_stats() -> dict:
    """
    Retorna estadísticas de almacenamiento.

    Returns:
        dict con raw/processed/temp files y size en MB
    """
    stats = {
        'raw_files': 0,
        'raw_size_mb': 0.0,
        'processed_files': 0,
        'processed_size_mb': 0.0,
        'temp_files': 0,
        'temp_size_mb': 0.0,
        'minio_enabled': _ensure_minio() is not None,
    }

    for dir_path, key_prefix in [(RAW_DIR, 'raw'), (PROCESSED_DIR, 'processed'), (TEMP_DIR, 'temp')]:
        if not dir_path.exists():
            continue
        files = [f for f in dir_path.rglob('*') if f.is_file()]
        stats[f'{key_prefix}_files'] = len(files)
        stats[f'{key_prefix}_size_mb'] = round(
            sum(f.stat().st_size for f in files) / (1024 * 1024), 2
        )

    return stats


def get_file_url(file_info: dict) -> str:
    """
    Devuelve la mejor URL disponible para un archivo:
    - MinIO URL si está disponible
    - ruta local si no

    Args:
        file_info: dict devuelto por save_raw_file

    Returns:
        URL (http://... o /path/to/file)
    """
    if file_info.get('minio_url'):
        return file_info['minio_url']
    return file_info.get('local_path', '')
