#!/bin/bash
# Backfill manual del gmail_collector para una cuenta concreta.
# Fuerza get_last_sync('gmail') = TARGET_DATE para que el collector procese
# correos desde esa fecha. Restaura al final.
#
# Uso:
#   ./scripts/run_backfill.sh                              # principal desde 2026-07-04
#   ./scripts/run_backfill.sh secundaria                   # secundaria desde 2026-07-04
#   ./scripts/run_backfill.sh principal 2026-06-01T00:00:00+00:00

set -e
ACCOUNT="${1:-principal}"
TARGET_DATE="${2:-2026-07-04T00:00:00+00:00}"
cd /root/liados

LOG=/var/log/liados/backfill_${ACCOUNT}_$(date +%Y%m%d_%H%M%S).log
mkdir -p /var/log/liados

set -a
[ -f /root/liados/.env ] && . /root/liados/.env
set +a

echo "TARGET=$TARGET_DATE  TARGET_ACCOUNT=$ACCOUNT" > "$LOG"

/root/liados/.venv/bin/python - >> "$LOG" 2>&1 <<PYEOF
from datetime import datetime
import sys
sys.path.insert(0, "agente/scripts")
from db_connection import get_conn
new_ts = datetime.fromisoformat("$TARGET_DATE".replace('Z','+00:00'))
with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT source, last_sync, status FROM sync_control WHERE source='gmail'")
    print("BEFORE sync_control:", cur.fetchone())
    cur.execute("UPDATE sync_control SET last_sync=%s WHERE source='gmail'", (new_ts,))
    cur.execute("SELECT source, last_sync FROM sync_control WHERE source='gmail'")
    print("AFTER  sync_control:", cur.fetchone())
    conn.commit()
PYEOF

echo "===== Lanzando collector -> $LOG =====" >> "$LOG"
PYTHONPATH="agente/scripts:$PYTHONPATH" /root/liados/.venv/bin/python -m agente.scripts.gmail_collector >> "$LOG" 2>&1
RC=$?

/root/liados/.venv/bin/python - >> "$LOG" 2>&1 <<PYEOF
from datetime import datetime, timezone
import sys
sys.path.insert(0, "agente/scripts")
from db_connection import get_conn
with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("UPDATE sync_control SET last_sync=%s WHERE source='gmail'",
                (datetime.now(timezone.utc),))
    conn.commit()
print("OK: sync_control.last_sync restaurado a now()")
PYEOF

echo "===== Finalizado rc=$RC, log=$LOG ====="
exit $RC
