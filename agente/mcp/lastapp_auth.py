"""
Gestión de tokens OAuth para el MCP remoto de Last.app.

Lee credenciales de .env:
  - LASTAPP_OAUTH_CLIENT_ID
  - LASTAPP_OAUTH_CLIENT_SECRET
  - LASTAPP_OAUTH_BEARER_TOKEN (modo directo, alternativa al flujo OAuth)
  - LASTAPP_OAUTH_TOKEN_URL (opcional, default https://api.last.app/mcp/token)
  - LASTAPP_OAUTH_AUTHORIZE_URL (opcional, default https://api.last.app/mcp/authorize)
  - LASTAPP_OAUTH_SCOPE (opcional, default mcp:read mcp:write)
  - LASTAPP_OAUTH_REDIRECT_URI (opcional, default http://localhost:9999/callback)

El servidor Last.app MCP soporta grant_type=authorization_code (NO client_credentials).

Modos de autenticación (por orden de prioridad):
  1. LASTAPP_OAUTH_BEARER_TOKEN: token Bearer directo, listo para usar
  2. LASTAPP_OAUTH_CLIENT_ID + LASTAPP_OAUTH_CLIENT_SECRET: flujo OAuth authorization_code

Funciones:
  - get_token() -> str: devuelve token válido, refresca si está a <60s de expirar
  - _discover_oauth_config() -> dict: parsea /.well-known/oauth-protected-resource/mcp
  - _request_token() -> dict: obtiene token via authorization_code
  - _refresh_token() -> str: intenta refrescar con refresh_token si disponible
"""
import os
import sys
import time
import logging
import urllib.parse
import webbrowser
import requests
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

MCP_BASE = "https://api.last.app/mcp"
TOKEN_URL = os.getenv("LASTAPP_OAUTH_TOKEN_URL", f"{MCP_BASE}/token")
AUTHORIZE_URL = os.getenv("LASTAPP_OAUTH_AUTHORIZE_URL", f"{MCP_BASE}/authorize")
SCOPE = os.getenv("LASTAPP_OAUTH_SCOPE", "mcp:read mcp:write")
REDIRECT_URI = os.getenv("LASTAPP_OAUTH_REDIRECT_URI", "http://localhost:9999/callback")
WELL_KNOWN_URL = "https://api.last.app/.well-known/oauth-protected-resource/mcp"

_token_store = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": 0,
}


def get_token(force_refresh: bool = False) -> str:
    """
    Devuelve un token Bearer válido para el MCP de Last.app.

    Modos de autenticación detectados automáticamente:
      1. LASTAPP_OAUTH_BEARER_TOKEN en .env -> uso directo
      2. LASTAPP_OAUTH_CLIENT_ID + LASTAPP_OAUTH_CLIENT_SECRET -> flujo OAuth

    Raises:
        RuntimeError: si no hay credenciales configuradas
    """
    direct_token = os.getenv("LASTAPP_OAUTH_BEARER_TOKEN")
    if direct_token:
        return direct_token

    now = time.time()
    if not force_refresh and _token_store["access_token"] and now < _token_store["expires_at"] - 60:
        return _token_store["access_token"]

    if _token_store["refresh_token"]:
        try:
            logger.info("Intentando refrescar token OAuth...")
            return _refresh_token()
        except Exception:
            logger.warning("Refresh fallido, haciendo auth desde cero")

    client_id = os.getenv("LASTAPP_OAUTH_CLIENT_ID")
    client_secret = os.getenv("LASTAPP_OAUTH_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError(
            "Configura OAuth siguiendo el README, sección 'Last.app MCP setup'.\n"
            "Necesitas definir en .env: LASTAPP_OAUTH_CLIENT_ID y LASTAPP_OAUTH_CLIENT_SECRET\n"
            "  o alternativamente LASTAPP_OAUTH_BEARER_TOKEN (token directo).\n"
            "Obtén las credenciales en admin.last.app > Integraciones > MCP.\n"
            "Doc: https://www.last.app/actualizaciones-de-producto/last-app-mcp-conecta-tu-ia-con-tu-restaurante"
        )

    return _request_token(client_id, client_secret)


def _request_token(client_id: str, client_secret: str) -> str:
    """
    Flujo OAuth authorization_code.

    1. Genera URL de autorización
    2. Instruye al usuario a visitarla (stderr si no hay TTY, stdout si sí)
    3. Espera el callback local en localhost:9999/callback
    4. Intercambia code por token

    Para automatización no interactiva, usa LASTAPP_OAUTH_BEARER_TOKEN.
    """
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
    })
    auth_url = f"{AUTHORIZE_URL}?{params}"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Autenticación OAuth Last.app MCP", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"\n  1. Abre esta URL en tu navegador:", file=sys.stderr)
    print(f"     {auth_url}", file=sys.stderr)
    print(f"\n  2. Inicia sesión y autoriza la aplicación", file=sys.stderr)
    print(f"\n  3. El navegador redirigirá a {REDIRECT_URI}", file=sys.stderr)
    print(f"\n  Esperando callback...", file=sys.stderr)

    auth_code = None

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/callback":
                if "code" in qs:
                    auth_code = qs["code"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<html><body><h1>Autorizado</h1><p>Puedes cerrar esta ventana.</p></body></html>")
                elif "error" in qs:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(f"<html><body><h1>Error</h1><p>{qs.get('error',['desconocido'])[0]}</p></body></html>".encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    try:
        parsed_redirect = urllib.parse.urlparse(REDIRECT_URI)
        host = parsed_redirect.hostname or "localhost"
        port = parsed_redirect.port or 9999
    except Exception:
        host = "localhost"
        port = 9999

    server = HTTPServer((host, port), CallbackHandler)
    server.timeout = 120

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    deadline = time.time() + 120
    while auth_code is None:
        if time.time() > deadline:
            raise RuntimeError(
                "OAuth callback no recibido en 120s. "
                "Aborta el flujo y revisa que la URL de authorize se haya abierto correctamente."
            )
        server.handle_request()

    print(f"  Código de autorización recibido. Intercambiando por token...", file=sys.stderr)

    exchange_resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )

    if not exchange_resp.ok:
        raise RuntimeError(
            f"Error al intercambiar código OAuth: {exchange_resp.status_code} {exchange_resp.text}"
        )

    data = exchange_resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError(f"Respuesta OAuth sin access_token: {data}")

    _token_store["access_token"] = access_token
    _token_store["refresh_token"] = data.get("refresh_token")
    _token_store["expires_at"] = time.time() + data.get("expires_in", 3600) - 60

    print(f"  Token obtenido correctamente.", file=sys.stderr)
    return access_token


def _refresh_token() -> str:
    if not _token_store.get("refresh_token"):
        raise RuntimeError("No hay refresh_token disponible")
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": _token_store["refresh_token"],
            "client_id": os.getenv("LASTAPP_OAUTH_CLIENT_ID", ""),
            "client_secret": os.getenv("LASTAPP_OAUTH_CLIENT_SECRET", ""),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Error refrescando token: {resp.status_code} {resp.text}")
    data = resp.json()
    _token_store["access_token"] = data["access_token"]
    _token_store["refresh_token"] = data.get("refresh_token", _token_store["refresh_token"])
    _token_store["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    return _token_store["access_token"]


def _discover_oauth_config() -> dict:
    """Parse el endpoint .well-known/oauth-protected-resource/mcp."""
    resp = requests.get(WELL_KNOWN_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()
