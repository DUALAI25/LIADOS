#!/usr/bin/env bash
# Wrapper para ejecutar los tests E2E del dashboard Liados.
# Uso: bash tests/run_e2e.sh [host] [--include-browser]
#
# Por defecto corre tests/test_api.py (sin navegador, ~5s, valida 41 endpoints).
# Con --include-browser intenta tests/demo_flow.py (requiere playwright + chromium).
set -euo pipefail

cd "$(dirname "$0")/.."
HOST="${1:-http://localhost:9121}"
shift || true

VENV="/root/liados/.venv/bin/python3"
LOG="/var/log/liados-e2e.log"

echo "=== Liados E2E tests ==="
echo "Host: $HOST"
echo "Fecha: $(date -Iseconds)"
echo

# ── Test API (sin navegador) ────────────────────────────────────
echo "--- test_api.py ---"
if $VENV tests/test_api.py "$HOST" 2>&1 | tee -a "$LOG"; then
    echo
    echo "RESULT: PASS"
else
    echo
    echo "RESULT: FAIL"
    exit 1
fi

# ── Test browser (opcional, requiere playwright) ─────────────────
if [[ "${1:-}" == "--include-browser" ]] || [[ "${INCLUDE_BROWSER:-}" == "1" ]]; then
    echo
    echo "--- demo_flow.py (Playwright) ---"
    if $VENV -c "import playwright" 2>/dev/null; then
        $VENV tests/demo_flow.py 2>&1 | tee -a "$LOG"
    else
        echo "  (skipping: playwright no instalado. pip install playwright && playwright install chromium)"
    fi
fi

echo
echo "OK -- tests E2E finalizados"
