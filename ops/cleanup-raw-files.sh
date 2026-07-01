#!/bin/bash
# S-1: cleanup raw_files > 90 dias. Cron automatico.
# Liberar espacio manteniendo auditoria razonable.

AGED_DAYS=90
RAW_DIR=/root/liados/data/invoices/raw
LOG=/root/liados/data/cleanup_raw.log

TOTAL_BEFORE=$(du -sb "$RAW_DIR" 2>/dev/null | awk '{print $1}')
COUNT_BEFORE=$(find "$RAW_DIR" -type f 2>/dev/null | wc -l)

echo "=== cleanup started at $(date) ===" >> $LOG
echo "Before: $COUNT_BEFORE files, $TOTAL_BEFORE bytes" >> $LOG

DELETED=$(find "$RAW_DIR" -type f -mtime +$AGED_DAYS -delete -print 2>/dev/null | wc -l)

TOTAL_AFTER=$(du -sb "$RAW_DIR" 2>/dev/null | awk '{print $1}')
COUNT_AFTER=$(find "$RAW_DIR" -type f 2>/dev/null | wc -l)

echo "Deleted: $DELETED files (age > $AGED_DAYS days)" >> $LOG
echo "After: $COUNT_AFTER files, $TOTAL_AFTER bytes" >> $LOG
echo "Saved: $(echo "scale=2; ($TOTAL_BEFORE - $TOTAL_AFTER) / 1024 / 1024" | bc) MB" >> $LOG
echo "=== cleanup finished at $(date) ===" >> $LOG
