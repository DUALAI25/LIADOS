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
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from db_connection import get_conn

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


def _sanitize_error(e):
    """Limpia mensajes de error para evitar filtrar tokens o credenciales."""
    msg = str(e)
    for needle in ('Bearer ', 'Authorization', 'sk-', 'github_pat_', 'client_secret', 'refresh_token'):
        idx = msg.find(needle)
        if idx >= 0:
            msg = msg[:idx + len(needle)] + '[REDACTED]'
    return msg


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
    """Resuelve la ruta del token para una cuenta (relativas contra WORKSPACE)."""
    env = load_env_dict()
    var_name = f'GMAIL_TOKEN_FILE_{account}'
    path = env.get(var_name, '')
    if path and not path.startswith('/'):
        path = str(WORKSPACE / path)
    return path


def get_service(account):
    """Crea el servicio Gmail para una cuenta.

    VERSION HARDENED 2026-07-01: distingue 3 estados (revoked/expired/ok),
    purga tokens muertos a /root/liados/data/tokens_revoked/, avisa con TAG.

    Returns:
        (service, status):
          - (svc, 'ok')               - servicio construido
          - (None, 'revoked')         - refresh_token invalid_grant (purga automatica)
          - (None, 'missing')         - token file no existe
          - (None, 'transient_error') - red/5xx/etc
          - (None, 'config_error')    - archivo malformado
    """
    from oauth_hardening import get_service_v2
    token_file = get_token_path_for_account(account)
    if not token_file:
        logger.error(f"[{account}] GMAIL_TOKEN_FILE_{account} no configurado en .env")
        return None, 'config_error'

    svc, status = get_service_v2(account, token_file)

    if status == 'revoked':
        logger.warning(
            f"[{account}] TOKEN REVOCADO POR GOOGLE. Reautorizar con:"
            f" python3 -m agente.scripts.gmail_auth --account {account} --force"
        )
        log_agent(
            'gmail_collector', 'error',
            f"[{account}] OAuth token REVOKED - reauth required",
        )
    elif status == 'missing':
        logger.error(f"[{account}] Token no encontrado: {token_file}")
        logger.error(f"  Ejecuta: python3 -m agente.scripts.gmail_auth --account {account}")
    return svc, status

def save_non_invoice(account, source_id, attachment, reason, subject):
    """Guarda un adjunto descartado por el filtro `is_invoice` en la tabla
    `gmail_non_invoices` para auditoría.

    Args:
        account: nombre de la cuenta Gmail (ej: 'principal')
        source_id: identificador único del mensaje (ej: 'principal:msgid')
        attachment: dict con filename, content_hash, mime_type
        reason: motivo del descarte (ej: 'keyword:\\bcontrato\\b')
        subject: asunto del email
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO gmail_non_invoices (
            account, source_id, filename, mime_type, content_hash,
            reason, subject, detected_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (account, source_id, content_hash) DO NOTHING
    """, (
        account, source_id, attachment['filename'], attachment['mime_type'],
        attachment['content_hash'], reason, (subject or '')[:500]
    ))
    conn.commit()
    cur.close()
    conn.close()


def process_account(account, search_query=None):
    """Procesa todas las facturas de una cuenta"""
    if search_query is None:
        search_query = SEARCH_QUERY
    logger.info(f"{'='*60}")
    logger.info(f"📧 Procesando cuenta: {account}")
    logger.info(f"{'='*60}")

    service, status = get_service(account)
    if not service:
        if status == 'revoked':
            logger.warning(
                f"[{account}] Saltando cuenta: token revocado por Google."
                f" El token moribundo fue purgado a data/tokens_revoked/."
                f" Reautorizar con gmail_auth.py --account {account} --force"
            )
            # CRITICO: devolver 0, 1 para que el caller sepa que NO se procesaron
            return 0, 1
        logger.warning(f"[{account}] Saltando cuenta ({status})")
        log_agent('gmail_collector', 'error', f"[{account}] Gmail service no disponible ({status})")
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
            # FIX 2026-06-22: source_id se calcula una sola vez por mensaje y se
            # reutiliza para que is_duplicate_by_hash ignore nuestro propio
            # re-proceso (bug que marcaba 323 facturas como duplicate).
            source_id = f"{account}:{msg['id']}"
            for att in attachments:
                if is_duplicate_by_hash(att['content_hash'], current_source_id=source_id):
                    logger.info(f"  [duplicado] {att['filename']}")
                    mark_as_duplicate('gmail', source_id)
                    continue

                # Guardar archivo
                storage_info = save_raw_file(att['content'], att['filename'])
                local_path = storage_info['local_path']
                minio_url = storage_info.get('minio_url')

                # FIX 2026-06-23: filtrar adjuntos que NO son facturas reales ANTES de
                # parsear. Evita meter contratos, propuestas, info legal y modelos
                # Hacienda en la tabla `invoices`. Lo que se descarta se guarda
                # en `gmail_non_invoices` para auditoría.
                try:
                    from is_invoice_filter import is_invoice_attachment
                    msg_subject = ''
                    for h in message.get('payload', {}).get('headers', []):
                        if h.get('name', '').lower() == 'subject':
                            msg_subject = h.get('value', '')
                            break
                    is_inv, reason = is_invoice_attachment(att['filename'], msg_subject)
                    if not is_inv:
                        try:
                            save_non_invoice(account, source_id, att, reason, msg_subject)
                        except Exception as e:
                            logger.warning(f"  [skip no-factura, no se pudo guardar en non_invoices: {e}]")
                        logger.info(f"  [skip no-factura] {att['filename']} ({reason})")
                        continue
                except ImportError:
                    # Si is_invoice_filter no está disponible, continuar sin filtrar
                    logger.debug("is_invoice_filter no disponible, saltando filtro")

                # Parsear con IA
                parsed = parse_invoice(local_path, att['mime_type'], att['filename'])
                if parsed:
                    parsed['content_hash'] = att['content_hash']
                    parsed['local_path'] = local_path
                    parsed['minio_url'] = minio_url
                    parsed['source_account'] = account  # <- multi-cuenta
                    # source_id incluye la cuenta para unicidad
                    inv_id = save_invoice(parsed, source='gmail', source_id=source_id, inv_type='expense')
                    if minio_url and inv_id:
                        save_raw_file(att['content'], att['filename'], invoice_id=inv_id)
                    logger.info(f"  ✅ {parsed.get('invoice_number', '?')} → {inv_id}")
                    processed += 1
                else:
                    logger.warning(f"  ⚠️  No se pudo parsear: {att['filename']}")
                    errors += 1
        except Exception as e:
            logger.error(f"  ❌ Error msg {msg['id']}: {_sanitize_error(e)}")
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

        size = body.get('size', 0)
        # FIX 2026-06-22: filtrar adjuntos que NO son facturas reales antes de
        # descargar. Emails HTML suelen traer iconos/separadores de <1KB que
        # coinciden con la query "factura/invoice/albaran" del subject pero no
        # son el documento. Esto causaba 10 facturas pending con imagenes
        # 12-50px que la IA no puede parsear.
        if mime_type.startswith('image/'):
            # Imagen: si <10KB o dimensiones <100x100 -> no es factura
            if size < 10240:
                logger.info(f"  [skip imagen pequena] {filename} ({size}b)")
                continue
        elif mime_type == 'application/pdf':
            # PDF: si <5KB probablemente es un PDF vacio o de prueba
            if size < 5120:
                logger.info(f"  [skip PDF pequeno] {filename} ({size}b)")
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
