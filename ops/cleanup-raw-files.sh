#!/bin/bash
set -u
AGED_DAYS="${AGED_DAYS:-90}"
DRY_RUN="${CLEANUP_DRY_RUN:-0}"
RAW_DIR=/root/liados/data/invoices/raw
LOG=/root/liados/data/cleanup_raw.log
ENV_FILE=/root/liados/.env
if [ ! -d "$RAW_DIR" ]; then echo "WARN: RAW_DIR $RAW_DIR no existe" >&2; exit 1; fi
PSWD_VAR=$(grep '^DB_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2-)
export PGPASSWORD="$PSWD_VAR"
PROTECTED=$(mktemp)
trap 'rm -f "$PROTECTED"' EXIT
if ! /usr/bin/psql -h localhost -U desliado -d desliado -At -F '' -c "SELECT raw_file_url FROM invoices WHERE raw_file_url LIKE '/root/liados/data/invoices/raw/%' UNION SELECT parsed_json->>'local_path' FROM invoices WHERE parsed_json->>'local_path' LIKE '/root/liados/data/invoices/raw/%';" > "$PROTECTED" 2>/dev/null; then
  echo "ERROR: no se pudo obtener la lista de raw protegidos" >&2; exit 1
fi
TOTAL_BEFORE=$(du -sb "$RAW_DIR" 2>/dev/null | cut -f1)
COUNT_BEFORE=$(find "$RAW_DIR" -type f 2>/dev/null | wc -l)
printf '=== cleanup started at %s ===\n' "$(date)" >> "$LOG"
printf 'Before: %s files, %s bytes; protected: %s paths\n' "$COUNT_BEFORE" "$TOTAL_BEFORE" "$(wc -l < "$PROTECTED")" >> "$LOG"
DELETED=0; SKIPPED=0; CANDIDATES=0
while IFS= read -r -d '' file; do
  CANDIDATES=$((CANDIDATES + 1))
  if grep -Fqx "$file" "$PROTECTED"; then SKIPPED=$((SKIPPED + 1)); continue; fi
  if [ "$DRY_RUN" = "1" ]; then printf 'DRY-RUN delete candidate: %s\n' "$file" >> "$LOG"; else rm -f -- "$file"; DELETED=$((DELETED + 1)); fi
done < <(find "$RAW_DIR" -type f -mtime +"$AGED_DAYS" -print0 2>/dev/null)
TOTAL_AFTER=$(du -sb "$RAW_DIR" 2>/dev/null | cut -f1)
COUNT_AFTER=$(find "$RAW_DIR" -type f 2>/dev/null | wc -l)
SAVED_BYTES=$((TOTAL_BEFORE - TOTAL_AFTER)); SAVED_MB=$((SAVED_BYTES / 1024 / 1024))
printf 'Candidates: %s; deleted: %s; protected/skipped: %s; dry_run: %s\n' "$CANDIDATES" "$DELETED" "$SKIPPED" "$DRY_RUN" >> "$LOG"
printf 'After: %s files, %s bytes; saved: %s MB (%s bytes)\n' "$COUNT_AFTER" "$TOTAL_AFTER" "$SAVED_MB" "$SAVED_BYTES" >> "$LOG"
printf '=== cleanup finished at %s ===\n' "$(date)" >> "$LOG"
