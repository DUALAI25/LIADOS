"""
gmail_auth_code.py — Completa el OAuth con POST manual al token endpoint

El bug de requests_oauthlib también afecta a fetch_token(), así que hacemos
el POST a mano a https://oauth2.googleapis.com/token.
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta

WORKSPACE = Path(__file__).resolve().parent.parent.parent
ENV_FILE = WORKSPACE / '.env'
STATE_FILE = Path('/tmp/gmail_oauth_state.json')

TOKEN_URL = 'https://oauth2.googleapis.com/token'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('code', nargs='?', help='Código de autorización de Google')
    args = parser.parse_args()

    if not STATE_FILE.exists():
        print(f"❌ No se encuentra {STATE_FILE}")
        print("   Primero ejecuta gmail_auth_url.py")
        sys.exit(1)

    state_data = json.loads(STATE_FILE.read_text())

    if args.code:
        code = args.code.strip()
    else:
        print("=" * 60)
        print("Pega el código de la URL del navegador")
        print("URL: http://localhost:8080/?code=XXXX&state=YYYY")
        print("Copia solo el XXXX")
        print()
        code = input("Código: ").strip()

    if not code:
        print("❌ Código vacío")
        sys.exit(1)

    print()
    print("🔄 Intercambiando código por token...")

    # POST manual al token endpoint
    data = urllib.parse.urlencode({
        'client_id': state_data['client_id'],
        'client_secret': state_data['client_secret'],
        'code': code,
        'code_verifier': state_data['code_verifier'],
        'grant_type': 'authorization_code',
        'redirect_uri': state_data['redirect_uri'],
    }).encode('ascii')

    req = urllib.request.Request(TOKEN_URL, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')

    try:
        with urllib.request.urlopen(req) as resp:
            token_response = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f"❌ Error {e.code}: {body}")
        print()
        print("Posibles causas:")
        print("  - Código expirado (>10 min). Genera URL nueva con gmail_auth_url.py")
        print("  - Código ya usado. Genera URL nueva")
        print("  - redirect_uri no coincide con el de la URL de auth")
        print(f"  - redirect_uri configurado: {state_data['redirect_uri']}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    if 'access_token' not in token_response:
        print(f"❌ Respuesta inesperada: {token_response}")
        sys.exit(1)

    # Formatear como creds (formato google.oauth2.credentials.Credentials)
    expiry = datetime.now(timezone.utc) + timedelta(seconds=token_response.get('expires_in', 3600))
    creds = {
        'access_token': token_response['access_token'],
        'refresh_token': token_response.get('refresh_token'),
        'token_uri': TOKEN_URL,
        'client_id': state_data['client_id'],
        'client_secret': state_data['client_secret'],
        'scopes': state_data['scopes'],
        'type': 'authorized_user',
        'expiry': expiry.isoformat(),
    }

    token_file = state_data['token_file']
    token_path = Path(token_file)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, 'w') as f:
        json.dump(creds, f, indent=2)
    token_path.chmod(0o600)

    STATE_FILE.unlink(missing_ok=True)

    print(f"💾 Token guardado en: {token_path}")
    print()
    print("🎉 Autenticación completada. Puedes ejecutar gmail_collector.py")


if __name__ == '__main__':
    main()
