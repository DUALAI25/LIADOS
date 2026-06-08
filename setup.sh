#!/bin/bash
set -euo pipefail

echo "=== Desliado — Fase 0: Setup ==="

# 1. Copiar .env si no existe
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[OK] .env creado desde .env.example — edítalo con tus credenciales"
fi

# 2. Levantar PostgreSQL + MinIO
echo "[...] Levantando contenedores..."
docker compose up -d
echo "[OK] Contenedores en marcha"

# 3. Esperar a que PostgreSQL esté listo
echo "[...] Esperando a PostgreSQL..."
until docker exec desliado-db pg_isready -U desliado -d desliado > /dev/null 2>&1; do
    sleep 2
done
echo "[OK] PostgreSQL listo"

# 4. Esperar a que MinIO esté listo
echo "[...] Esperando a MinIO..."
until docker exec desliado-minio curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; do
    sleep 2
done
echo "[OK] MinIO listo"

# 5. Verificar schema
echo "[...] Verificando schema..."
docker exec desliado-db psql -U desliado -d desliado -c '\dt' > /dev/null 2>&1
echo "[OK] Tablas creadas"

# 6. Crear bucket en MinIO
echo "[...] Creando bucket invoices en MinIO..."
docker exec desliado-minio mc alias set local http://localhost:9000 minioadmin "${MINIO_SECRET_KEY:-minio_pass_2026}" 2>/dev/null || true
docker exec desliado-minio mc mb local/invoices 2>/dev/null || true
echo "[OK] Bucket invoices listo"

# 7. Instalar dependencias Python
echo "[...] Instalando dependencias Python..."
pip install -r agente/requirements.txt -q
echo "[OK] Dependencias instaladas"

echo ""
echo "=== Fase 0 completada ==="
echo "PostgreSQL: localhost:5432"
echo "MinIO API:  localhost:9000"
echo "MinIO Consola: http://localhost:9001"
echo ""
echo "Próximo paso: editar .env con tus credenciales y ejecutar:"
echo "  python3 agente/scripts/gmail_collector.py"
