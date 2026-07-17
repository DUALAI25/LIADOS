#!/bin/bash
# S-1: cleanup raw_files > 90 dias. Cron automatico.
# Liberar espacio manteniendo auditoria razonable.
# Hardening 2026-07-17: reemplazo `bc` por aritmética bash pura + agrego
# cleanup_raw.log al logrotate para que no se pierda el historial.

set -u
AGED_DAYS=90
RAW_DIR=/root/liados/data/invoices/raw
LOG=/root/liados/data/cleanup_raw.log

TOTAL_BEFORE=$(du -sb "$RAW_DIR" 2>/dev/null | awk '{print $1}')
COUNT_BEFORE=$(find "$RAW_DIR" -type f 2>/dev/null | wc -l)

echo "=== cleanup started at $(date) ===" >> "$LOG"
echo "Before: $COUNT_BEFORE files, $TOTAL_BEFORE bytes" >> "$LOG"

DELETED=$(find "$RAW_DIR" -type f -mtime +$AGED_DAYS -delete -print 2>/dev/null | wc -l)

TOTAL_AFTER=$(du -sb "$RAW_DIR" 2>/dev/null | awk '{print $1}')
COUNT_AFTER=$(find "$RAW_DIR" -type f 2>/dev/null | wc -l)

# Saved sin `bc`: aritmética entera bash + conversión a MB
SAVED_BYTES=$((TOTAL_BEFORE - TOTAL_AFTER))
SAVED_MB=$((SAVED_BYTES / 1024 / 1024))

echo "Deleted: $DELETED files (age > $AGED_DAYS days)" >> "$LOG"
echo "After: $COUNT_AFTER files, $TOTAL_AFTER bytes" >> "$LOG"
echo "Saved: ${SAVED_MB} MB (${SAVED_BYTES} bytes)" >> "$LOG"
echo "=== cleanup finished at $(date) ===" >> "$LOG"

# exit 0 siempre que el find haya funcionado; si RAW_DIR no existe, alertar
if [ ! -d "$RAW_DIR" ]; then
    echo "WARN: RAW_DIR $RAW_DIR no existe" >&2
    exit 1
fi
exit 0
