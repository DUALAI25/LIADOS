"""
smoke_desglose_pyg.py — Smoke test del motor PYG con datos reales de la BD.

v1 (2026-07-21): ejecuta build_pyg() contra los datos reales de Liados,
verifica que el P&L se construye sin errores y que las claves críticas
están presentes.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Cargar variables de entorno desde .env (necesario para psycopg2)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
except Exception:
    pass

from datetime import date, timedelta
from dashboard.desglose_pyg import build_pyg, cross_check_subcat
from dashboard.desglose_pyg_rules import load_rules


def fetch_invoices_for_period(date_from: str, date_to: str, cuenta: str | None = None):
    """Query directa a la BD (sin pasar por la app FastAPI)."""
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "desliado"),
        user=os.getenv("DB_USER", "desliado"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = """
        SELECT
          i.invoice_date::text as invoice_date,
          i.vendor_name as vendor_name,
          COALESCE(c.name, i.category_raw) as category_raw,
          i.source_account as source_account,
          i.total_amount as total_amount,
          i.status as status
        FROM invoices i
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE i.invoice_date >= %s AND i.invoice_date <= %s
          """ + (" AND i.source_account = %s" if cuenta else "") + """
          AND i.status != 'void'
        ORDER BY i.invoice_date
        LIMIT 20000
    """
    pp = [date_from, date_to] + ([cuenta] if cuenta else [])
    cur.execute(sql, tuple(pp))
    rows = [dict(r) for r in cur.fetchall()]

    # Last.app es la fuente de ingresos del PYG; total_cents -> euros.
    if cuenta is None or cuenta.lower() == "principal":
        cur.execute("""
            SELECT COALESCE(finalizing_time, creation_time)::date::text as invoice_date,
                   'Last.app' as vendor_name,
                   CASE WHEN total_cents < 0 THEN 'Devoluciones' ELSE 'Ventas' END as category_raw,
                   'principal' as source_account,
                   ABS(total_cents)::numeric / 100.0 as total_amount,
                   'classified' as status
            FROM lastapp_bills
            WHERE deleted = false
              AND COALESCE(finalizing_time, creation_time)::date >= %s
              AND COALESCE(finalizing_time, creation_time)::date <= %s
        """, (date_from, date_to))
        rows.extend(dict(r) for r in cur.fetchall())
    cur.close()
    conn.close()
    return rows


def main():
    rules = load_rules()

    # Periodo: último mes con datos
    today = date.today()
    d_to = today
    d_from = today - timedelta(days=30)

    print("=" * 60)
    print(f"SMOKE TEST PYG: {d_from} → {d_to}, cuenta=principal")
    rows = fetch_invoices_for_period(d_from.isoformat(), d_to.isoformat(), cuenta="principal")
    print(f"Rows fetched: {len(rows)}")

    if not rows:
        print("No hay datos. Probando enero 2026...")
        rows = fetch_invoices_for_period("2026-01-01", "2026-01-31", cuenta="principal")
        print(f"Rows fetched (enero 2026): {len(rows)}")
        d_from = date(2026, 1, 1)
        d_to = date(2026, 1, 31)

    pyg = build_pyg(
        rows, d_from.isoformat(), d_to.isoformat(),
        cuenta="principal", rules=rules
    )

    # Validar claves críticas
    assert "totals" in pyg, "falta totals"
    assert "lines" in pyg, "falta lines"
    assert "buckets" in pyg, "falta buckets"
    assert "drilldown" in pyg, "falta drilldown"
    assert "issues" in pyg, "falta issues"

    t = pyg["totals"]
    print(f"  Ingresos: {t['ingresos']:.2f}€")
    print(f"  Total gastos: {t['total_gastos']:.2f}€")
    print(f"  Margen bruto: {t['margen_bruto']:.2f}€ ({t['margen_bruto_pct']*100:.1f}%)")
    print(f"  MC: {t['mc']:.2f}€ ({t['mc_pct']*100:.1f}%)")
    print(f"  EBITDA: {t['ebitda']:.2f}€ ({t['ebitda_pct']*100:.1f}%)")
    print(f"  Food cost buckets: {pyg['buckets'].get('aprovisionamientos', 0):.2f}€")

    print(f"\n  Issues detectados: {len(pyg['issues'])}")
    for iss in pyg["issues"]:
        print(f"    [{iss['level'].upper()}] {iss['message']}")

    print(f"\n  Líneas (jerarquía): {len(pyg['lines'])}")
    for line in pyg["lines"][:15]:
        ind = "  " * line["level"]
        print(f"  {ind}{line['kind']:8s} {line['label']:50s} {line['value']:>10.2f}")

    # Cross-check
    print()
    print("=" * 60)
    print("CROSS-CHECK (sin datos de venta):")
    cc = cross_check_subcat(pyg)
    for r in cc:
        print(f"  {r['subcat']:15s} gasto={r['gasto_real']:.2f}€ target_margin={r.get('target_margin', 'N/A')} status={r['status']}")

    print()
    print("=" * 60)
    print("✓ SMOKE PYG OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
