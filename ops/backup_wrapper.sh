#!/bin/bash
# A-6 backup wrapper: lee .env y ejecuta pg_dump
cd /root/liados
PW=$(awk -F= '/^DB_PASSWORD=*** $2; exit}' .env)
export PGPASSWORD=*** 
/usr/bin/pg_dump -h localhost -U desliado -d desliado --exclude-table=_pre_limpieza_20260622 2>/dev/null | gzip > /root/liados/backups/db-$(date +%Y%m%d-%H%M).sql.gz
echo "Backup done: $(ls -la /root/liados/backups/db-$(date +%Y%m%d-)*.sql.gz 2>/dev/null | tail -1)"