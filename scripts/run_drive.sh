#!/bin/bash
# Wrapper para ejecutar drive_collector.py como tarea cron.
# Loguea a /var/log/liados-drive.log (rotado por drive_collector.py).
#
# v2 (2026-07-13): creado para watchdog + cron incremental.

set -e
cd /root/liados

LOG=/var/log/liados-drive.log

# Cargar .env para que DRIVE_FOLDER_ID_* y GMAIL_ACCOUNTS esten disponibles
if [ -f /root/liados/.env ]; then
    set -a
    # shellcheck disable=SC1091
    . /root/liados/.env
    set +a
fi

echo "=== drive_collector started at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> $LOG
PYTHONPATH="agente/scripts:$PYTHONPATH" /root/liados/.venv/bin/python -m agente.scripts.drive_collector --once >> $LOG 2>&1
RC=$?
echo "=== drive_collector finished at $(date -u +%Y-%m-%dT%H:%M:%SZ) with rc=$RC ===" >> $LOG

exit $RC