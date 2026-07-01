"""
oauth_hardening.py — Mejoras defensivas para gmail_collector.py (Fase 0)

CAMBIOS PRINCIPALES vs get_service() original:

1. Distingue 3 estados de credenciales:
   - OK: token valido y fresco
   - EXPIRED: access expirado, refresh posible con refresh_token existente
   - REVOKED: refresh_token INVALID_GRANT (refresh fallo o token manual revocado)
   - MISSING: no hay archivo de token

2. Cuando REVOKED:
   - Purgar el token malo a /root/liados/data/tokens_revoked/<timestamp>.json
   - Devuelve None con TAG claro para que el caller pueda enviar alerta por
     Telegram o email
   - Log de WARN level con cuenta, error exacto y remediation

3. Refresh exitoso: REESCRIBE el token a disco incluyendo el access_token
   nuevo, expires_in actualizado, y refresh_token (que puede haber cambiado)
   Esta es la causa raíz del bug: el codigo original reusa el mismo refresh_token
   muerto en lugar de actualizar el JSON al estado actual post-refresh.

4. Probe preventivo: si la ultima modificacion del token es >24h,
   intentar refresh proactivo ANTES de devolver creds.
"""

import os
import json
import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Directorio para purgar tokens muertos (auditoria)
REVOKED_DIR = Path('/root/liados/data/tokens_revoked')

# Maxima antiguedad antes de refresh proactivo (24h es un margen conservador)
MAX_TOKEN_AGE_HOURS = 24


def _purge_token(token_path: str, reason: str) -> Optional[str]:
    """Mueve el token muerto a /root/liados/data/tokens_revoked/ para auditoria.

    Devuelve la ruta del archivo purgado para que el caller pueda notificar.
    """
    try:
        REVOKED_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        token_name = Path(token_path).name
        backup = REVOKED_DIR / f"{ts}_{token_name}.{reason}"
        shutil.move(token_path, str(backup))
        return str(backup)
    except Exception as e:
        logger.error(f"  No se pudo purgar token {token_path}: {e}")
        return None


def get_service_v2(account: str, token_file: str) -> Tuple[Optional[object], str]:
    """Crea el servicio Gmail para una cuenta. Anti-desconfiguración.

    Returns:
        (service, status) donde status es uno de:
        - 'ok': servicio construido OK
        - 'missing': token no existe
        - 'revoked': refresh_token invalid_grant (purga automatica)
        - 'transient_error': error transitorio (red, 5xx, etc.)
        - 'config_error': config invalida (no client_id, etc.)
    """
    if not token_file or not os.path.exists(token_file):
        logger.error(f"[{account}] Token no encontrado: {token_file}")
        return None, 'missing'

    try:
        # 1. Cargar credenciales desde archivo
        with open(token_file) as f:
            token_data = json.load(f)
        client_id = token_data.get('client_id')
        client_secret = token_data.get('client_secret')
        refresh_token = token_data.get('refresh_token')

        if not all([client_id, client_secret, refresh_token]):
            logger.error(f"[{account}] Token file malformado: faltan campos")
            return None, 'config_error'

        creds = Credentials(
            token=token_data.get('access_token'),
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )

        # 2. Probe preventivo: si el archivo tiene >24h, refrescar antes de usar
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(token_file), tz=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
            if age_hours > MAX_TOKEN_AGE_HOURS:
                logger.info(f"[{account}] Token {age_hours:.1f}h viejo, probando refresh preventivo")
                try:
                    creds.refresh(Request())
                    _persist_token(token_file, creds, token_data, client_id, client_secret)
                except RefreshError as re:
                    err_text = str(re).lower()
                    if 'invalid_grant' in err_text or 'revoked' in err_text:
                        logger.warning(f"[{account}] 🔴 Refresh proactivo: token REVOCADO")
                        purged = _purge_token(token_file, 'invalid_grant_proactive')
                        return None, 'revoked'
                    raise  # re-lanza transient
        except OSError:
            pass

        # 3. Refresh si el access esta vencido (rama original)
        if creds.expired and creds.refresh_token:
            logger.info(f"[{account}] Token expirado, refrescando...")
            try:
                creds.refresh(Request())
                # IMPORTANTE: reescribir el token actualizado a disco (FIX bug original)
                _persist_token(token_file, creds, token_data, client_id, client_secret)
                logger.info(f"[{account}] Token refrescado y guardado en disco")
            except RefreshError as re:
                err_text = str(re).lower()
                if 'invalid_grant' in err_text or 'revoked' in err_text:
                    logger.warning(
                        f"[{account}] 🔴 Refresh dio invalid_grant — token revocado por Google"
                    )
                    purged = _purge_token(token_file, 'invalid_grant')
                    # CRÍTICO: devolver TAG 'revoked' para que el caller notifique
                    return None, 'revoked'
                raise  # transient -> cae al except de abajo

        # 4. Sanity check: hacer un call barato antes de devolver
        try:
            service = build('gmail', 'v1', credentials=creds)
            # ping barato: perfil del usuario (no requiere cuota adicional)
            service.users().getProfile(userId='me').execute()
            return service, 'ok'
        except Exception as e:
            err_text = str(e).lower()
            if 'invalid_grant' in err_text or ('401' in err_text and 'unauthorized' in err_text):
                logger.warning(f"[{account}] 🔴 API call devolvió 401 — token revocado")
                purged = _purge_token(token_file, 'invalid_grant_at_api')
                return None, 'revoked'
            raise

    except RefreshError as re:
        err_text = str(re).lower()
        if 'invalid_grant' in err_text or 'revoked' in err_text:
            logger.warning(f"[{account}] 🔴 Top-level RefreshError: token revocado")
            _purge_token(token_file, 'invalid_grant_top')
            return None, 'revoked'
        logger.error(f"[{account}] RefreshError transitorio: {re}")
        return None, 'transient_error'

    except Exception as e:
        err_text = _sanitize_error(str(e))
        if 'invalid_grant' in err_text or 'revoked' in err_text:
            logger.warning(f"[{account}] 🔴 invalid_grant atrapado en top-level")
            _purge_token(token_file, 'invalid_grant_unknown')
            return None, 'revoked'
        logger.error(f"[{account}] Error creando servicio Gmail: {err_text}")
        return None, 'transient_error'


def _persist_token(token_file, creds, original_data, client_id, client_secret):
    """Reescribe el token a disco con TODOS los campos actualizados."""
    new_data = dict(original_data)
    new_data['access_token'] = creds.token
    new_data['expires_in'] = 3599  # google siempre 1h
    new_data['expiry'] = creds.expiry.isoformat() if creds.expiry else None
    # CRÍTICO: refresh_token puede haber rotado; usar el de creds si lo hay
    if creds.refresh_token:
        new_data['refresh_token'] = creds.refresh_token
    new_data['client_id'] = client_id
    new_data['client_secret'] = client_secret
    new_data['scope'] = ' '.join(SCOPES)
    new_data['last_refresh'] = datetime.now(timezone.utc).isoformat()
    with open(token_file, 'w') as f:
        json.dump(new_data, f, indent=2)
    os.chmod(token_file, 0o600)  # 600 es lo seguro (root solo)


def _sanitize_error(msg: str) -> str:
    """Limpia el mensaje de error para no filtrar tokens."""
    for needle in ('Bearer ', 'Authorization', 'sk-', 'github_pat_',
                   'client_secret', 'refresh_token'):
        idx = msg.find(needle)
        if idx >= 0:
            msg = msg[:idx + len(needle)] + '[REDACTED]'
    return msg
