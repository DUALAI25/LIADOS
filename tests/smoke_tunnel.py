"""Smoke test for the production deliverable: login page + auth + tunnel."""
import os
import subprocess
import sys
import json
from pathlib import Path

results = []
def test(name, fn):
    try:
        ok, msg = fn()
        results.append((name, ok, msg))
        print(f"{'OK ' if ok else 'FAIL'}  {name}: {msg}")
    except Exception as e:
        results.append((name, False, str(e)))
        print(f"FAIL  {name}: {e}")

def get_url():
    p = Path("/root/liados/data/.current_tunnel_url")
    if p.exists():
        return json.loads(p.read_text())["url"]
    return None

URL = get_url()
if not URL:
    print("ERROR: no tunnel URL found")
    sys.exit(1)

print(f"URL: {URL}\n")

# Test 1: /login is public (200)
def t1():
    r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                        f"{URL}/login", "--max-time", "10"], capture_output=True, text=True)
    return r.stdout == "200", f"got {r.stdout}"
test("/login (public, expect 200)", t1)

# Test 2: /api/health is public (200)
def t2():
    r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                        f"{URL}/api/health", "--max-time", "10"], capture_output=True, text=True)
    return r.stdout == "200", f"got {r.stdout}"
test("/api/health (public, expect 200)", t2)

# Test 3: / without auth = 401
def t3():
    r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                        f"{URL}/", "--max-time", "10"], capture_output=True, text=True)
    return r.stdout == "401", f"got {r.stdout}"
test("/ (no auth, expect 401)", t3)

# Test 4: / with auth = 200
user = os.environ.get("DASHBOARD_USER")
pwd = os.environ.get("DASHBOARD_PASSWORD")
def t4():
    r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                        "-u", f"{user}:{pwd}", f"{URL}/", "--max-time", "10"],
                       capture_output=True, text=True)
    return r.stdout == "200", f"got {r.stdout}"
test("/ (auth, expect 200)", t4)

# Test 5: /api/kpis with auth = 200 + valid JSON
def t5():
    r = subprocess.run(["curl", "-sS", "-u", f"{user}:{pwd}",
                        f"{URL}/api/kpis", "--max-time", "10"], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
        ok = "ventas_mes" in d and "gastos_mes" in d
        return ok, f"keys={list(d.keys())}"
    except Exception:
        return False, "not JSON"
test("/api/kpis (auth, JSON valido)", t5)

# Test 6: /api/kpis without auth = 401
def t6():
    r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                        f"{URL}/api/kpis", "--max-time", "10"], capture_output=True, text=True)
    return r.stdout == "401", f"got {r.stdout}"
test("/api/kpis (no auth, expect 401)", t6)

# Summary
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"\n=== SMOKE TUNNEL ===\nTests: {total} | PASS: {passed} | FAIL: {total-passed}")
sys.exit(0 if passed == total else 1)
