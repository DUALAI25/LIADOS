#!/usr/bin/env bash
# Wrapper para ejecutar los tests E2E del dashboard Liados.
# Uso: bash tests/run_e2e.sh [host] [--include-browser]
#
# 2026-08-20: ampliado para incluir tests de cuenta_resultados y desglose_pyg
# (v1 + v2) — el cron E2E solo cubría test_api.py y dejó pasar una regresión
# en marketplace_legal_names durante 15h. Ahora se cubren todas las suites
# unitarias de reglas PyG + build/periods/reconciliation + API + browser.
#
# Suites de pytest (sin navegador, rápidas, ~3s total):
#   - test_cuenta_resultados.py  (clasificación de facturas, marketplace vendors)
#   - test_desglose_pyg.py      (TestClassification TestCompatibilidad)
#   - test_desglose_pyg_v2.py    (TestCasosReales TestIntegridadSistema)
#   - test_build_pyg_canonical.py
#   - test_pyg_periods.py
#   - test_pyg_reconciliation.py
#
# Tests con HTTP (requieren dashboard arriba):
#   - test_api.py (sin navegador, valida 41 endpoints)
#
# Browser (opcional, requiere playwright + chromium):
#   - demo_flow.py
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

# ── Suites pytest unitarias (sin red, rápidas) ───────────────────
PYTEST_SUITES=(
    "tests/test_cuenta_resultados.py"
    "tests/test_desglose_pyg.py"
    "tests/test_desglose_pyg_v2.py"
    "tests/test_build_pyg_canonical.py"
    "tests/test_pyg_periods.py"
    "tests/test_pyg_reconciliation.py"
)

for suite in "${PYTEST_SUITES[@]}"; do
    if [ -f "$suite" ]; then
        echo "--- pytest $suite ---"
        if $VENV -m pytest "$suite" --no-header -q 2>&1 | tee -a "$LOG"; then
            echo
        else
            echo
            echo "RESULT: FAIL (pytest $suite)"
            exit 1
        fi
    else
        echo "--- pytest $suite (skip: no existe) ---"
    fi
done

# ── Test API (sin navegador, requiere HTTPS dashboard) ──────────
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
