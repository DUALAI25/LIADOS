#!/usr/bin/env python3
"""Proxy HTTP→HTTPS local para Tailscale Funnel.

Escucha en 9122 (HTTP plain) y forward a 9121 (HTTPS self-signed).
Permite que Tailscale Funnel haga proxy HTTP sin pelearse con el
certificado self-signed del dashboard.

Seguridad: solo escucha en 127.0.0.1 (no expuesto fuera del VPS).
El TLS verification se desactiva SOLO porque la app usa cert
self-signed interno; el tráfico externo siempre va por HTTPS
vía Tailscale Funnel.
"""
import http.server
import urllib.request
import urllib.error
import ssl
import socketserver


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self): self._proxy("GET")
    def do_POST(self): self._proxy("POST")
    def do_PUT(self): self._proxy("PUT")
    def do_DELETE(self): self._proxy("DELETE")
    def do_PATCH(self): self._proxy("PATCH")
    def do_HEAD(self): self._proxy("HEAD")
    def do_OPTIONS(self): self._proxy("OPTIONS")

    def _proxy(self, method):
        url = f"https://localhost:9121{self.path}"
        body = None
        if "Content-Length" in self.headers:
            length = int(self.headers["Content-Length"])
            body = self.rfile.read(length)
        req = urllib.request.Request(url, data=body, method=method)
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length"):
                req.add_header(k, v)
        # Self-signed cert interno del dashboard; no MITM posible porque
        # solo escucha en 127.0.0.1 y el tráfico externo va cifrado por Tailscale.
        ctx = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                payload = resp.read()
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(k, v)
            payload = e.read()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            self.send_error(502, str(e))

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    PORT = 9122
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), ProxyHandler) as httpd:
        httpd.allow_reuse_address = True
        print(f"HTTP→HTTPS proxy listening on 127.0.0.1:{PORT} → localhost:9121", flush=True)
        httpd.serve_forever()
