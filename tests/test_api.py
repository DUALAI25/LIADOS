"""
Tests E2E ligeros (sin navegador) del dashboard v5.1.0.

Verifica todos los endpoints criticos: salud, KPIs, charts, search,
export CSV, drill-down, chat streaming. Sin dependencias externas
(solo requests, ya en requirements).

Uso: python3 tests/test_api.py [host]
"""
import os
import sys
import json
import time
import requests
from requests.auth import HTTPBasicAuth

HOST = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9121"
AUTH = HTTPBasicAuth("jefe", "jefe2026")
TIMEOUT = 10
STREAM_TIMEOUT = 45

PASS = 0
FAIL = 0
ERRORS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  FAIL {name} -- {detail}")


def section(title):
    print(f"\n=== {title} ===")


# ── 1. Salud ────────────────────────────────────────────────────
section("Salud")
r = requests.get(f"{HOST}/api/health", timeout=TIMEOUT)
check("GET /api/health", r.ok and r.json().get("version", "").startswith("5"),
      f"status={r.status_code} body={r.text[:100]}")
check("version 5.x", "5." in r.json().get("version", ""), r.json().get("version"))

# ── 2. KPIs y charts ───────────────────────────────────────────
section("KPIs y charts")
endpoints = [
    ("/api/kpis", "ventas_mes"),
    ("/api/kpis-comparativa", "ventas"),
    ("/api/ventas-por-canal", None),
    ("/api/canal-por-mes", None),
    ("/api/ingresos-por-mes", None),
    ("/api/ingresos-6m", None),
    ("/api/gastos-por-proveedor", None),
    ("/api/gastos-por-categoria", None),
    ("/api/margen-por-mes", None),
    ("/api/facturas-recientes", None),
    ("/api/locales", None),
    ("/api/ventas-por-local", None),
    ("/api/ventas-por-dia?days=30", None),
]
for path, key in endpoints:
    r = requests.get(f"{HOST}{path}", auth=AUTH, timeout=TIMEOUT)
    ok = r.ok
    detail = f"{r.status_code}"
    if ok and key:
        ok = key in r.json()
        detail = f"falta clave '{key}'"
    elif ok and not key:
        detail = f"OK ({len(r.text)}b)"
    check(f"GET {path}", ok, detail)

# ── 3. Búsqueda global ─────────────────────────────────────────
section("Búsqueda global (Capa 6)")
# Usar un proveedor real (top 1) en lugar de un literal hardcodeado.
r = requests.get(f"{HOST}/api/gastos-por-proveedor", auth=AUTH, timeout=TIMEOUT)
top_vendor = r.json()[0]["proveedor"] if r.ok and r.json() else "test"
qword = top_vendor.split()[0]  # primera palabra

r = requests.get(f"{HOST}/api/search?q={requests.utils.quote(qword)}", auth=AUTH, timeout=TIMEOUT)
check(f"GET /api/search?q={qword}", r.ok, f"{r.status_code}")
if r.ok:
    data = r.json()
    check("search.facturas es lista", isinstance(data.get("facturas"), list), str(data)[:100])
    check("search.proveedores es lista", isinstance(data.get("proveedores"), list), str(data)[:100])
    check(f"search '{qword}' encuentra resultados", data.get("total", 0) > 0, f"total={data.get('total')}")

# Verificar tambien que un termino inexistente devuelve 0 (no error)
r = requests.get(f"{HOST}/api/search?q=zzz_no_existe_xyz", auth=AUTH, timeout=TIMEOUT)
check("search termino inexistente -> 0", r.ok and r.json().get("total") == 0,
      f"status={r.status_code} total={r.json().get('total') if r.ok else '?'}")
# Verificar que terminos < 2 chars devuelven 0 sin buscar
r = requests.get(f"{HOST}/api/search?q=a", auth=AUTH, timeout=TIMEOUT)
check("search <2 chars -> vacio", r.ok and r.json().get("total") == 0,
      f"total={r.json().get('total') if r.ok else '?'}")

# ── 4. Drill-down ──────────────────────────────────────────────
section("Drill-down")
# Buscar un proveedor real
r = requests.get(f"{HOST}/api/gastos-por-proveedor", auth=AUTH, timeout=TIMEOUT)
if r.ok and r.json():
    vendor = r.json()[0]["proveedor"]
    r2 = requests.get(
        f"{HOST}/api/proveedor/{requests.utils.quote(vendor)}/facturas",
        auth=AUTH, timeout=TIMEOUT,
    )
    check(f"drill /api/proveedor/{vendor[:20]}", r2.ok, f"{r2.status_code}")
    if r2.ok:
        stats = r2.json().get("stats", {})
        check("drill devuelve stats.total_facturas",
              "total_facturas" in stats, str(stats)[:80])

# ── 5. Export CSV ──────────────────────────────────────────────
section("Export CSV (4 vistas)")
for view in ["proveedores", "categorias", "facturas", "ingresos"]:
    r = requests.get(f"{HOST}/api/export/{view}", auth=AUTH, timeout=TIMEOUT)
    ok = r.ok and "csv" in r.headers.get("content-type", "").lower()
    has_bom = r.content[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM
    check(f"export/{view}", ok, f"status={r.status_code} ct={r.headers.get('content-type','')}")
    check(f"  + BOM UTF-8", has_bom, f"primeros bytes={r.content[:5]!r}")

# ── 6. Chat (sin y con streaming) ──────────────────────────────
section("Chat AI")
r = requests.post(f"{HOST}/api/chat", auth=AUTH, timeout=STREAM_TIMEOUT,
                  json={"message": "Dime hola", "history": []})
check("POST /api/chat", r.ok, f"{r.status_code}")
if r.ok:
    data = r.json()
    check("  reply no vacio", bool(data.get("reply")), data.get("reply", "")[:60])

# Streaming: verificamos que la conexión abre y emite al menos un evento
# en un tiempo razonable. Toleramos latencia del LLM con timeout generoso.
print("  (streaming) probando /api/chat/stream...")
t0 = time.time()
try:
    r = requests.post(f"{HOST}/api/chat/stream", auth=AUTH, timeout=(5, 30),
                      json={"message": "ok", "history": []}, stream=True)
    got_event = False
    got_done = False
    for raw in r.iter_lines(chunk_size=1):
        if not raw:
            continue
        if raw.startswith(b"event:"):
            got_event = True
            if b"done" in raw or b"error" in raw:
                got_done = True
                break
        if time.time() - t0 > 25:
            break
    elapsed = time.time() - t0
    check("  stream conecta", r.status_code == 200, f"status={r.status_code}")
    check("  stream emite eventos", got_event, f"ningun evento en {elapsed:.1f}s")
    check("  stream completa (done o error)", got_done, f"sin terminacion tras {elapsed:.1f}s")
except requests.exceptions.ReadTimeout:
    check("  stream conecta", False, f"ReadTimeout tras {time.time()-t0:.1f}s (LLM lento)")
except Exception as e:
    check("  stream conecta", False, str(e)[:100])

# ── 7. Confirm/cancel endpoints (estructura) ───────────────────
section("Endpoints de confirmacion (estructura)")
r = requests.post(f"{HOST}/api/chat/confirm", auth=AUTH, json={"confirmation_token": "fake"})
check("POST /api/chat/confirm responde (no 404)", r.status_code != 404, f"{r.status_code}")
r = requests.post(f"{HOST}/api/chat/cancel", auth=AUTH, json={"confirmation_token": "fake"})
check("POST /api/chat/cancel responde (no 404)", r.status_code != 404, f"{r.status_code}")

# ── 8. Estatico ────────────────────────────────────────────────
section("Assets estaticos")
for path in ["/static/tokens.css", "/static/app.css", "/static/app.js",
             "/static/fonts/Inter-Variable.woff2",
             "/static/fonts/JetBrainsMono-Variable.woff2"]:
    r = requests.get(f"{HOST}{path}", timeout=TIMEOUT)
    check(f"GET {path}", r.ok and len(r.content) > 100, f"{r.status_code} {len(r.content)}b")

# ── Resumen ─────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"Tests: {PASS + FAIL} | PASS: {PASS} | FAIL: {FAIL}")
if ERRORS:
    print("Errores:")
    for e in ERRORS:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("OK -- todos los tests pasan")
    sys.exit(0)
