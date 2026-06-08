"""
setup_gmail_auth.py — Configura la autenticación OAuth de Gmail

Uso:
  1. Ir a https://console.cloud.google.com/
  2. Crear proyecto → habilitar Gmail API
  3. Crear credenciales → OAuth 2.0 → Aplicación de escritorio
  4. Descargar JSON y guardarlo como credentials/gmail_credentials.json
  5. Ejecutar: python3 scripts/setup_gmail_auth.py
  6. Se abrirá el navegador para autorizar → se guardará gmail_token.json
"""
import os
import json
import sys
from pathlib import Path

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Buscar .env en el workspace
WORKSPACE = Path(__file__).resolve().parent.parent.parent  # scripts/ → agente/ → workspace root
ENV_FILE = WORKSPACE / '.env'
CREDENTIALS_DIR = WORKSPACE / 'credentials'


def load_env():
    """Carga variables de .env"""
    if not ENV_FILE.exists():
        print(f"❌ No se encuentra {ENV_FILE}")
        print("   Ejecuta: cp .env.example .env y edítalo")
        return {}

    env_vars = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    return env_vars


def main():
    print("=" * 60)
    print("Configuración de Gmail API — OAuth 2.0")
    print("=" * 60)
    print()

    env = load_env()
    creds_file = env.get('GMAIL_CREDENTIALS_FILE', '')

    if not creds_file:
        # Buscar en directorio credentials/
        CREDENTIALS_DIR.mkdir(exist_ok=True)
        default_path = str(CREDENTIALS_DIR / 'gmail_credentials.json')
        print("📋 GMAIL_CREDENTIALS_FILE no está configurado en .env")
        print()
        print("Para obtener las credenciales:")
        print("  1. Ve a https://console.cloud.google.com/")
        print("  2. Crea un proyecto nuevo")
        print("  3. Habilita Gmail API (Biblioteca → buscar 'Gmail API' → Habilitar)")
        print("  4. Ve a 'Crear credenciales' → 'OAuth 2.0 Client ID'")
        print("  5. Tipo de aplicación: 'Aplicación de escritorio'")
        print("  6. Descarga el JSON y guárdalo en:")
        print(f"     {default_path}")
        print()

        # Comprobar si ya existe
        if Path(default_path).exists():
            print(f"✅ Ya existe: {default_path}")
            creds_file = default_path
        else:
            print(f"❌ No se encuentra: {default_path}")
            print()
            print(f"   Descarga el JSON de Google Cloud Console y guárdalo como:")
            print(f"   {default_path}")
            print()
            print(f"   Luego actualiza .env:")
            print(f"   GMAIL_CREDENTIALS_FILE={default_path}")
            print(f"   GMAIL_TOKEN_FILE={CREDENTIALS_DIR / 'gmail_token.json'}")
            sys.exit(1)
    else:
        creds_path = Path(creds_file).expanduser()
        if not creds_path.exists():
            print(f"❌ No se encuentra: {creds_path}")
            print(f"   Revisa GMAIL_CREDENTIALS_FILE en {ENV_FILE}")
            sys.exit(1)
        print(f"✅ Credenciales encontradas: {creds_path}")

    print()
    print("🔄 Iniciando flujo OAuth...")
    print("   Se abrirá un navegador para autorizar el acceso a Gmail.")
    print("   Asegúrate de usar la cuenta de Gmail del cliente.")
    print()

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    # Guardar token
    token_path = env.get('GMAIL_TOKEN_FILE', str(CREDENTIALS_DIR / 'gmail_token.json'))
    token_path = Path(token_path).expanduser()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    with open(token_path, 'w') as f:
        f.write(creds.to_json())

    print(f"✅ Token guardado en: {token_path}")
    print()
    print("📌 NO OLVIDES actualizar .env con:")
    if not env.get('GMAIL_CREDENTIALS_FILE'):
        print(f"   GMAIL_CREDENTIALS_FILE={creds_path}")
    if not env.get('GMAIL_TOKEN_FILE'):
        print(f"   GMAIL_TOKEN_FILE={token_path}")
    print()
    print("🎉 Autenticación completada. Puedes ejecutar gmail_collector.py")


if __name__ == '__main__':
    main()
