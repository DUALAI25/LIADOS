#!/bin/bash
# Health check rápido de Liados. Sale con 0 si todo OK, 1 si falla algo.
# Uso: ./scripts/healthcheck.sh

ERRORS=0

echo "=== Liados Health Check ==="

# PostgreSQL
if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
    echo "✓ PostgreSQL"
else
    echo "✗ PostgreSQL"
    ERRORS=$((ERRORS + 1))
fi

# Dashboard
if curl -sf -o /dev/null -u "${DASHBOARD_USER:-jefe}:${DASHBOARD_PASSWORD:-jefe2026}" http://localhost:9121/api/kpis; then
    echo "✓ Dashboard (puerto 9121)"
else
    echo "✗ Dashboard (puerto 9121)"
    ERRORS=$((ERRORS + 1))
fi

# MinIO
if curl -sf -o /dev/null http://localhost:9000/minio/health/live; then
    echo "✓ MinIO (puerto 9000)"
else
    echo "✗ MinIO (puerto 9000)"
    ERRORS=$((ERRORS + 1))
fi

# OpenClaw
if [ "$(docker inspect -f '{{.State.Status}}' openclaw 2>/dev/null)" = "running" ]; then
    echo "✓ OpenClaw container"
else
    echo "✗ OpenClaw container"
    ERRORS=$((ERRORS + 1))
fi

echo "=============================="
if [ $ERRORS -eq 0 ]; then
    echo "Todo OK"
    exit 0
else
    echo "Fallos detectados: $ERRORS"
    exit 1
fi
