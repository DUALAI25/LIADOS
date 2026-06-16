#!/bin/bash
# Arranca todos los servicios de Liados en orden correcto.
# Uso: ./scripts/start_all.sh
set -e

echo "=== Liados: Iniciando servicios ==="

# 1. PostgreSQL (nativo, debe estar ya activo)
if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
    echo "✓ PostgreSQL OK"
else
    echo "✗ ERROR: PostgreSQL no responde en localhost:5432"
    exit 1
fi

# 2. MinIO Docker
cd /root/liados
if docker compose ps minio 2>/dev/null | grep -q "running"; then
    echo "✓ MinIO ya corría"
else
    docker compose up -d minio
    echo "✓ MinIO iniciado"
fi

# 3. OpenClaw (si hay compose disponible)
if [ -f /root/hostedapps/docker-compose.openclaw.yaml ]; then
    docker compose -f /root/hostedapps/docker-compose.openclaw.yaml up -d
    echo "✓ OpenClaw iniciado"
fi

# 4. Dashboard systemd
systemctl restart liados-dashboard
sleep 2
if systemctl is-active --quiet liados-dashboard; then
    echo "✓ Dashboard iniciado en puerto 9121"
else
    echo "✗ ERROR: dashboard no arrancó. Ver: journalctl -u liados-dashboard -n 50"
    exit 1
fi

echo "=== Liados: Todos los servicios iniciados ==="
