"""
gmail_auth_device.py — OAuth Gmail con Device Code Flow (headless-friendly)

Uso:
  python3 gmail_auth_device.py
  # O paso a paso:
  python3 gmail_auth_device.py --request    # pide código al usuario
  python3 gmail_auth_device.py --code <CODE> # completa el OAuth

Ventajas sobre OOB:
  - Funciona con cualquier tipo de OAuth client (Desktop, Web)
  - No necesita navegador en el servidor
  - No requiere redirect_uri pre-registrado
  - Google's official "devices" flow para TVs/IoT/headless
"""
import os
import sys
import json
import time
import argparse
import urllib.parse
import urllib.request
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
ENV_FILE = WORKSPACE / '.env'

DEVICE_CODE_URL = 'https://oauth2.googleapis.com/device/code'
TOKEN_URL = 'https://oauth2.googleapis.com/token'

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def load_env():
    if not ENV_FILE.exists():
        print(f"❌ No se encuentra {ENV_FILE}")
        sys.exit(1)
    env_vars = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    return env_vars


def get_credentials(env):
    creds_file = env.get('GMAIL_CREDENTIALS_FILE', '').strip()
    if not creds_file or not Path(creds_file).exists():
        print(f"❌ Credenciales no encontradas: {creds_file}")
        sys.exit(1)
    with open(creds_file) as f:
        creds = json.load(f)
    if 'installed' in creds:
        return creds['installed']['client_id'], creds['installed']['client_secret']
    elif 'web' in creds:
        return creds['web']['client_id'], creds['web']['client_secret']
    else:
        print("❌ Formato de credentials.json no reconocido (ni 'installed' ni 'web')")
        sys.exit(1)


def request_device_code(client_id):
    data = urllib.parse.urlencode({
        'client_id': client_id,
        'scope': ' '.join(SCOPES),
    }).encode()
    req = urllib.request.Request(DEVICE_CODE_URL, data=data)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def poll_for_token(client_id, client_secret, device_code, interval, expires_in):
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        data = urllib.parse.urlencode({
            'client_id': client_id,
            'client_secret': client_secret,
            'device_code': device_code,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=data)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())
            err = body.get('error', '')
            if err == 'authorization_pending':
                print('.', end='', flush=True)
                continue
            elif err == 'slow_down':
                interval += 5
                print('(slowing down)', end='', flush=True)
                continue
            elif err == 'expired_token':
                print('\n❌ Código expirado. Ejecuta de nuevo.')
                sys.exit(1)
            elif err == 'access_denied':
                print('\n❌ Acceso denegado por el usuario.')
                sys.exit(1)
            else:
                print(f'\n❌ Error: {body}')
                sys.exit(1)
    print('\n❌ Tiempo agotado. Ejecuta de nuevo.')
    sys.exit(1)


def save_token(token_data, env):
    token_file = env.get('GMAIL_TOKEN_FILE', '').strip()
    if not token_file:
        token_file = str(WORKSPACE / 'credentials' / 'gmail_token.json')

    token_path = Path(token_file)
    token_path.parent.mkdir(parents=True, exist_ok=True)

    from datetime import datetime, timezone, timedelta
    expiry = datetime.now(timezone.utc) + timedelta(seconds=token_data.get('expires_in', 3600))
    creds = {
        'access_token': token_data['access_token'],
        'refresh_token': token_data.get('refresh_token'),
        'token_uri': TOKEN_URL,
        'client_id': env.get('__client_id'),
        'client_secret': env.get('__client_secret'),
        'scopes': SCOPES,
        'type': 'authorized_user',
        'expiry': expiry.isoformat(),
    }
    with open(token_path, 'w') as f:
        json.dump(creds, f, indent=2)

    return token_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', action='store_true',
                        help='Solo pedir el device code e imprimirlo')
    args = parser.parse_args()

    env = load_env()
    client_id, client_secret = get_credentials(env)
    env['__client_id'] = client_id
    env['__client_secret'] = client_secret

    print("=" * 60)
    print("Gmail API — Device Code Flow (headless)")
    print("=" * 60)
    print()

    device = request_device_code(client_id)
    user_code = device['user_code']
    verification_url = device['verification_url']
    device_code = device['device_code']
    interval = device.get('interval', 5)
    expires_in = device.get('expires_in', 1800)

    print("🌐 ABRE ESTA URL EN TU NAVEGADOR:")
    print()
    print(f"   {verification_url}")
    print()
    print("=" * 60)
    print()
    print(f"📋 Y ENTRA ESTE CÓDIGO:  {user_code}")
    print()
    print("=" * 60)
    print()
    print("Pasos:")
    print(f"  1. Abre {verification_url} en tu navegador")
    print("  2. Inicia sesión con la cuenta Gmail del cliente")
    print(f"  3. Cuando pida el código, entra: {user_code}")
    print("  4. Acepta los permisos (Gmail readonly)")
    print()
    print("⏳ Esperando autorización", end='', flush=True)

    token_data = poll_for_token(client_id, client_secret, device_code, interval, expires_in)
    print()
    print()
    print("✅ Token recibido!")

    token_path = save_token(token_data, env)
    print(f"💾 Guardado en: {token_path}")
    print()
    print("🎉 Autenticación completada. Puedes ejecutar gmail_collector.py")


if __name__ == '__main__':
    main()
