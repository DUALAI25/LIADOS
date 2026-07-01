"""
gmail_auth.py — OAuth Gmail con paste-back flow (único y multi-cuenta)

POR QUÉ ESTE MÉTODO:
  - Funciona en servidores remotos (VPS) sin abrir puertos
  - Funciona en local también
  - Compatible con OAuth Web y Desktop de Google Cloud
  - Cero dependencias raras (solo urllib y requests)
  - Ya validado con el paste-back de Google Workspace

USO (multi-cuenta):
  # Primera vez: autoriza la cuenta "principal"
  python3 gmail_auth.py --account principal

  # Primera vez: autoriza la cuenta "secundaria"
  python3 gmail_auth.py --account secundaria

  # Re-autoriza una cuenta que ya tenía token
  python3 gmail_auth.py --account principal --force

FLUJO:
  1. Genera URL de autorización (con PKCE)
  2. Te la imprime → ábrela en tu navegador
  3. Autoriza con la cuenta Gmail correspondiente
  4. Google redirige a redirect_uri con ?code=XXXX
  5. Copia la URL completa de la barra de direcciones
  6. Pégala aquí cuando te la pida
  7. El script canjea el code por tokens y guarda gmail_token_<cuenta>.json
"""
import os
import sys
import json
import argparse
import hashlib
import base64
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Scopes necesarios (solo lectura de Gmail)
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Rutas base
WORKSPACE = Path(__file__).resolve().parent.parent.parent
ENV_FILE = WORKSPACE / '.env'
CREDENTIALS_DIR = WORKSPACE / 'agente' / 'credentials'


def load_env():
    """Carga variables de .env"""
    if not ENV_FILE.exists():
        print(f"❌ No se encuentra {ENV_FILE}")
        print("   Ejecuta: cp .env.example .env y edítalo")
        sys.exit(1)
    env_vars = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    return env_vars


def generate_pkce():
    """Genera code_verifier y code_challenge (PKCE)"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge


def _resolve_path(path_str):
    """Resuelve una ruta de .env: absolutas se usan tal cual, relativas se resuelven contra WORKSPACE."""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    return p


def get_credentials_path(account):
    """Resuelve la ruta del JSON de credenciales OAuth para la cuenta"""
    env = load_env()
    var_name = f'GMAIL_CREDENTIALS_FILE_{account}'
    creds_path = env.get(var_name, '')

    if not creds_path:
        # Fallback: archivo por defecto en agente/credentials/
        default_path = CREDENTIALS_DIR / f'gmail_credentials_{account}.json'
        if default_path.exists():
            return str(default_path)
        print(f"❌ {var_name} no configurado en .env")
        print(f"   Y tampoco existe: {default_path}")
        print()
        print("   Pasos:")
        print("   1. Ve a https://console.cloud.google.com/")
        print("   2. Crea credenciales OAuth (Web o Desktop app)")
        print(f"   3. Guarda el JSON como: {default_path}")
        print(f"   4. Añade a .env: {var_name}={default_path}")
        sys.exit(1)

    creds_path = _resolve_path(creds_path)
    if not creds_path.exists():
        print(f"❌ No se encuentra: {creds_path}")
        sys.exit(1)
    return str(creds_path)


def get_token_path(account):
    """Resuelve la ruta donde guardar/leer el token de la cuenta"""
    env = load_env()
    var_name = f'GMAIL_TOKEN_FILE_{account}'
    token_path = env.get(var_name, '')

    if not token_path:
        # Default: agente/credentials/gmail_token_<cuenta>.json
        default_path = CREDENTIALS_DIR / f'gmail_token_{account}.json'
        default_path.parent.mkdir(parents=True, exist_ok=True)
        return str(default_path)

    token_path = _resolve_path(token_path)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    return str(token_path)


def load_client_config(creds_path):
    """Carga el client_id y client_secret del JSON de credenciales OAuth"""
    with open(creds_path) as f:
        config = json.load(f)

    # Soporta formato "installed" (Desktop) y "web" (Web application)
    if 'installed' in config:
        return config['installed']
    elif 'web' in config:
        return config['web']
    else:
        print("❌ Formato de credenciales no reconocido. Debe ser 'installed' o 'web'.")
        sys.exit(1)


def generate_auth_url(client_id, redirect_uri, code_challenge, state=None):
    """Genera la URL de autorización OAuth con PKCE y state"""
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'access_type': 'offline',
        'prompt': 'consent',  # Forzar refresh_token
    }
    if state:
        params['state'] = state
    base_url = 'https://accounts.google.com/o/oauth2/v2/auth'
    return f"{base_url}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code, client_id, client_secret, redirect_uri, code_verifier):
    """Canjea el authorization code por access_token + refresh_token"""
    token_url = 'https://oauth2.googleapis.com/token'
    data = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
        'code_verifier': code_verifier,
    }

    try:
        req = urllib.request.Request(
            token_url,
            data=urllib.parse.urlencode(data).encode('utf-8'),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"❌ Error HTTP {e.code}: {error_body}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error canjeando code: {e}")
        sys.exit(1)


def extract_code_from_url(url):
    """Extrae el 'code' de una URL completa de callback"""
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    if 'code' not in params:
        print("❌ No se encontró 'code' en la URL pegada.")
        print("   Asegúrate de copiar la URL completa de la barra de direcciones después de autorizar.")
        sys.exit(1)
    return params['code'][0]


def save_token(token_data, token_path, client_id, client_secret, scopes=None):
    """Guarda el token en formato JSON compatible con google-auth"""
    token_info = {
        'access_token': token_data.get('access_token'),
        'refresh_token': token_data.get('refresh_token'),
        'token_type': token_data.get('token_type', 'Bearer'),
        'expires_in': token_data.get('expires_in', 3600),
        'scope': token_data.get('scope', ' '.join(scopes or SCOPES)),
        'client_id': client_id,
        'client_secret': client_secret,
    }
    with open(token_path, 'w') as f:
        json.dump(token_info, f, indent=2)
    return token_info


def authorize_account(account, force=False):
    """Hace OAuth completo para una cuenta"""
    print("=" * 60)
    print(f"🔐 Autorización OAuth Gmail — cuenta: {account}")
    print("=" * 60)
    print()

    creds_path = get_credentials_path(account)
    token_path = get_token_path(account)

    # Si ya hay token y no es --force, salir
    if Path(token_path).exists() and not force:
        print(f"✅ Ya existe token para '{account}': {token_path}")
        print(f"   Usa --force para re-autorizar.")
        return

    client_config = load_client_config(creds_path)
    client_id = client_config['client_id']
    client_secret = client_config['client_secret']

    # Determinar redirect_uri
    # Para Web: usar http://localhost
    # Para Desktop: usar http://localhost con puerto (Google lo inyecta)
    redirect_uris = client_config.get('redirect_uris', [])
    if 'http://localhost' in redirect_uris:
        redirect_uri = 'http://localhost'
    elif redirect_uris:
        redirect_uri = redirect_uris[0]
    else:
        # Desktop app siempre tiene http://localhost preconfigurado
        redirect_uri = 'http://localhost'

    # Generar PKCE
    code_verifier, code_challenge = generate_pkce()

    # Generar state (anti-CSRF)
    oauth_state = secrets.token_urlsafe(32)

    # Generar URL
    auth_url = generate_auth_url(client_id, redirect_uri, code_challenge, state=oauth_state)

    print("📋 PASOS:")
    print(f"   1. Abre esta URL en tu navegador (con la cuenta Gmail de '{account}'):")
    print()
    print(f"      {auth_url}")
    print()
    print(f"   2. Autoriza el acceso a Gmail.")
    print(f"   3. Google te redirigirá a una URL que empieza por '{redirect_uri}'")
    print(f"      (puede dar error de 'sitio no alcanza' — IGNORALO, es normal)")
    print(f"   4. Copia la URL COMPLETA de la barra de direcciones.")
    print(f"   5. Pégala aquí cuando te la pida.")
    print()

    # Leer URL pegada
    callback_url = input("🔗 Pega aquí la URL de callback: ").strip()
    if not callback_url:
        print("❌ No pegaste ninguna URL. Cancelando.")
        sys.exit(1)

    # Extraer code y validar state
    code = extract_code_from_url(callback_url)
    callback_state = extract_state_from_url(callback_url)
    if callback_state and callback_state != oauth_state:
        print("❌ ERROR: state de OAuth no coincide (posible ataque CSRF). Cancelando.")
        sys.exit(1)
    if callback_state:
        print("✅ State OAuth validado correctamente.")

    # Canjear code por tokens
    print()
    print("🔄 Canjeando code por tokens...")
    token_data = exchange_code_for_tokens(
        code, client_id, client_secret, redirect_uri, code_verifier
    )

    # Guardar
    save_token(token_data, token_path, client_id, client_secret)

    print()
    print(f"✅ Token guardado en: {token_path}")
    print()
    print(f"🎉 Cuenta '{account}' autorizada. Ya puedes usar gmail_collector.py")


def list_accounts():
    """Lista las cuentas configuradas en .env"""
    env = load_env()
    accounts = env.get('GMAIL_ACCOUNTS', '').split(',')
    accounts = [a.strip() for a in accounts if a.strip()]

    if not accounts:
        print("❌ GMAIL_ACCOUNTS no configurado en .env")
        print("   Añade una línea: GMAIL_ACCOUNTS=cuenta1,cuenta2")
        return

    print("=" * 60)
    print("📧 Cuentas Gmail configuradas")
    print("=" * 60)
    for acc in accounts:
        token_path = get_token_path(acc)
        if Path(token_path).exists():
            print(f"  ✅ {acc:20s} → token OK ({token_path})")
        else:
            print(f"  ❌ {acc:20s} → NO AUTORIZADA (ejecuta: python3 gmail_auth.py --account {acc})")


def main():
    parser = argparse.ArgumentParser(description='OAuth Gmail paste-back multi-cuenta')
    parser.add_argument('--account', help='Nombre de la cuenta a autorizar (ej: principal, secundaria)')
    parser.add_argument('--list', action='store_true', help='Lista las cuentas configuradas y su estado')
    parser.add_argument('--force', action='store_true', help='Re-autorizar aunque ya exista token')
    args = parser.parse_args()

    if args.list:
        list_accounts()
    elif args.account:
        authorize_account(args.account, force=args.force)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
