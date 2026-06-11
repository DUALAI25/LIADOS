"""
Cliente JSON-RPC para https://api.last.app/mcp

Implementa el subconjunto mínimo del protocolo MCP que necesitamos:
  - initialize (handshake)
  - tools/list (descubrir tools disponibles)
  - tools/call (invocar tool)
  - resources/list y resources/read (para KB/soporte)

Usa requests con timeout 10s y reintentos (3 intentos, backoff exponencial 1s/2s/4s).
Si el servidor responde 401, fuerza refresh del token y reintenta UNA vez.
"""
import time
import logging
import requests

logger = logging.getLogger(__name__)

MCP_URL = "https://api.last.app/mcp"
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1


class LastAppClient:
    def __init__(self, auth_token_getter=None):
        self._auth_token_getter = auth_token_getter
        self._session_id = None
        self._server_capabilities = None
        self._server_info = None
        self._request_id = 0

    def _next_id(self):
        self._request_id += 1
        return self._request_id

    def _rpc(self, method: str, params: dict = None, retry_on_401: bool = True) -> dict:
        url = MCP_URL
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_id(),
        }
        headers = {"Content-Type": "application/json"}

        if method not in ("initialize",) and self._auth_token_getter:
            try:
                token = self._auth_token_getter()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
            except Exception as e:
                logger.warning("No se pudo obtener token OAuth: %s", e)

        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 401 and retry_on_401 and self._auth_token_getter:
                    if attempt == 0:
                        logger.info("401 recibido, refrescando token y reintentando...")
                        try:
                            self._auth_token_getter()
                            headers["Authorization"] = f"Bearer {self._auth_token_getter()}"
                            resp = requests.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
                        except Exception:
                            pass
                        if resp.status_code != 401:
                            return self._parse_response(resp)
                resp.raise_for_status()
                return self._parse_response(resp)
            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt < MAX_RETRIES - 1:
                    backoff = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("Intento %d/%d fallido (%s), reintentando en %ds...",
                                   attempt + 1, MAX_RETRIES, e, backoff)
                    time.sleep(backoff)
                else:
                    raise RuntimeError(f"Fallo tras {MAX_RETRIES} intentos a {method}: {last_exc}")

        raise RuntimeError(f"Fallo tras {MAX_RETRIES} intentos a {method}: {last_exc}")

    @staticmethod
    def _parse_response(resp: requests.Response) -> dict:
        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"JSON-RPC error {err.get('code', '?')}: {err.get('message', str(err))}")
        if "result" not in data:
            raise RuntimeError(f"Respuesta JSON-RPC sin 'result': {data}")
        return data["result"]

    def initialize(self) -> dict:
        """Handshake con el servidor MCP remoto."""
        result = self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "liados-proxy", "version": "1.0.0"},
        })
        self._server_capabilities = result.get("capabilities", {})
        self._server_info = result.get("serverInfo", {})
        logger.info("Handshake MCP OK. Server: %s v%s (capabilities: %s)",
                     self._server_info.get("name", "?"),
                     self._server_info.get("version", "?"),
                     ", ".join(k for k, v in self._server_capabilities.items() if v))
        self._rpc("notifications/initialized", {}, retry_on_401=False)
        return result

    def discover_tools(self) -> list:
        """tools/list: descubre las tools disponibles en el servidor remoto."""
        result = self._rpc("tools/list")
        tools = result.get("tools", [])
        logger.info("Descubiertas %d tools del MCP remoto: %s",
                     len(tools),
                     ", ".join(t.get("name", "?") for t in tools))
        return tools

    def discover_resources(self) -> list:
        """resources/list: descubre recursos (KB, docs) disponibles."""
        result = self._rpc("resources/list")
        resources = result.get("resources", [])
        logger.info("Descubiertos %d recursos del MCP remoto", len(resources))
        return resources

    def call_tool(self, tool_name: str, arguments: dict = None) -> dict:
        """tools/call: invoca una tool del MCP remoto."""
        params = {"name": tool_name}
        if arguments:
            params["arguments"] = arguments
        return self._rpc("tools/call", params)

    def read_resource(self, resource_uri: str) -> dict:
        """resources/read: lee un recurso de la KB."""
        return self._rpc("resources/read", {"uri": resource_uri})

    @property
    def capabilities(self) -> dict:
        return self._server_capabilities or {}

    @property
    def server_info(self) -> dict:
        return self._server_info or {}

    def ping(self) -> bool:
        try:
            self._rpc("ping", {}, retry_on_401=False)
            return True
        except Exception:
            return False
