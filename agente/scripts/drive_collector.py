"""
drive_collector.py — Colector de facturas desde Google Drive.

v1 (2026-07-12): descarga PDFs/imagenes desde una carpeta Drive y los pasa
por el pipeline estandar (parse_invoice + dedup_checker + INSERT).

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from io import BytesIO
from googleapiclient.http import MediaIoBaseDownload

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

logger = logging.getLogger(__name__)

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
        resp = service.files().list(**kwargs).execute()
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
    # NO filtramos subcarpetas por modified_after: una carpeta de 2025 puede
    # contener PDFs de 2026. Solo filtramos al listar ARCHIVOS finales.
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
        resp = service.files().list(**kwargs).execute()
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
    """Descarga archivo de Drive a dest_path. Devuelve bytes escritos."""
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
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
        try:
            is_inv, reason = is_invoice_attachment(name, subject=None)
        except Exception as e:
            logger.warning(f"[drive:{account}] is_invoice_filter fallo {name}: {e}")
            is_inv, reason = True, "filter_unavailable"
        if not is_inv:
            logger.debug(f"[drive:{account}] saltando {name} (no-factura: {reason})")
            continue

        file_id = f["id"]
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
        # El hash real MD5 del contenido se calcula tras descarga
        tmp_dest = f"/tmp/drive_{file_id}_{name}"
        try:
            size = download_drive_file(service, file_id, tmp_dest)
        except Exception as e:
            logger.error(f"[drive:{account}] descarga fallo {name}: {e}")
            errors += 1
            continue

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
            os.remove(tmp_dest)
            continue

        # Mover a destino final con nombre hasheado
        final_name = f"{content_hash}_{name}"
        final_path = f"/root/liados/{RAW_SUBPATH}/{yyyy}/{mm}/{final_name}"
        try:
            Path(final_path).parent.mkdir(parents=True, exist_ok=True)
            os.rename(tmp_dest, final_path)
        except Exception as e:
            logger.error(f"[drive:{account}] fallo mover {tmp_dest} -> {final_path}: {e}")
            errors += 1
            continue

        # Parsear con IA (igual que gmail_collector)
        try:
            with open(final_path, "rb") as fh:
                content_bytes = fh.read()
            # parse_invoice espera path o bytes; ajustar segun firma
            # parse_invoice(file_path_or_content, mime_type, filename)
            # El mime del archivo Drive se infiere del nombre (Drive ya filtro por extension)
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
            # Detectar facturas rechazadas por el parser (heuristica: confidence muy baja o explicitamente no-factura)
            is_actually_invoice = parsed.get('is_invoice', True)
            confidence = parsed.get('confidence_score', 0.0) or 0.0
            if not is_actually_invoice or confidence < 0.3:
                logger.info(f"[drive:{account}] no-factura {name} (conf={confidence:.2f})")
                # Insertar como is_invoice=false (igual que el auto-reject del flujo normal)
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
            processed += 1
        except Exception as e:
            logger.error(f"[drive:{account}] parse/insert fallo {name}: {e}")
            errors += 1

    # Update sync_control
    update_last_sync(f"{SYNC_KEY_PREFIX}:{account}")
    logger.info(f"[drive:{account}] processed={processed} errors={errors}")
    return processed, errors, None


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
    args = parser.parse_args(argv)

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
            logger.error(f"[drive:{account}] Excepcion no controlada: {e}")
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

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))