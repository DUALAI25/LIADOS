#!/bin/bash
# Wrapper para ejecutar run_all.py todos los dias a las 6 AM.
# Loguea a /root/liados/data/run_all.log, rota si pasa de 10MB.

set -e
cd /root/liados

LOG=/root/liados/data/run_all.log
mkdir -p $(dirname $LOG)

# Rotar si > 10MB
if [ -f "$LOG" ] && [ $(stat -c%s "$LOG" 2>/dev/null || echo 0) -gt 10485760 ]; then
    mv "$LOG" "$LOG.$(date +%Y%m%d-%H%M%S).old"
fi

echo "=== run_all.py started at $(date) ===" >> $LOG
PYTHONPATH="agente/scripts:$PYTHONPATH" .venv/bin/python -m agente.scripts.run_all >> $LOG 2>&1
RC=$?
echo "=== run_all.py finished at $(date) with exit code $RC ===" >> $LOG

# Si falla, notificar al sistema
if [ $RC -ne 0 ]; then
    logger -t liados-run-all "ERROR: run_all.py exited with code $RC, ver $LOG"
fi

exit $RC
