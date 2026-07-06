#!/bin/bash
# Backfill manual del gmail_collector para una cuenta concreta.
# Fuerza get_last_sync('gmail:<account>') = TARGET_DATE para que el collector
# procese correos desde esa fecha. Restaura al final.
#
# Uso:
#   ./scripts/run_backfill.sh                              # principal desde 2026-07-04
#   ./scripts/run_backfill.sh secundaria                   # secundaria desde 2026-07-04
#   ./scripts/run_backfill.sh principal 2026-06-01T00:00:00+00:00
#   DRY_RUN=1 ./scripts/run_backfill.sh principal          # solo lista, no parsea, no DB
#
# v2 (B2): acepta DRY_RUN=1, valida TARGET_DATE y registra audit log con
# source='gmail:backfill:<account>' para cada ejecucion real.

set -e
ACCOUNT="${1:-principal}"
TARGET_DATE="${2:-2026-07-04T00:00:00+00:00}"
DRY_RUN="${DRY_RUN:-0}"

cd /root/liados
LOG=/var/log/liados/backfill_${ACCOUNT}_$(date +%Y%m%d_%H%M%S).log
mkdir -p /var/log/liados

# Carga .env
set -a
[ -f /root/liados/.env ] && . /root/liados/.env
set +a

# B2: Validacion de TARGET_DATE (futuro o > 365d -> exit 4)
python3 - <<EOF
from datetime import datetime, timezone, timedelta
import sys
ts = datetime.fromisoformat("${TARGET_DATE}".replace('Z','+00:00'))
now = datetime.now(timezone.utc)
if ts > now:
    print("ERROR: TARGET_DATE en el futuro ({})".format(ts), file=sys.stderr)
    sys.exit(4)
if (now - ts) > timedelta(days=365):
    print("ERROR: TARGET_DATE > 365 dias atras ({})".format(ts), file=sys.stderr)
    sys.exit(4)
EOF
RC=$?
if [ "$RC" -ne 0 ]; then exit $RC; fi

echo "TARGET=${TARGET_DATE}  TARGET_ACCOUNT=${ACCOUNT}  DRY_RUN=${DRY_RUN}" > "$LOG"

# SIEMPRE ajustar sync_control para que la query use la fecha objetivo
# (tanto en DRY_RUN como en real; al final restauramos).
/root/liados/.venv/bin/python - >> "$LOG" 2>&1 <<EOF
from datetime import datetime
import sys
sys.path.insert(0, "agente/scripts")
from db_connection import get_conn
new_ts = datetime.fromisoformat("${TARGET_DATE}".replace('Z','+00:00'))
with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT source, last_sync, status FROM sync_control WHERE source='gmail:${ACCOUNT}'")
    print("BEFORE sync_control:", cur.fetchone())
    cur.execute("UPDATE sync_control SET last_sync=%s WHERE source='gmail:${ACCOUNT}'", (new_ts,))
    cur.execute("SELECT source, last_sync FROM sync_control WHERE source='gmail:${ACCOUNT}'")
    print("AFTER  sync_control:", cur.fetchone())
    conn.commit()
EOF

echo "===== Lanzando collector (DRY_RUN=${DRY_RUN}) -> ${LOG} =====" >> "$LOG"
if [ "$DRY_RUN" = "1" ]; then
    PYTHONPATH="agente/scripts:${PYTHONPATH}" /root/liados/.venv/bin/python -m agente.scripts.gmail_collector --account "${ACCOUNT}" --dry-run >> "$LOG" 2>&1
else
    PYTHONPATH="agente/scripts:${PYTHONPATH}" /root/liados/.venv/bin/python -m agente.scripts.gmail_collector --account "${ACCOUNT}" >> "$LOG" 2>&1
fi
RC=$?

# Restaurar last_sync SIEMPRE (dry-run o real). Audit log solo en real.
if [ "$DRY_RUN" = "1" ]; then
    /root/liados/.venv/bin/python - >> "$LOG" 2>&1 <<EOF
from datetime import datetime, timezone
import sys
sys.path.insert(0, "agente/scripts")
from db_connection import get_conn
with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("UPDATE sync_control SET last_sync=%s WHERE source='gmail:${ACCOUNT}'",
                (datetime.now(timezone.utc),))
    conn.commit()
print("OK: sync_control.last_sync restaurado a now() (DRY_RUN, sin audit)")
EOF
else
    /root/liados/.venv/bin/python - >> "$LOG" 2>&1 <<EOF
from datetime import datetime, timezone
import sys
sys.path.insert(0, "agente/scripts")
from db_connection import get_conn
with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("UPDATE sync_control SET last_sync=%s WHERE source='gmail:${ACCOUNT}'",
                (datetime.now(timezone.utc),))
    conn.commit()
print("OK: sync_control.last_sync restaurado a now()")

# B2: Audit log del backfill (idempotente por source unico)
RC_VAL = $RC
with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sync_control (source, last_sync, status, items_processed, errors)
        VALUES (%s, NOW(), %s, %s, %s)
        ON CONFLICT (source) DO UPDATE SET
            last_sync = NOW(),
            status = EXCLUDED.status,
            items_processed = sync_control.items_processed + EXCLUDED.items_processed,
            errors = sync_control.errors + EXCLUDED.errors
    """, ('gmail:backfill:${ACCOUNT}', 'ok' if RC_VAL == 0 else 'error', 0, 0 if RC_VAL == 0 else 1))
    conn.commit()
print("OK: audit log en gmail:backfill:${ACCOUNT}")
EOF
fi

echo "===== Finalizado rc=${RC}, log=${LOG} ====="
exit $RC
