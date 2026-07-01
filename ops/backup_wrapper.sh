#!/bin/bash
set -e
cd /root/liados
# Read password from .env - use grep with pattern matching only
PSWD_VAR=$(grep "^DB_PASSWORD=" .env | head -1 | cut -d= -f2)
export PGPASSWORD="$PSWD_VAR"
/usr/bin/pg_dump -h localhost -U desliado -d desliado --exclude-table=_pre_limpieza_20260622 2>/dev/null | gzip > /root/liados/backups/db-$(date +%Y%m%d-%H%M).sql.gz
echo "BACKUP OK $(date)"
