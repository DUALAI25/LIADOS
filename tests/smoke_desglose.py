"""
Smoke test del módulo desglose con datos REALES del VPS.

Ejecutar manualmente:
    A_PASS=... /root/liados/.venv/bin/python /tmp/feat-desglose-2026-07-12/tests/smoke_desglose.py
"""
import os
import sys
sys.path.insert(0, "/tmp/feat-desglose-2026-07-12/dashboard")

import psycopg2
from psycopg2.extras import RealDictCursor
from desglose import build_desglose

p = os.environ.get("A_PASS")
if not p:
    sys.exit("A_PASS no está")

conn = psycopg2.connect(host="localhost", dbname="desliado", user="desliado", password=p)
cur = conn.cursor(cursor_factory=RealDictCursor)

# Traer TODAS las facturas expense reales
cur.execute("""
    SELECT vendor_name, category_raw, source_account, status,
           invoice_date, total_amount
    FROM invoices
    WHERE type='expense' AND status != 'rejected' AND is_invoice = true
      AND COALESCE(category_raw, '') NOT IN ('nomina','administrativo','basura')
""")
rows = [dict(r) for r in cur.fetchall()]
print(f"Filas cargadas: {len(rows)}")

# Smoke 1: Total por categoria
print("\n=== SMOKE 1: sum por category ===")
out = build_desglose(rows, ["category"], "sum")
print(f"  grupos: {out['rows_count']}")
print(f"  total: {out['total']['value']:.2f}€ ({out['total']['count']} facturas)")
print("  top 5:")
for r in out["rows"][:5]:
    print(f"    {r['category']:30s} {r['value']:>10.2f}€  ({r['count']} facs)")

# Smoke 2: cuenta x mes
print("\n=== SMOKE 2: sum por cuenta x mes ===")
out = build_desglose(rows, ["cuenta", "month"], "sum")
print(f"  grupos: {out['rows_count']}")
for r in out["rows"][:8]:
    print(f"    {r['cuenta']:15s} {r['month']:10s} {r['value']:>10.2f}€  ({r['count']} facs)")

# Smoke 3: count por vendor
print("\n=== SMOKE 3: count por vendor (top 10) ===")
out = build_desglose(rows, ["vendor"], "count")
print(f"  vendors únicos: {out['rows_count']}")
for r in out["rows"][:10]:
    print(f"    {r['vendor'] or '<NULL>':40s} {r['count']:4d} facs")

# Smoke 4: avg por categoria x quarter
print("\n=== SMOKE 4: avg por categoria x quarter ===")
out = build_desglose(rows, ["category", "quarter"], "avg")
print(f"  grupos: {out['rows_count']}")
for r in out["rows"][:5]:
    print(f"    {r['category']:25s} {r['quarter']:10s} avg={r['value']:>8.2f}€  ({r['count']} facs)")

print("\n=== TODOS LOS SMOKES OK ===")