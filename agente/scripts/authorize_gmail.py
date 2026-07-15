"""
authorize_gmail.py — Script para autorizar UNA cuenta Gmail desde cero.

Uso (desde el VPS):
    python -m agente.scripts.authorize_gmail --account secundaria

Flujo:
1. Lee credenciales de agente/credentials/gmail_credentials_<account>.json
2. Genera URL de autorizacion con InstalledAppFlow
3. IMPRIME la URL a stdout
4. Espera a que el usuario pegue el codigo por stdin (timeout 5min)
5. Intercambia code -> token, guarda en credentials/gmail_token_<account>.json
6. Sanity check: hace un users().getProfile para confirmar
"""
import os
import sys
import json
import logging
import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# Mismos scopes que el collector real
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, help="principal | secundaria | ...")
    args = parser.parse_args()
    account = args.account

    WORKSPACE = Path("/root/liados")
    creds_dir = WORKSPACE / "agente" / "credentials"
    creds_file = creds_dir / f"gmail_credentials_{account}.json"
    token_file = creds_dir / f"gmail_token_{account}.json"

    if not creds_file.exists():
        logger.error(f"No existe {creds_file}")
        return 1

    if token_file.exists():
        logger.warning(f"YA existe token en {token_file}")
        resp = input("Sobreescribir? (s/N): ").strip().lower()
        if resp != "s":
            logger.info("Abortado por usuario")
            return 0

    # 1. Cargar client secrets
    with open(creds_file) as f:
        client_config = json.load(f)

    # Soporta tanto formato "installed" como "web"
    if "installed" in client_config:
        config = client_config["installed"]
    elif "web" in client_config:
        config = client_config["web"]
    else:
        logger.error("client config no tiene ni 'installed' ni 'web'")
        return 1

    # 2. Crear flow sin redirect_uri (lo hará run_local_server)
    # Pero como el VPS no tiene display, generamos URL manual y pedimos code
    flow = InstalledAppFlow.from_client_config(
        {"installed": config},
        scopes=SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",  # OOB = pedir code manual
    )

    # 3. Generar URL
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",  # fuerza refresh_token nuevo
        include_granted_scopes="true",
    )

    print()
    print("=" * 70)
    print(f"PASO 1: Abre esta URL en tu navegador (PC o móvil):")
    print()
    print(auth_url)
    print()
    print("=" * 70)
    print(f"PASO 2: Autoriza con la cuenta Gmail SECUNDARIA")
    print(f"PASO 3: Google te dará un codigo. Pegalo aqui abajo y dale Enter.")
    print(f"        (timeout 5 min)")
    print("=" * 70)
    print()

    # 4. Leer code de stdin
    try:
        code = input("Codigo de autorizacion: ").strip()
    except EOFError:
        logger.error("No se recibio codigo")
        return 1

    if not code:
        logger.error("Codigo vacio, abortando")
        return 1

    # 5. Intercambiar code -> token
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logger.error(f"Error intercambiando code por token: {e}")
        return 1

    creds = flow.credentials

    # 6. Guardar token en formato compatible con oauth_hardening.py
    token_data = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
        "scope": " ".join(SCOPES),
        "expires_in": 3599,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "issued_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }

    token_file.parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, "w") as f:
        json.dump(token_data, f, indent=2)
    os.chmod(token_file, 0o600)

    print()
    print("=" * 70)
    print(f"OK Token guardado en {token_file}")
    print("=" * 70)

    # 7. Sanity check
    try:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "?")
        total_msgs = profile.get("messagesTotal", "?")
        print()
        print(f"Sanity check OK:")
        print(f"  Email: {email}")
        print(f"  Total mensajes en inbox: {total_msgs}")
        print()
        print(f"Cuenta Gmail '{account}' AUTORIZADA correctamente")
        return 0
    except Exception as e:
        logger.error(f"Token guardado pero sanity check fallo: {e}")
        logger.error("El token puede estar roto, prueba de nuevo")
        return 2


if __name__ == "__main__":
    sys.exit(main())