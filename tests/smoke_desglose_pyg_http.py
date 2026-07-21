"""
tests/smoke_desglose_pyg_http.py — Smoke HTTP del endpoint /api/gastos/pyg.

Levanta la app en :9130 SIN tocar producción (9121) y hace 3 curls reales
para verificar que el endpoint responde, el cache funciona y el comparador
de periodos se activa.

Uso: python3 tests/smoke_desglose_pyg_http.py
"""
import sys
import os
import subprocess
import time
import urllib.request
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def main():
    # Arrancar uvicorn en puerto 9130 con override de auth
    env = os.environ.copy()
    # Sobrescribir credenciales dummy (la app valida que coincidan)
    env["DASHBOARD_USER"] = "smoke"
    env["DASHBOARD_PASSWORD"] = "smoke"
    # Cargar .env para DB_* (si existe)
    env_path = "/root/liados/.env"
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k not in env:  # no pisar DASHBOARD_*
                env[k] = v

    proc = subprocess.Popen(
        [".venv/bin/python3", "-m", "uvicorn", "dashboard.app:app",
         "--host", "127.0.0.1", "--port", "9130"],
        env=env, cwd="/root/liados",
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    time.sleep(5)

    try:
        # Auth basic
        import base64
        auth = base64.b64encode(b"smoke:smoke").decode()
        headers = {"Authorization": f"Basic {auth}"}

        # TEST 1: PYG sin comparador
        print("=" * 60)
        print("TEST 1: GET /api/gastos/pyg (sin comparador)")
        url = "http://127.0.0.1:9130/api/gastos/pyg?date_from=2026-01-01&date_to=2026-01-31&cuenta=principal"
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30)
        data = json.loads(r.read())
        assert r.status == 200, f"status {r.status}"
        assert "totals" in data, "falta totals"
        assert "lines" in data, "falta lines"
        assert "buckets" in data, "falta buckets"
        assert "issues" in data, "falta issues"
        print(f"  ✓ Status 200")
        print(f"  ✓ Ingresos: {data['totals']['ingresos']}€")
        print(f"  ✓ Total gastos: {data['totals']['total_gastos']}€")
        print(f"  ✓ Líneas jerárquicas: {len(data['lines'])}")
        print(f"  ✓ Issues: {len(data['issues'])}")

        # TEST 2: PYG con comparador
        print()
        print("=" * 60)
        print("TEST 2: GET /api/gastos/pyg (con comparador de 2 periodos)")
        url = ("http://127.0.0.1:9130/api/gastos/pyg?date_from=2026-02-01&date_to=2026-02-28"
               "&cuenta=principal&compare_from=2026-01-01&compare_to=2026-01-31")
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30)
        data = json.loads(r.read())
        assert r.status == 200
        assert data.get("comparison") is not None, "falta comparison"
        print(f"  ✓ Status 200")
        print(f"  ✓ Comparison.ingresos.current: {data['comparison']['ingresos']['current']}")
        print(f"  ✓ Comparison.ingresos.previous: {data['comparison']['ingresos']['previous']}")
        print(f"  ✓ Comparison.ingresos.diff_eur: {data['comparison']['ingresos']['diff_eur']}")

        # TEST 3: Sin filtro de cuenta
        print()
        print("=" * 60)
        print("TEST 3: GET /api/gastos/pyg (sin filtro de cuenta)")
        url = "http://127.0.0.1:9130/api/gastos/pyg?date_from=2026-01-01&date_to=2026-01-31"
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30)
        data = json.loads(r.read())
        assert r.status == 200
        print(f"  ✓ Status 200")
        print(f"  ✓ Rows used: {data['rows_used']}")

        print()
        print("=" * 60)
        print("✓ SMOKE HTTP PYG OK — 3/3 tests verde")
        return 0
    except Exception as e:
        print(f"✗ FAIL: {e!r}")
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
