"""
gmail_auth_oob.py — OAuth Gmail con flujo OOB (out-of-band) para entornos headless

Uso:
  python3 gmail_auth_oob.py
  # O modo no-interactivo:
  python3 gmail_auth_oob.py --url-only
  python3 gmail_auth_oob.py --code <CODIGO>
"""
import os
import sys
import json
import argparse
from pathlib import Path

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

WORKSPACE = Path(__file__).resolve().parent.parent.parent
ENV_FILE = WORKSPACE / '.env'


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


def get_flow(env):
    creds_file = env.get('GMAIL_CREDENTIALS_FILE', '').strip()
    if not creds_file or not Path(creds_file).exists():
        print(f"❌ Credenciales no encontradas: {creds_file}")
        sys.exit(1)
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_secrets_file(
        str(creds_file),
        scopes=SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url-only', action='store_true',
                        help='Solo imprimir la URL de autorización y salir')
    parser.add_argument('--code', type=str,
                        help='Código de autorización devuelto por Google')
    args = parser.parse_args()

    env = load_env()
    creds_file = env.get('GMAIL_CREDENTIALS_FILE', '').strip()
    token_file = env.get('GMAIL_TOKEN_FILE', '').strip()
    if not token_file:
        token_file = str(WORKSPACE / 'credentials' / 'gmail_token.json')

    flow = get_flow(env)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')

    if args.url_only:
        print(auth_url)
        return

    if not args.code:
        print("=" * 60)
        print("🌐 ABRE ESTA URL EN TU NAVEGADOR:")
        print("=" * 60)
        print()
        print(auth_url)
        print()
        print("=" * 60)
        print()
        print("Pasos:")
        print("  1. Abre la URL en Chrome/Firefox/Safari")
        print("  2. Inicia sesión con la cuenta Gmail del cliente")
        print("  3. Acepta los permisos (Gmail readonly)")
        print("  4. Google te mostrará un código. Cópialo.")
        print()
        code = input("📋 Pega aquí el código: ").strip()
    else:
        code = args.code

    if not code:
        print("❌ No pegaste código. Abortando.")
        sys.exit(1)

    print()
    print("🔄 Intercambiando código por token...")
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        print(f"❌ Error: {e}")
        print("   El código expira rápido. Ejecuta de nuevo y pega el código antes de 60s.")
        sys.exit(1)

    creds = flow.credentials
    token_path = Path(token_file)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, 'w') as f:
        f.write(creds.to_json())

    print(f"✅ Token guardado en: {token_path}")
    print()
    print("🎉 Autenticación completada. Puedes ejecutar gmail_collector.py")


if __name__ == '__main__':
    main()
