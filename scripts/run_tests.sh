#!/bin/bash
# Ejecuta los tests de Liados.
# Uso: ./scripts/run_tests.sh
set -e

cd /root/liados
export PYTHONPATH="agente/scripts:agente/mcp:${PYTHONPATH}"

echo "=== Liados: Ejecutando tests ==="

if .venv/bin/python -m pytest --version >/dev/null 2>&1; then
    .venv/bin/python -m pytest agente/scripts/tests/ -v "$@"
else
    echo "pytest no encontrado, usando unittest..."
    .venv/bin/python -m unittest discover -s agente/scripts/tests/ -v "$@"
fi
