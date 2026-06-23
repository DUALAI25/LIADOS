"""
backfill_invoice_dates.py — Migración idempotente para rellenar invoice_date NULL

Fuentes de backfill (en orden de prioridad):
  1. parsed_json['invoice_date'] cuando db.invoice_date IS NULL
  2. Filename YYYY-MM-DD / YYYY_MM_DD / YYYYMMDD extraído de raw_file_url o local_path

Idempotente: UPDATE ... WHERE invoice_date IS NULL no se re-aplica.
Log de cada fila actualizada con id, vendor, fecha_antes, fecha_despues, fuente.

Ejecutar:
    python3 agente/scripts/backfill_invoice_dates.py [--dry-run]
"""
import os
import sys
import json
import re
import argparse
from datetime import date
from pathlib import Path

# Cargar .env
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import psycopg2

DATE_RE1 = re.compile(r"((?:20|19)\d{2})[-_/](\d{1,2})[-_/](\d{1,2})(?:[T_\s]|$)")
DATE_RE2 = re.compile(r"\b((?:20|19)\d{2})(\d{2})(\d{2})\b")


def extract_date_from_filename(target: str):
    """Extrae fecha (date) del filename. None si no hay match válido."""
    if not target:
        return None
    m = DATE_RE1.search(target) or DATE_RE2.search(target)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (2018 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31):
            return None
        return date(y, mo, d)
    except (ValueError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(
        host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("""
        SELECT id, vendor_name, parsed_json::text, raw_file_url
        FROM invoices
        WHERE invoice_date IS NULL
    """)

    updates = []
    no_source = []
    for pid, vendor, ptext, url in cur.fetchall():
        pdate = None
        local = None
        if ptext:
            try:
                p = json.loads(ptext)
                pdate = p.get("invoice_date")
                local = p.get("local_path")
            except Exception:
                pass
        if pdate:
            updates.append((pid, vendor, pdate, "parsed_json"))
            continue
        target = url or local or ""
        fecha = extract_date_from_filename(target)
        if fecha:
            updates.append((pid, vendor, fecha, "filename"))
        else:
            no_source.append((pid[:8], vendor, url or local))

    print(f"=== Backfill de invoice_date ===")
    print(f"Candidatas a backfill: {len(updates)}")
    print(f"Sin fuente: {len(no_source)}")
    if no_source:
        print(f"\n--- Sin fuente (revisar manualmente) ---")
        for pid, vendor, target in no_source:
            print(f"  {pid} {vendor or '(no vendor)':30s} -> {target or '(no url)'}")

    if not updates:
        print("\nNada que actualizar.")
        return

    print(f"\n--- Detalle de updates ---")
    for pid, vendor, fecha, fuente in updates:
        print(f"  {pid[:8]} {vendor or '(no vendor)':30s} -> {fecha} (de {fuente})")

    if args.dry_run:
        print("\n--dry-run: no se aplicaron cambios.")
        return

    print(f"\nAplicando {len(updates)} updates...")
    sql = "UPDATE invoices SET invoice_date = %s WHERE id = %s AND invoice_date IS NULL"
    for pid, vendor, fecha, fuente in updates:
        cur.execute(sql, (fecha, pid))
    conn.commit()

    # Verificación post
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE invoice_date IS NULL) AS sin_fecha,
            COUNT(*) FILTER (WHERE invoice_date IS NOT NULL) AS con_fecha
        FROM invoices
    """)
    sin, con = cur.fetchone()
    print(f"\nPost-backfill: {con} con fecha, {sin} sin fecha (de 468 totales)")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()