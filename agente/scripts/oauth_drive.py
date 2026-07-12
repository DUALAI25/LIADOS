"""
oauth_drive.py — Reutiliza la infraestructura de oauth_hardening.py
pero con scope Drive.

v1 (2026-07-12): scope drive.readonly para listar y descargar PDFs.
   No comparte token con Gmail (mantiene aislamiento: Gmail vivo
   no se invalida si Drive falla al reautorizar).

Uso:
    from agente.scripts.oauth_drive import get_drive_service, get_drive_status
    service, status = get_drive_service("principal")
"""
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Scope solo Drive — INDEPENDIENTE del scope Gmail
DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
DRIVE_CREDENTIALS_FILE = os.getenv(
    "GMAIL_CREDENTIALS_FILE_principal",  # reutilizamos el mismo client_secret
    "/root/liados/agente/credentials/gmail_credentials_principal.json"
)
DRIVE_TOKEN_FILE = os.getenv(
    "DRIVE_TOKEN_FILE_principal",
    "/root/liados/agente/credentials/drive_token_principal.json"
)
MAX_TOKEN_AGE_HOURS = 24


def _get_credentials_paths(account="principal"):
    """Devuelve (credentials_file, token_file) para la cuenta."""
    cred_file = os.getenv(
        f"GMAIL_CREDENTIALS_FILE_{account}",
        f"/root/liados/agente/credentials/gmail_credentials_{account}.json"
    )
    tok_file = os.getenv(
        f"DRIVE_TOKEN_FILE_{account}",
        f"/root/liados/agente/credentials/drive_token_{account}.json"
    )
    return cred_file, tok_file


def _load_token(tok_file):
    if not Path(tok_file).exists():
        return None
    try:
        with open(tok_file) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error leyendo token Drive {tok_file}: {e}")
        return None


def _persist_token(tok_file, creds, client_id, client_secret):
    """Reescribe token Drive a disco."""
    new_data = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expires_in": 3599,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": " ".join(DRIVE_SCOPES),
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "last_refresh": datetime.now(timezone.utc).isoformat(),
    }
    with open(tok_file, "w") as f:
        json.dump(new_data, f, indent=2)
    os.chmod(tok_file, 0o600)


def _purge_token(tok_file, reason):
    """Mueve token a data/tokens_revoked/ con motivo."""
    from agente.scripts.oauth_hardening import _purge_token as _purge_oauth
    try:
        _purge_oauth(tok_file, reason)
    except Exception as e:
        logger.warning(f"No se pudo purgar token Drive: {e}")


def get_drive_service(account="principal"):
    """Devuelve (service, status) igual que oauth_hardening.get_service().

    status: 'ok' | 'missing' | 'revoked' | 'transient_error'
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from googleapiclient.discovery import build

    cred_file, tok_file = _get_credentials_paths(account)

    if not Path(cred_file).exists():
        logger.error(f"[drive:{account}] credentials file no existe: {cred_file}")
        return None, "missing"

    token_data = _load_token(tok_file)
    if not token_data:
        return None, "missing"

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        logger.warning(f"[drive:{account}] token sin refresh_token")
        return None, "missing"

    client_id = token_data.get("client_id") or json.load(open(cred_file))["installed"]["client_id"]
    client_secret = token_data.get("client_secret") or json.load(open(cred_file))["installed"]["client_secret"]

    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=DRIVE_SCOPES,
    )

    # Refresh proactivo si token viejo (>24h)
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(tok_file), tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        if age_hours > MAX_TOKEN_AGE_HOURS:
            logger.info(f"[drive:{account}] Token {age_hours:.1f}h viejo, probando refresh")
            creds.refresh(Request())
            _persist_token(tok_file, creds, client_id, client_secret)
    except RefreshError as re:
        err_text = str(re).lower()
        if "invalid_grant" in err_text or "revoked" in err_text:
            _purge_token(tok_file, "invalid_grant_drive_refresh")
            return None, "revoked"
        logger.error(f"[drive:{account}] RefreshError: {re}")
        return None, "transient_error"
    except Exception as e:
        logger.warning(f"[drive:{account}] refresh preventivo fallo (no bloqueante): {e}")

    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service, "ok"
    except Exception as e:
        logger.error(f"[drive:{account}] Error creando servicio Drive: {e}")
        return None, "transient_error"


def get_drive_status(account="principal"):
    """Devuelve dict con metadatos del token Drive (igual que /api/admin/gmail-status)."""
    _, tok_file = _get_credentials_paths(account)
    if not Path(tok_file).exists():
        return {"account": account, "exists": False, "status": "MISSING"}

    token_data = _load_token(tok_file) or {}
    issued = token_data.get("issued_at")
    age_days = None
    if issued:
        try:
            ts = datetime.fromisoformat(issued.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - ts).days
        except Exception:
            pass

    has_refresh = bool(token_data.get("refresh_token"))
    has_access = bool(token_data.get("access_token"))
    status = "OK" if has_refresh else "MISSING_TOKEN"
    if has_refresh and age_days is not None and age_days > 180:
        status = "STALE"

    return {
        "account": account,
        "exists": True,
        "token_file": tok_file,
        "has_refresh_token": has_refresh,
        "has_access_token": has_access,
        "scope": token_data.get("scope"),
        "issued_at": issued,
        "age_days": age_days,
        "status": status,
    }


def get_drive_oauth_url(account="principal", redirect_port=8085):
    """Genera URL para OAuth flow Drive-only."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    cred_file, _ = _get_credentials_paths(account)
    flow = InstalledAppFlow.from_client_secrets_file(cred_file, scopes=DRIVE_SCOPES)
    flow.redirect_uri = f"http://localhost:{redirect_port}/"
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # forzar refresh_token
    )
    return auth_url


def exchange_code_for_token(account, code, redirect_port=8085):
    """Intercambia code OAuth por token Drive."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    cred_file, tok_file = _get_credentials_paths(account)
    flow = InstalledAppFlow.from_client_secrets_file(cred_file, scopes=DRIVE_SCOPES)
    flow.redirect_uri = f"http://localhost:{redirect_port}/"
    flow.fetch_token(code=code)
    creds = flow.credentials
    _persist_token(
        tok_file,
        creds,
        creds.client_id or json.load(open(cred_file))["installed"]["client_id"],
        creds.client_secret or json.load(open(cred_file))["installed"]["client_secret"],
    )
    return tok_file


def main(argv=None):
    """CLI:
        oauth_drive.py status [account]     -> muestra estado token
        oauth_drive.py auth-url [account]   -> genera URL OAuth
        oauth_drive.py exchange CODE [acc]  -> intercambia code por token
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "auth-url", "exchange"])
    parser.add_argument("arg", nargs="?", default=None)
    parser.add_argument("--account", default="principal")
    parser.add_argument("--redirect-port", type=int, default=8085)
    args = parser.parse_args(argv)

    if args.action == "status":
        s = get_drive_status(args.account)
        print(json.dumps(s, indent=2))
    elif args.action == "auth-url":
        url = get_drive_oauth_url(args.account, args.redirect_port)
        print(url)
    elif args.action == "exchange":
        if not args.arg:
            print("Falta el code")
            return 2
        path = exchange_code_for_token(args.account, args.arg, args.redirect_port)
        print(f"Token guardado en: {path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))