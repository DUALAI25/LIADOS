import os
import hashlib
import base64
import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from invoice_parser import parse_invoice
from db_writer import save_invoice, log_agent, update_last_sync
from dedup_checker import is_duplicate_by_hash, mark_as_duplicate
from storage import save_raw_file

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
SEARCH_QUERY = '(factura OR invoice OR receipt OR recibo OR "nota de cargo") has:attachment'


def get_service():
    token_file = os.getenv('GMAIL_TOKEN_FILE')
    if not token_file:
        logger.error("GMAIL_TOKEN_FILE no configurado en .env")
        return None
    if not os.path.exists(token_file):
        logger.error(f"Archivo de token no encontrado: {token_file}")
        return None
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    return build('gmail', 'v1', credentials=creds)


def main():
    service = get_service()
    if not service:
        log_agent('gmail_collector', 'error', 'Gmail service no disponible — credenciales no configuradas')
        return

    if not os.getenv('OPENAI_API_KEY'):
        logger.error("OPENAI_API_KEY no configurado en .env")
        log_agent('gmail_collector', 'error', 'OPENAI_API_KEY no configurado')
        return

    results = service.users().messages().list(
        userId='me', q=SEARCH_QUERY, maxResults=50
    ).execute()

    all_messages = []
    while True:
        batch = results.get('messages', [])
        all_messages.extend(batch)
        next_token = results.get('nextPageToken')
        if not next_token:
            break
        results = service.users().messages().list(
            userId='me', q=SEARCH_QUERY, maxResults=50, pageToken=next_token
        ).execute()

    messages = all_messages

    logger.info(f"Gmail: {len(messages)} mensajes encontrados")
    processed = 0
    errors = 0

    for msg in messages:
        try:
            message = service.users().messages().get(
                userId='me', id=msg['id'], format='full'
            ).execute()

            attachments = _extract_attachments(service, message)
            for att in attachments:
                if is_duplicate_by_hash(att['content_hash']):
                    logger.info(f"  Duplicado (hash): {att['filename']}")
                    mark_as_duplicate('gmail', msg['id'])
                    continue

                # Guardar archivo localmente y en MinIO
                storage_info = save_raw_file(att['content'], att['filename'])
                local_path = storage_info['local_path']
                minio_url = storage_info['minio_url']

                parsed = parse_invoice(local_path, att['mime_type'], att['filename'])
                if parsed:
                    parsed['content_hash'] = att['content_hash']
                    parsed['local_path'] = local_path
                    parsed['minio_url'] = minio_url
                    inv_id = save_invoice(parsed, source='gmail', source_id=msg['id'], inv_type='expense')
                    # Actualizar ruta de MinIO con ID de factura
                    if minio_url:
                        storage_info = save_raw_file(att['content'], att['filename'], invoice_id=inv_id)
                    logger.info(f"  Guardada: {parsed.get('invoice_number', '?')} -> {inv_id}")
                    processed += 1
                else:
                    logger.warning(f"  No se pudo parsear: {att['filename']}")
                    errors += 1
        except Exception as e:
            logger.error(f"Error procesando mensaje {msg['id']}: {e}")
            errors += 1

    log_agent('gmail_collector', 'info' if errors == 0 else 'warning',
              f"Procesados {processed}, errores {errors}")
    update_last_sync('gmail', status='error' if errors > 0 else 'ok')
    logger.info(f"Gmail: {processed} procesadas, {errors} errores")


def _extract_attachments(service, message):
    attachments = []
    payload = message.get('payload', {})
    _walk_parts(service, message['id'], payload.get('parts', []), attachments)
    return attachments


def _walk_parts(service, msg_id, parts, attachments):
    for part in parts:
        filename = part.get('filename', '')
        mime_type = part.get('mimeType', '')

        # Si tiene sub-partes, recorrer recursivamente
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


if __name__ == '__main__':
    main()
