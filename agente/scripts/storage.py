"""
storage.py — Manejo de persistencia de archivos
Guarda PDFs localmente y los sube a MinIO
"""
import os
import hashlib
from pathlib import Path
from datetime import datetime
from minio import Minio
from minio.error import S3Error
import logging

logger = logging.getLogger(__name__)

# Configuración de rutas
DATA_DIR = Path(os.getenv('DATA_DIR', '/home/node/.openclaw/workspace-desliado/data'))
RAW_DIR = DATA_DIR / 'invoices' / 'raw'
PROCESSED_DIR = DATA_DIR / 'invoices' / 'processed'
TEMP_DIR = DATA_DIR / 'invoices' / 'temp'

# Crear directorios si no existen
for d in [RAW_DIR, PROCESSED_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Cliente MinIO
minio_client = Minio(
    os.getenv('MINIO_ENDPOINT', 'localhost:9000'),
    access_key=os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
    secret_key=os.getenv('MINIO_SECRET_KEY', 'minio_pass_2026'),
    secure=False
)

BUCKET_NAME = os.getenv('MINIO_BUCKET', 'invoices')


def save_raw_file(content: bytes, filename: str, invoice_id: str = None) -> dict:
    """
    Guarda un archivo raw localmente y lo sube a MinIO

    Si invoice_id se proporciona, se usa en la ruta de MinIO.
    
    Returns:
        dict con local_path, minio_url, content_hash
    """
    content_hash = hashlib.md5(content).hexdigest()
    
    # Crear subdirectorio por fecha
    date_dir = datetime.now().strftime('%Y/%m')
    local_dir = RAW_DIR / date_dir
    local_dir.mkdir(parents=True, exist_ok=True)
    
    # Nombre único con hash para evitar colisiones
    safe_filename = f"{content_hash}_{filename}"
    local_path = local_dir / safe_filename
    
    # Guardar localmente
    with open(local_path, 'wb') as f:
        f.write(content)
    
    logger.info(f"Archivo guardado localmente: {local_path}")
    
    # Subir a MinIO
    minio_url = None
    try:
        if not minio_client.bucket_exists(BUCKET_NAME):
            minio_client.make_bucket(BUCKET_NAME)
        
        # Ruta en MinIO: invoices/2026/05/[invoice_id/]hash_filename.pdf
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
        
        minio_url = f"http://{os.getenv('MINIO_ENDPOINT', 'localhost:9000')}/{BUCKET_NAME}/{minio_path}"
        logger.info(f"Archivo subido a MinIO: {minio_url}")
        
    except S3Error as e:
        logger.error(f"Error subiendo a MinIO: {e}")
    
    return {
        'local_path': str(local_path),
        'minio_url': minio_url,
        'content_hash': content_hash
    }


def get_local_file(content_hash: str) -> Path | None:
    """
    Busca un archivo local por su hash
    """
    # Buscar en todas las carpetas de fecha
    for date_dir in RAW_DIR.glob('*/*'):
        for file in date_dir.glob(f'{content_hash}_*'):
            return file
    return None


def move_to_processed(local_path: Path) -> Path:
    """
    Mueve un archivo de raw a processed
    """
    if not local_path.exists():
        return None
    
    # Mantener estructura de fecha
    relative = local_path.relative_to(RAW_DIR)
    processed_path = PROCESSED_DIR / relative
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    
    local_path.rename(processed_path)
    logger.info(f"Archivo movido a processed: {processed_path}")
    
    return processed_path


def cleanup_temp_files(max_age_hours: int = 24):
    """
    Limpia archivos temporales antiguos
    """
    import time
    
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    
    for file in TEMP_DIR.rglob('*'):
        if file.is_file():
            age = now - file.stat().st_mtime
            if age > max_age_seconds:
                file.unlink()
                logger.info(f"Archivo temporal eliminado: {file}")


def get_storage_stats() -> dict:
    """
    Retorna estadísticas de almacenamiento
    """
    stats = {
        'raw_files': 0,
        'raw_size_mb': 0,
        'processed_files': 0,
        'processed_size_mb': 0,
        'temp_files': 0,
        'temp_size_mb': 0
    }
    
    for dir_path, key_prefix in [(RAW_DIR, 'raw'), (PROCESSED_DIR, 'processed'), (TEMP_DIR, 'temp')]:
        files = list(dir_path.rglob('*'))
        files = [f for f in files if f.is_file()]
        
        stats[f'{key_prefix}_files'] = len(files)
        stats[f'{key_prefix}_size_mb'] = sum(f.stat().st_size for f in files) / (1024 * 1024)
    
    return stats
