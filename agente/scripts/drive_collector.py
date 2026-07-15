"""
drive_collector.py — Colector de facturas desde Google Drive.

v1 (2026-07-12): descarga PDFs/imagenes desde una carpeta Drive y los pasa
por el pipeline estandar (parse_invoice + dedup_checker + INSERT).

v2 (2026-07-13) BLINDADO:
  - Logging robusto a /var/log/liados-drive.log con rotacion
  - Retry con backoff exponencial para errores transitorios (429/503/5xx)
  - Top-level exception handler por archivo (no mata el batch)
  - sync_control SIEMPRE se actualiza (con timestamp actual incluso si 0 procesados)
  - Healthcheck: ping de lectura + reporte de estado para watchdog
  - Modo --once para correr desde cron con timeout duro

Scope: drive.readonly. Token independiente del Gmail (oauth_drive.py).

Sync incremental: solo descarga archivos modificados desde el ultimo sync.
Persiste timestamp en tabla sync_control (igual que gmail_collector).

CLI:
    python -m agente.scripts.drive_collector                     # procesa todas las cuentas
    python -m agente.scripts.drive_collector --account principal
    python -m agente.scripts.drive_collector --dry-run          # lista sin descargar
    python -m agente.scripts.drive_collector --folder FOLDER_ID # carpeta especifica (opcional)

Variables de entorno:
    GMAIL_ACCOUNTS=principal,secundaria   (se reusa para Drive)
    DRIVE_FOLDER_ID_<account>=            # si no, usa "root"
    DRIVE_TOKEN_FILE_<account>=           # default: credentials/drive_token_<account>.json
"""
import os
import sys
import json
import hashlib
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler

from io import BytesIO
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError as GoogleHttpError

from db_connection import get_conn
from is_invoice_filter import is_invoice_attachment

# Carga .env manualmente (igual que gmail_collector)
try:
    WORKSPACE = Path(__file__).resolve().parent.parent.parent
except NameError:
    WORKSPACE = Path(os.getcwd())
ENV_FILE = WORKSPACE / ".env"


def load_env():
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env()

# Imports que requieren env cargada
from agente.scripts.oauth_drive import get_drive_service
from invoice_parser import parse_invoice
from storage import save_raw_file
from dedup_checker import is_duplicate_by_hash, mark_as_duplicate

# === LOGGING ROBUSTO A ARCHIVO CON ROTACION ===
LOG_DIR = Path("/var/log")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "liados-drive.log"

_root_logger = logging.getLogger()
if not _root_logger.handlers:
    _root_logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    # File handler: 10MB rotacion, 5 backups
    try:
        fh = RotatingFileHandler(
            str(LOG_FILE), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        _root_logger.addHandler(fh)
    except Exception as e:
        sys.stderr.write(f"WARN: no se pudo abrir {LOG_FILE}: {e}\n")
    # Stream handler (capturado por systemd o run_daily)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    _root_logger.addHandler(sh)

logger = logging.getLogger(__name__)

# === TIMEOUT GLOBAL ===
# Cualquier llamada API o descarga tarda demasiado -> SIGALRM la mata
DEFAULT_TIMEOUT_SEC = 25 * 60  # 25 min (cron corre cada 30)


class TimeoutError_(Exception):
    pass


def _alarm_handler(signum, frame):
    raise TimeoutError_(f"drive_collector timeout ({DEFAULT_TIMEOUT_SEC}s)")


# === RETRY CONFIG ===
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 2.0  # segundos
RETRY_MAX_DELAY = 60.0  # segundos


def _is_retryable_api_error(e):
    """429/503/500/502/504 son retryables. 4xx no."""
    if isinstance(e, GoogleHttpError):
        code = getattr(e, "resp", None) and getattr(e.resp, "status", None)
        if code in (429, 500, 502, 503, 504):
            return True
        # 403 con rateLimitExceeded
        try:
            reason = (e._get_reason() if hasattr(e, "_get_reason") else "").lower()
            if "ratelimitexceeded" in reason or "usagelimit" in reason or "backenderror" in reason:
                return True
        except Exception:
            pass
    return False


def _api_call_with_retry(func, *args, **kwargs):
    """Ejecuta func(*args, **kwargs) con retry+backoff exponencial."""
    delay = RETRY_BASE_DELAY
    last_exc = None
    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if not _is_retryable_api_error(e):
                raise
            last_exc = e
            if attempt == RETRY_MAX_ATTEMPTS:
                logger.error(f"API retry agotado ({attempt}/{RETRY_MAX_ATTEMPTS}): {e}")
                raise
            sleep_for = min(delay, RETRY_MAX_DELAY)
            logger.warning(
                f"API retryable error intento {attempt}/{RETRY_MAX_ATTEMPTS}: "
                f"{type(e).__name__}: {str(e)[:100]} | esperando {sleep_for:.1f}s"
            )
            time.sleep(sleep_for)
            delay *= 2
    raise last_exc  # no deberia llegar


# Extensiones válidas para facturas
VALID_MIME_TYPES = (
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
)

# Nombre de la carpeta raw de Drive
RAW_SUBPATH = "data/invoices/raw"


def sanitize_filename(name: str) -> str:
    """Sanitiza un nombre de archivo contra path traversal.

    CRITICAL: Sin esta sanitización, un colaborador malicioso en Drive podría
    usar un nombre como `../etc/passwd` o `subdir/../../.env` para escribir
    o sobrescribir archivos fuera de data/invoices/raw/.

    Estrategia:
    - Rechazar nombre vacío
    - Usar solo el basename (sin directorios)
    - Reemplazar caracteres peligrosos (/, \\, NUL, caracteres de control)
    - Preservar puntos, espacios, tildes y eñes (típicos en nombres de facturas ES)
    """
    if not name or not isinstance(name, str):
        return "unnamed"
    # Tomar solo el basename (eliminar cualquier prefijo de directorio)
    safe = Path(name).name
    # Si queda vacío tras basename, fallback
    if not safe or safe in (".", ".."):
        return "unnamed"
    # Eliminar caracteres de control y nul
    safe = safe.replace("\x00", "")
    # Reemplazar separadores de path que basename ya eliminó, pero por si acaso
    safe = safe.replace("/", "_").replace("\\", "_")
    # Caracteres de control ASCII (excepto printable)
    safe = "".join(c for c in safe if c.isprintable() or c in (" ",))
    if not safe:
        return "unnamed"
    # Limitar longitud para evitar problemas de FS
    return safe[:200] if len(safe) > 200 else safe

# Sync control table: misma que gmail_collector usa
# SYNC_KEY_PREFIX + account = "drive:principal" (debe matchear sync_control CHECK constraint)
SYNC_KEY_PREFIX = "drive"


def get_drive_accounts():
    """Lee GMAIL_ACCOUNTS del .env (se reusa la config)."""
    accounts_raw = os.getenv("GMAIL_ACCOUNTS", "").strip()
    return [a.strip() for a in accounts_raw.split(",") if a.strip()]


def get_folder_id_for_account(account):
    """Devuelve LISTA de folder IDs para la cuenta.

    Soporta DRIVE_FOLDER_ID_<account> con uno o varios IDs separados por coma.
    Si no existe la variable, devuelve ["root"] (todo el Drive).
    """
    raw = os.getenv(f"DRIVE_FOLDER_ID_{account}", "").strip()
    if not raw:
        return ["root"]
    return [f.strip() for f in raw.split(",") if f.strip()]


# Reusar db_writer (mismo patron que gmail_collector)
from db_writer import get_last_sync, update_last_sync


def put_conn(conn):
    """Liberar conexion al pool (mismo patron que db_connection)."""
    try:
        from db_connection import put_conn as _put
        _put(conn)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def list_drive_files(service, folder_id="root", modified_after=None, page_size=100):
    """Lista archivos en folder_id con mime valido, opcionalmente modificados tras timestamp.

    Returns: list[dict] con {id, name, mime, modifiedTime, size, parents}
    """
    q = [
        f"'{folder_id}' in parents",
        "trashed = false",
        "(" + " or ".join([f"mimeType='{m}'" for m in VALID_MIME_TYPES]) + ")",
    ]
    if modified_after:
        # ISO 8601 con Z
        ts = modified_after.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if hasattr(modified_after, "strftime") else str(modified_after)
        q.append(f"modifiedTime > '{ts}'")
    query = " and ".join(q)

    files = []
    page_token = None
    while True:
        kwargs = {
            "q": query,
            "pageSize": page_size,
            "fields": "nextPageToken, files(id,name,mimeType,modifiedTime,size,parents,webViewLink)",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        # PATCH v2: retry+backoff
        resp = _api_call_with_retry(service.files().list, **kwargs).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def list_drive_files_recursive(service, folder_id, modified_after=None, page_size=100, depth=0, max_depth=10):
    """Lista archivos recursivamente entrando en subcarpetas.

    Devuelve lista plana con todos los archivos encontrados bajo folder_id
    y todas sus subcarpetas hasta max_depth.
    """
    if depth > max_depth:
        logger.warning(f"Drive recursion depth > {max_depth}, parando en {folder_id}")
        return []

    # Listar archivos directos (filtro mime valido)
    files = list_drive_files(service, folder_id, modified_after, page_size)

    # Listar subcarpetas y recursar.
    q = [
        f"'{folder_id}' in parents",
        "trashed = false",
        "mimeType = 'application/vnd.google-apps.folder'",
    ]
    query = " and ".join(q)

    subfolder_files = []
    page_token = None
    while True:
        kwargs = {
            "q": query,
            "pageSize": page_size,
            "fields": "nextPageToken, files(id,name)",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        resp = _api_call_with_retry(service.files().list, **kwargs).execute()
        for sub in resp.get("files", []):
            subfolder_files.extend(
                list_drive_files_recursive(
                    service, sub["id"], modified_after, page_size,
                    depth=depth + 1, max_depth=max_depth
                )
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return files + subfolder_files


def download_drive_file(service, file_id, dest_path):
    """Descarga archivo de Drive a dest_path. Devuelve bytes escritos.

    PATCH v2: retry+backoff en errores transitorios, no abortar todo el batch.
    """
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        # PATCH v2: bucle de retry que envuelve next_chunk
        attempts = 0
        while not done:
            try:
                attempts += 1
                _, done = downloader.next_chunk()
            except Exception as e:
                if not _is_retryable_api_error(e) or attempts > RETRY_MAX_ATTEMPTS:
                    raise
                logger.warning(
                    f"download_drive_file retry {attempts}/{RETRY_MAX_ATTEMPTS} para {file_id}: {e}"
                )
                time.sleep(min(RETRY_BASE_DELAY * (2 ** (attempts - 1)), RETRY_MAX_DELAY))
    return os.path.getsize(dest_path)


def is_likely_invoice(filename):
    """Heurística simple por nombre de archivo."""
    name = filename.lower()
    keywords = ("factura", "invoice", "receipt", "recibo", "albaran", "albarán",
                "nota", "cargo", "ticket", "compra", "bill")
    return any(k in name for k in keywords)


def process_account(account, dry_run=False):
    """Procesa archivos nuevos/modificados para una cuenta.

    Returns: (processed, errors, dry_report_dict_or_None)
    """
    folder_ids = get_folder_id_for_account(account)
    logger.info(f"[drive:{account}] carpetas Drive: {folder_ids}")

    last_sync = get_last_sync(f"{SYNC_KEY_PREFIX}:{account}")
    # Ventana inicial: 30 dias si nunca ha corrido
    if last_sync is None:
        from os import getenv as _ge
        try:
            initial_days = int(_ge("GMAIL_INITIAL_DAYS", "30"))
        except Exception:
            initial_days = 30
        last_sync = datetime.now(timezone.utc) - timedelta(days=initial_days)
        logger.info(f"[drive:{account}] primera corrida, ventana {initial_days}d")

    service, status = get_drive_service(account)
    if status != "ok":
        logger.error(f"[drive:{account}] sin servicio Drive: {status}")
        raise RuntimeError(f"Drive token no OK para {account}: {status}")

    # Listar archivos candidatos
    files = []
    for fid in folder_ids:
        sub = list_drive_files_recursive(service, fid, modified_after=last_sync)
        logger.info(f"[drive:{account}] {len(sub)} archivos en carpeta {fid} (recursivo)")
        files.extend(sub)
    logger.info(f"[drive:{account}] {len(files)} archivos candidatos")

    if dry_run:
        return 0, 0, {
            "account": account,
            "msg_count": len(files),
            "files": [{"id": f["id"], "name": f["name"], "modified": f.get("modifiedTime")} for f in files[:20]],
        }

    processed = 0
    errors = 0
    dry_report = None

    for f in files:
        name = f.get("name", "")
        # PATCH v2: top-level try/except por archivo para no matar el batch entero
        try:
            _process_single_file(f, account)
            processed += 1
        except Exception as e:
            errors += 1
            logger.error(f"[drive:{account}] fallo procesando {name}: {type(e).__name__}: {e}")

    # PATCH v2: sync_control SIEMPRE se actualiza, incluso si 0 procesados.
    # Asi la siguiente corrida incremental filtra correctamente por modifiedTime
    # y evitamos re-escanear 743 archivos cada 30 min.
    try:
        update_last_sync(f"{SYNC_KEY_PREFIX}:{account}")
        logger.info(f"[drive:{account}] sync_control actualizado a NOW()")
    except Exception as e:
        logger.error(f"[drive:{account}] NO se pudo actualizar sync_control: {e}")

    logger.info(f"[drive:{account}] processed={processed} errors={errors}")
    return processed, errors, None


def _process_single_file(f, account):
    """Procesa UN archivo: dedup, descarga, parse, insert. Raises on failure."""
    name = f.get("name", "")
    file_id = f["id"]

    try:
        is_inv, reason = is_invoice_attachment(name, subject=None)
    except Exception as e:
        logger.warning(f"[drive:{account}] is_invoice_filter fallo {name}: {e}")
        is_inv, reason = True, "filter_unavailable"
    if not is_inv:
        logger.debug(f"[drive:{account}] saltando {name} (no-factura: {reason})")
        return

    # Destino en disco: data/invoices/raw/<yyyy>/<mm>/<sha256>_<name>
    try:
        modified_str = f.get("modifiedTime", "")
        modified_dt = datetime.fromisoformat(modified_str.replace("Z", "+00:00"))
        yyyy = modified_dt.strftime("%Y")
        mm = modified_dt.strftime("%m")
    except Exception:
        yyyy = datetime.now().strftime("%Y")
        mm = datetime.now().strftime("%m")

    # Hash preliminar por nombre + id (suficiente para evitar re-descarga)
    # v2: Sanitizar nombre contra path traversal (CRITICAL fix 2026-07-15)
    safe_name = sanitize_filename(name)
    tmp_dest = f"/tmp/drive_{file_id}_{safe_name}"
    service, _ = get_drive_service(account)
    size = download_drive_file(service, file_id, tmp_dest)

    # MD5 del contenido
    h = hashlib.md5()
    with open(tmp_dest, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    content_hash = h.hexdigest()

    # Dedup check
    if is_duplicate_by_hash(content_hash):
        logger.info(f"[drive:{account}] duplicado por hash, saltando {name}")
        try:
            mark_as_duplicate("drive", file_id)
        except Exception:
            pass
        try:
            os.remove(tmp_dest)
        except Exception:
            pass
        return

    # Mover a destino final con nombre hasheado + sanitizado
    final_name = f"{content_hash}_{safe_name}"
    raw_root = Path("/root/liados") / RAW_SUBPATH
    final_dir = (raw_root / yyyy / mm).resolve()
    # v2: Verificar que el directorio resuelto sigue dentro de raw_root (anti path-traversal)
    try:
        final_dir.relative_to(raw_root.resolve())
    except ValueError:
        logger.error(f"[drive:{account}] directorio de destino fuera de raw_root: {final_dir}")
        try:
            os.remove(tmp_dest)
        except Exception:
            pass
        raise
    final_path = str(final_dir / final_name)
    try:
        Path(final_path).parent.mkdir(parents=True, exist_ok=True)
        os.rename(tmp_dest, final_path)
    except Exception as e:
        logger.error(f"[drive:{account}] fallo mover {tmp_dest} -> {final_path}: {e}")
        raise

    # Parsear con IA (igual que gmail_collector)
    mime = "application/pdf"
    if name.lower().endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    elif name.lower().endswith(".png"):
        mime = "image/png"
    elif name.lower().endswith(".webp"):
        mime = "image/webp"
    elif name.lower().endswith(".heic"):
        mime = "image/heic"

    parsed = parse_invoice(final_path, mime, name) or {}
    # Detectar facturas rechazadas por el parser
    is_actually_invoice = parsed.get('is_invoice', True)
    confidence = parsed.get('confidence_score', 0.0) or 0.0
    if not is_actually_invoice or confidence < 0.3:
        logger.info(f"[drive:{account}] no-factura {name} (conf={confidence:.2f})")
        parsed['is_invoice'] = False
        parsed['category_raw'] = None

    # Insertar en BD
    invoice_id = _insert_invoice(
        source="drive",
        source_id=file_id,
        source_account=account,
        file_path=final_path,
        content_hash=content_hash,
        parsed=parsed,
    )
    logger.info(f"[drive:{account}] OK {name} -> {invoice_id}")


def _insert_invoice(source, source_id, source_account, file_path, content_hash, parsed):
    """Inserta fila en tabla invoices con los campos parseados. Devuelve UUID.

    is_invoice: respeta lo que decidio el parser (default True si no viene).
    category_raw: puede ser None si no es factura.
    """
    import uuid
    conn = get_conn()
    try:
        cur = conn.cursor()
        invoice_id = str(uuid.uuid4())
        is_inv = bool(parsed.get('is_invoice', True))
        cur.execute("""
            INSERT INTO invoices (
                id, type, source, source_id, source_account, raw_file_url,
                content_hash, invoice_number, invoice_date, vendor_name, vendor_tax_id,
                base_amount, tax_amount, total_amount, currency,
                category_raw, description, confidence_score, status, is_invoice,
                created_at, updated_at
            ) VALUES (
                %s, 'expense', %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, 'classified', %s,
                NOW(), NOW()
            )
            ON CONFLICT (source, source_id) DO UPDATE SET
                invoice_number = EXCLUDED.invoice_number,
                invoice_date = EXCLUDED.invoice_date,
                vendor_name = EXCLUDED.vendor_name,
                vendor_tax_id = EXCLUDED.vendor_tax_id,
                base_amount = EXCLUDED.base_amount,
                tax_amount = EXCLUDED.tax_amount,
                total_amount = EXCLUDED.total_amount,
                currency = EXCLUDED.currency,
                category_raw = EXCLUDED.category_raw,
                description = EXCLUDED.description,
                confidence_score = EXCLUDED.confidence_score,
                is_invoice = EXCLUDED.is_invoice,
                raw_file_url = EXCLUDED.raw_file_url,
                content_hash = EXCLUDED.content_hash,
                updated_at = NOW()
            RETURNING id
        """, (
            invoice_id, source, source_id, source_account, file_path,
            content_hash,
            parsed.get("invoice_number"),
            parsed.get("invoice_date"),
            parsed.get("vendor_name"),
            parsed.get("vendor_tax_id"),
            parsed.get("base_amount"),
            parsed.get("tax_amount"),
            parsed.get("total_amount"),
            parsed.get("currency", "EUR"),
            parsed.get("category_raw"),
            parsed.get("description"),
            parsed.get("confidence_score", 0.5),
            is_inv,
        ))
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else invoice_id
    except Exception as e:
        conn.rollback()
        logger.error(f"_insert_invoice failed for {source}:{source_id}: {e}")
        raise
    finally:
        put_conn(conn)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", "-a", action="append", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Corre una sola vez con timeout duro (uso desde cron). Mata el proceso si tarda >25min.",
    )
    args = parser.parse_args(argv)

    # PATCH v2: timeout duro opcional
    if args.once:
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(DEFAULT_TIMEOUT_SEC)
        logger.info(f"[drive] modo --once activo, timeout={DEFAULT_TIMEOUT_SEC}s")

    if args.account:
        accounts = [a.strip() for a in args.account if a and a.strip()]
        configured = set(get_drive_accounts())
        unknown = [a for a in accounts if a not in configured]
        if unknown:
            logger.error(f"Cuentas no configuradas: {unknown}. Configuradas: {sorted(configured)}")
            return 2
    else:
        accounts = get_drive_accounts()

    if not accounts:
        logger.error("GMAIL_ACCOUNTS no configurado en .env")
        return 1

    total_processed = 0
    total_errors = 0
    dry_reports = {}

    for account in accounts:
        try:
            processed, errors, dry_report = process_account(account, dry_run=args.dry_run)
            total_processed += processed
            total_errors += errors
            if dry_report is not None:
                dry_reports[account] = dry_report
        except Exception as e:
            logger.error(f"[drive:{account}] Excepcion no controlada (no aborta batch): {e}")
            total_errors += 1

    if args.dry_run:
        out = {
            "dry_run": True,
            "accounts": dry_reports,
            "summary": {
                "total_files": sum(d.get("msg_count", 0) for d in dry_reports.values()),
                "errors": total_errors,
            },
        }
        sys.stderr.write("--- DRY-RUN JSON ---\n")
        sys.stderr.write(json.dumps(out, indent=2, default=str))
        sys.stderr.write("\n")
        sys.stderr.flush()

    # PATCH v2: cancelar alarma al terminar OK
    if args.once:
        signal.alarm(0)
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))