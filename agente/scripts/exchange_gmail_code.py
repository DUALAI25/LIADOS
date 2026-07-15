"""
exchange_gmail_code.py — Recibe un codigo OAuth y genera el token.
Se usa DESPUES de que el usuario autorizo en su navegador.

Uso:
    python -m agente.scripts.exchange_gmail_code --account secundaria --code "4/0A..."
"""
import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

from google_auth_oauthlib.flow import Flow

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--code", required=True, help="Codigo OAuth pegado por el usuario")
    args = parser.parse_args()
    account = args.account
    code = args.code.strip()

    WORKSPACE = Path("/root/liados")
    state_file = WORKSPACE / "data" / ".oauth_state" / f"{account}.json"
    creds_dir = WORKSPACE / "agente" / "credentials"
    token_file = creds_dir / f"gmail_token_{account}.json"

    if not state_file.exists():
        print(f"ERROR: no existe {state_file}. Genera URL primero con get_auth_url_gmail.py", file=sys.stderr)
        return 1

    with open(state_file) as f:
        state = json.load(f)

    flow = Flow.from_client_config(
        state["client_config"],
        scopes=state["scopes"],
        state=state.get("state"),
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",
    )

    # Restaurar code_verifier si existe
    if "code_verifier" in state and state["code_verifier"]:
        flow.oauth2session.code_verifier = state["code_verifier"]

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        print(f"ERROR: fallo fetch_token: {e}", file=sys.stderr)
        return 1

    creds = flow.credentials

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
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }

    creds_dir.mkdir(parents=True, exist_ok=True)
    with open(token_file, "w") as f:
        json.dump(token_data, f, indent=2)
    os.chmod(token_file, 0o600)

    # Limpiar state file (ya no sirve)
    try:
        state_file.unlink()
    except Exception:
        pass

    # Sanity check
    try:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "?")
        total_msgs = profile.get("messagesTotal", "?")
        print(f"OK Cuenta '{account}' autorizada: {email} ({total_msgs} mensajes)")
        return 0
    except Exception as e:
        print(f"WARN Token guardado pero sanity check fallo: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())