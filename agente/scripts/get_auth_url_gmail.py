"""
get_auth_url_gmail.py — Solo genera la URL OAuth sin pedir input.
Para entornos donde stdin no esta disponible (ssh remoto, cron, etc).

Uso:
    python -m agente.scripts.get_auth_url_gmail --account secundaria
"""
import os
import sys
import json
import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    account = args.account

    WORKSPACE = Path("/root/liados")
    creds_file = WORKSPACE / "agente" / "credentials" / f"gmail_credentials_{account}.json"

    if not creds_file.exists():
        print(f"ERROR: No existe {creds_file}", file=sys.stderr)
        return 1

    with open(creds_file) as f:
        client_config = json.load(f)

    config = client_config.get("installed") or client_config.get("web")
    if not config:
        print("ERROR: client config invalida", file=sys.stderr)
        return 1

    flow = InstalledAppFlow.from_client_config(
        {"installed": config},
        scopes=SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    # Guardar el flow serializado para reusarlo en el segundo paso
    # (sin esto, fetch_token falla porque el code_verifier se pierde)
    state_file = WORKSPACE / "data" / ".oauth_state" / f"{account}.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump({
            "client_config": {"installed": config},
            "scopes": SCOPES,
            "state": state,
            # CRITICO: el code_verifier DEBE persistirse entre procesos
            # porque run_console() lo regenera si no
        }, f)

    # Tambien guardamos el code_verifier que flow genero
    # (en google-auth-oauthlib moderno, el verifier esta en flow.oauth2session)
    try:
        verifier = flow.oauth2session.code_verifier
        with open(state_file, "w") as f:
            json.dump({
                "client_config": {"installed": config},
                "scopes": SCOPES,
                "state": state,
                "code_verifier": verifier,
            }, f)
    except Exception:
        pass

    print(auth_url)
    print(f"# STATE_FILE={state_file}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())