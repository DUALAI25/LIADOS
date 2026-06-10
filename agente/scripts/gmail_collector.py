"""
gmail_collector.py — Recolector de facturas desde Gmail (multi-cuenta)

Soporta N cuentas Gmail. Configuradas en .env:
  GMAIL_ACCOUNTS=principal,secundaria
  GMAIL_TOKEN_FILE_principal=...
  GMAIL_TOKEN_FILE_secundaria=...

Para cada cuenta, itera sobre mensajes con adjuntos PDF/JPEG/PNG
que parezcan facturas, parsea con IA, deduplica por hash, guarda
en DB + filesystem local (o MinIO si está configurado).
"""
import os
import sys
import json
import hashlib
import base64
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Carga .env manualmente (este script puede correr sin venv, standalone o via -m)
try:
    WORKSPACE = Path(__file__).resolve().parent.parent.parent
except NameError:
    WORKSPACE = Path(os.getcwd())
ENV_FILE = WORKSPACE / '.env'

def load_env():
    """Carga variables del .env en os.environ. Usa setdefault para no pisar
    valores ya inyectados por el orquestador (run_all.py)."""
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    else:
        logger = logging.getLogger(__name__)
        logger.warning(".env no encontrado en %s, usando variables de entorno existentes", WORKSPACE)

# Cargar env ANTES de cualquier import que use BD o APIs externas
load_env()

from invoice_parser import parse_invoice
from db_writer import save_invoice, log_agent, update_last_sync, get_last_sync
from dedup_checker import is_duplicate_by_hash, mark_as_duplicate
from storage import save_raw_file

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
SEARCH_QUERY = '(factura OR invoice OR receipt OR recibo OR "nota de cargo" OR albarán) has:attachment'
INITIAL_DAYS = int(os.getenv('GMAIL_INITIAL_DAYS', '30'))


def load_env_dict():
    """Lee .env a dict (sin contaminar os.environ)"""
    env = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def get_gmail_accounts():
    """Lee GMAIL_ACCOUNTS del .env y devuelve lista de nombres"""
    env = load_env_dict()
    accounts_raw = env.get('GMAIL_ACCOUNTS', '')
    accounts = [a.strip() for a in accounts_raw.split(',') if a.strip()]
    return accounts


def get_token_path_for_account(account):
    """Resuelve la ruta del token para una cuenta"""
    env = load_env_dict()
    var_name = f'GMAIL_TOKEN_FILE_{account}'
    return env.get(var_name, '')


def get_service(account):
    """Crea el servicio Gmail para una cuenta"""
    token_file = get_token_path_for_account(account)
    if not token_file:
        logger.error(f"[{account}] GMAIL_TOKEN_FILE_{account} no configurado en .env")
        return None
    if not os.path.exists(token_file):
        logger.error(f"[{account}] Token no encontrado: {token_file}")
        logger.error(f"  Ejecuta: python3 gmail_auth.py --account {account}")
        return None
    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        logger.error(f"[{account}] Error creando servicio Gmail: {e}")
        return None


def process_account(account, search_query=None):
    """Procesa todas las facturas de una cuenta"""
    if search_query is None:
        search_query = SEARCH_QUERY
    logger.info(f"{'='*60}")
    logger.info(f"📧 Procesando cuenta: {account}")
    logger.info(f"{'='*60}")

    service = get_service(account)
    if not service:
        log_agent('gmail_collector', 'error', f"[{account}] Gmail service no disponible")
        return 0, 1

    if not os.getenv('OPENCODE_API_KEY'):
        logger.error(f"[{account}] OPENCODE_API_KEY no configurado en .env")
        log_agent('gmail_collector', 'error', f"[{account}] OPENCODE_API_KEY no configurado")
        return 0, 1

    # Listar mensajes
    all_messages = []
    next_token = None
    while True:
        results = service.users().messages().list(
            userId='me', q=search_query, maxResults=50, pageToken=next_token
        ).execute()
        all_messages.extend(results.get('messages', []))
        next_token = results.get('nextPageToken')
        if not next_token:
            break

    logger.info(f"[{account}] {len(all_messages)} mensajes con adjuntos de factura")

    processed = 0
    errors = 0

    for msg in all_messages:
        try:
            message = service.users().messages().get(
                userId='me', id=msg['id'], format='full'
            ).execute()

            attachments = _extract_attachments(service, message)
            for att in attachments:
                if is_duplicate_by_hash(att['content_hash']):
                    logger.info(f"  [duplicado] {att['filename']}")
                    mark_as_duplicate('gmail', f"{account}:{msg['id']}")
                    continue

                # Guardar archivo
                storage_info = save_raw_file(att['content'], att['filename'])
                local_path = storage_info['local_path']
                minio_url = storage_info.get('minio_url')

                # Parsear con IA
                parsed = parse_invoice(local_path, att['mime_type'], att['filename'])
                if parsed:
                    parsed['content_hash'] = att['content_hash']
                    parsed['local_path'] = local_path
                    parsed['minio_url'] = minio_url
                    parsed['source_account'] = account  # <- multi-cuenta
                    # source_id incluye la cuenta para unicidad
                    source_id = f"{account}:{msg['id']}"
                    inv_id = save_invoice(parsed, source='gmail', source_id=source_id, inv_type='expense')
                    if minio_url and inv_id:
                        save_raw_file(att['content'], att['filename'], invoice_id=inv_id)
                    logger.info(f"  ✅ {parsed.get('invoice_number', '?')} → {inv_id}")
                    processed += 1
                else:
                    logger.warning(f"  ⚠️  No se pudo parsear: {att['filename']}")
                    errors += 1
        except Exception as e:
            logger.error(f"  ❌ Error msg {msg['id']}: {e}")
            errors += 1

    log_agent('gmail_collector', 'info' if errors == 0 else 'warning',
              f"[{account}] Procesados {processed}, errores {errors}")
    return processed, errors


def _extract_attachments(service, message):
    attachments = []
    payload = message.get('payload', {})
    _walk_parts(service, message['id'], payload.get('parts', []), attachments)
    return attachments


def _walk_parts(service, msg_id, parts, attachments):
    for part in parts:
        filename = part.get('filename', '')
        mime_type = part.get('mimeType', '')

        sub_parts = part.get('parts', [])
        if sub_parts:
            _walk_parts(service, msg_id, sub_parts, attachments)
            continue

        if not filename or mime_type not in ('application/pdf', 'image/jpeg', 'image/png'):
            continue

        body = part.get('body', {})
        att_id = body.get('attachmentId')
        if not att_id:
            continue

        att_data = service.users().messages().attachments().get(
            userId='me', messageId=msg_id, id=att_id
        ).execute()

        file_data = base64.urlsafe_b64decode(att_data['data'].encode('UTF-8'))
        content_hash = hashlib.md5(file_data).hexdigest()

        attachments.append({
            'filename': filename,
            'content': file_data,
            'mime_type': mime_type,
            'content_hash': content_hash
        })


def main():
    accounts = get_gmail_accounts()
    if not accounts:
        logger.error("GMAIL_ACCOUNTS no configurado en .env")
        logger.error("Añade: GMAIL_ACCOUNTS=cuenta1,cuenta2")
        sys.exit(1)

    last_sync = get_last_sync('gmail')
    # Defensivo: si la BD devuelve datetime naive (sin tz), lo marcamos como UTC
    if last_sync is not None and last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)
        logger.warning("last_sync de BD era naive, asumido UTC")
    if last_sync and last_sync.year > 2000:
        since_date = last_sync
        logger.info("Gmail: incremental desde %s", since_date.isoformat())
    else:
        since_date = datetime.now(timezone.utc) - timedelta(days=INITIAL_DAYS)
        logger.info("Gmail: primera ejecucion, procesando ultimos %d dias desde %s",
                     INITIAL_DAYS, since_date.isoformat())

    date_filter = since_date.strftime('%Y/%m/%d')
    search_query = f"{SEARCH_QUERY} after:{date_filter}"
    logger.info("Gmail query: %s", search_query)

    # Marcar sync como en curso ANTES de procesar. Asi, si el proceso muere
    # por timeout/exception, al menos sabemos que llego a empezar.
    try:
        update_last_sync('gmail', status='warning')
        logger.info("Gmail: sync marcado como en curso en sync_control")
    except Exception as e:
        logger.warning("No se pudo marcar sync como en curso: %s", str(e))

    total_processed = 0
    total_errors = 0

    for account in accounts:
        processed, errors = process_account(account, search_query=search_query)
        total_processed += processed
        total_errors += errors

    try:
        update_last_sync('gmail', status='error' if total_errors > 0 else 'ok')
    except Exception as e:
        logger.error("No se pudo actualizar sync_control al final: %s", str(e))
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"📊 RESUMEN TOTAL: {total_processed} procesadas, {total_errors} errores")
    logger.info("=" * 60)

    return 0 if total_errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
