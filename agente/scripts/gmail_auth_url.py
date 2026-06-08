"""
gmail_auth_url.py — Genera URL OAuth manualmente (sin bug de requests_oauthlib)

El bug: requests_oauthlib incluye code_verifier en la URL cuando se le pasa
como param a authorization_url(), causando que Google rechace con
"redirect_uri_mismatch" y un puerto random.

Solución: construir la URL a mano con solo code_challenge (sin code_verifier).
El code_verifier se guarda en /tmp y se usa en la fase 2 (POST manual).
"""
import os
import sys
import json
import secrets
import hashlib
import base64
from pathlib import Path
from urllib.parse import urlencode

WORKSPACE = Path(__file__).resolve().parent.parent.parent
ENV_FILE = WORKSPACE / '.env'
STATE_FILE = Path('/tmp/gmail_oauth_state.json')

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
REDIRECT_URI = 'http://localhost:8080/'


def load_env():
    env = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    env[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():
        env[k] = v
    return env


def make_pkce():
    """Genera code_verifier y code_challenge (S256) según RFC 7636."""
    # verifier: 43-128 chars de [A-Z][a-z][0-9]-.~
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode('ascii').rstrip('=')
    # challenge: SHA256(verifier) en base64url sin padding
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('ascii')).digest()
    ).decode('ascii').rstrip('=')
    return code_verifier, challenge


def main():
    env = load_env()
    creds_file = env.get('GMAIL_CREDENTIALS_FILE', '').strip()
    token_file = env.get('GMAIL_TOKEN_FILE', '').strip()
    if not token_file:
        token_file = str(WORKSPACE / 'credentials' / 'gmail_token.json')

    if not creds_file or not Path(creds_file).exists():
        print(f"❌ Credenciales no encontradas: {creds_file}")
        sys.exit(1)

    with open(creds_file) as f:
        creds = json.load(f)
    if 'installed' in creds:
        client_id = creds['installed']['client_id']
        client_secret = creds['installed']['client_secret']
    elif 'web' in creds:
        client_id = creds['web']['client_id']
        client_secret = creds['web']['client_secret']
    else:
        print("❌ Formato de credentials.json no reconocido")
        sys.exit(1)

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = make_pkce()

    # Construir URL manualmente (SIN code_verifier — solo code_challenge)
    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': REDIRECT_URI,
        'scope': ' '.join(SCOPES),
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'access_type': 'offline',
        'prompt': 'consent',
    }
    auth_url = 'https://accounts.google.com/o/oauth2/auth?' + urlencode(params)

    state_data = {
        'state': state,
        'code_verifier': code_verifier,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': REDIRECT_URI,
        'scopes': SCOPES,
        'token_file': token_file,
    }
    STATE_FILE.write_text(json.dumps(state_data, indent=2))
    STATE_FILE.chmod(0o600)

    print("=" * 70)
    print("🌐 ABRE ESTA URL EN TU NAVEGADOR:")
    print("=" * 70)
    print()
    print(auth_url)
    print()
    print("=" * 70)
    print()
    print("Pasos:")
    print("  1. Abre la URL en tu navegador (Chrome, Firefox, Safari)")
    print("  2. Inicia sesión con la cuenta Gmail del cliente")
    print("  3. Acepta los permisos (Gmail readonly)")
    print("  4. Google te redirigirá a http://localhost:8080/?code=XXXX&state=YYYY")
    print("  5. El navegador mostrará 'no se puede conectar' — ESTO ES NORMAL")
    print("  6. Copia el valor de 'code' de la barra de URL (lo que va después de code=)")
    print()
    print("=" * 70)
    print(f"📋 Cuando tengas el código, pásamelo y completo el OAuth")
    print()
    print(f"🔐 State+verifier guardados en: {STATE_FILE}")
    print(f"⏰ La URL expira en ~10 minutos.")


if __name__ == '__main__':
    main()
