"""
gmail_auth_local.py — OAuth Gmail con local server (headless-compatible)

Uso:
  python3 gmail_auth_local.py

El script:
  1. Lee GMAIL_CREDENTIALS_FILE del .env
  2. Genera URL de autorización (redirect_uri=http://localhost:8080/)
  3. Imprime la URL — ábrela en tu navegador
  4. Inicia un servidor local en localhost:8080 que recibe el callback
  5. Cuando autorizas, Google redirige a localhost:8080/?code=XXXX
  6. El script captura el código y guarda el token

Requisitos:
  - OAuth client tipo "Desktop" (default) o "Web application" con
    http://localhost:8080/ en redirect_uris autorizados
  - El host debe tener acceso a localhost:8080 (sí, dentro del container)
  - El navegador del usuario debe poder alcanzar el container
    (en este caso, lo más simple es ejecutar el script en el host,
    no en el container)
"""
import os
import sys
import json
import threading
import webbrowser
import argparse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

WORKSPACE = Path(__file__).resolve().parent.parent.parent
ENV_FILE = WORKSPACE / '.env'

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
REDIRECT_URI = 'http://localhost:8080/'
PORT = 8080

_captured_code = None
_captured_state = None
_captured_error = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _captured_code, _captured_state, _captured_error
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        _captured_code = qs.get('code', [None])[0]
        _captured_state = qs.get('state', [None])[0]
        _captured_error = qs.get('error', [None])[0]
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        if _captured_error:
            html = f'<h1>❌ Error: {_captured_error}</h1><p>Cierra esta ventana y revisa los logs.</p>'
        else:
            html = '<h1>✅ Autorización recibida</h1><p>Puedes cerrar esta ventana y volver a la terminal.</p>'
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


def load_env():
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    env_vars[key.strip()] = val.strip().strip('"').strip("'")
    for k, v in os.environ.items():
        env_vars[k] = v
    return env_vars


def get_credentials_path(env):
    creds_file = env.get('GMAIL_CREDENTIALS_FILE', '').strip()
    if not creds_file or not Path(creds_file).exists():
        print(f"❌ Credenciales no encontradas: {creds_file}")
        sys.exit(1)
    return creds_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true',
                        help='No intentar abrir el navegador (headless)')
    args = parser.parse_args()

    env = load_env()
    creds_path = get_credentials_path(env)
    token_file = env.get('GMAIL_TOKEN_FILE', '').strip()
    if not token_file:
        token_file = str(WORKSPACE / 'credentials' / 'gmail_token.json')

    print("=" * 60)
    print("Gmail API — OAuth Local Server Flow (headless-friendly)")
    print("=" * 60)
    print()

    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        str(creds_path),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    auth_url, state = flow.authorization_url(
        prompt='consent',
        access_type='offline',
        include_granted_scopes='true'
    )

    print("🌐 ABRE ESTA URL EN TU NAVEGADOR:")
    print()
    print(f"   {auth_url}")
    print()
    print("=" * 60)
    print()
    print(f"🔌 Iniciando servidor local en {REDIRECT_URI}")
    print("   (esperando el callback de Google...)")
    print()

    if not args.no_browser:
        try:
            webbrowser.open(auth_url)
            print("   (intentando abrir navegador automáticamente...)")
        except Exception:
            print("   (no se pudo abrir navegador, ábrelo manualmente)")

    server = HTTPServer(('localhost', PORT), _CallbackHandler)
    print(f"⏳ Esperando callback en http://localhost:{PORT}/ ...", flush=True)

    while True:
        server.handle_request()
        if _captured_error:
            print(f"\n❌ Error de Google: {_captured_error}")
            sys.exit(1)
        if _captured_code:
            if _captured_state != state:
                print(f"\n❌ State mismatch (CSRF protection). Abortando.")
                sys.exit(1)
            break

    print()
    print("✅ Callback recibido, intercambiando código por token...")
    try:
        flow.fetch_token(code=_captured_code)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    creds = flow.credentials
    token_path = Path(token_file)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, 'w') as f:
        f.write(creds.to_json())

    print(f"💾 Token guardado en: {token_path}")
    print()
    print("🎉 Autenticación completada. Puedes ejecutar gmail_collector.py")


if __name__ == '__main__':
    main()
