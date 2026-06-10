"""
invoices_server.py — MCP server de solo-lectura para facturas

Tools expuestas:
  - list_invoices: lista facturas con filtros
  - get_invoice: detalle de una factura
  - monthly_summary: resumen mensual (ingresos vs gastos)
  - vendor_summary: top proveedores por gasto
  - pending_payments: facturas sin pagar
  - count_invoices: cuenta rápida con criterios

Todas las queries son SELECT. La DB user es read-only (desliado_ro).
"""
import os
import sys
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("invoices")


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "desliado-db"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "desliado"),
        user=os.getenv("DB_USER", "desliado_ro"),
        password=os.getenv("DB_PASSWORD") or os.getenv("DESLIADO_RO_PASSWORD"),
        connect_timeout=5,
    )


def query(sql: str, params: tuple = ()):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


@mcp.tool()
def list_invoices(
    type: str = "all",
    status: str = "all",
    vendor_name: str = "",
    category: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 20,
) -> str:
    """
    Lista facturas con filtros opcionales.

    Args:
        type: 'expense', 'income' o 'all'
        status: 'pending', 'processed', 'paid', 'failed', 'duplicate' o 'all'
        vendor_name: parte del nombre del proveedor (case-insensitive)
        category: nombre exacto de la categoría
        date_from: fecha inicio (YYYY-MM-DD)
        date_to: fecha fin (YYYY-MM-DD)
        limit: máximo de resultados (default 20, max 100)
    """
    where = []
    params = []
    if type != "all":
        where.append("i.type = %s")
        params.append(type)
    if status != "all":
        where.append("i.status = %s")
        params.append(status)
    if vendor_name:
        where.append("v.name ILIKE %s")
        params.append(f"%{vendor_name}%")
    if category:
        where.append("c.name = %s")
        params.append(category)
    if date_from:
        where.append("i.invoice_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("i.invoice_date <= %s")
        params.append(date_to)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    sql = f"""
        SELECT
            i.id,
            i.invoice_number,
            i.invoice_date,
            i.due_date,
            i.type,
            i.status,
            v.name AS vendor,
            c.name AS category,
            i.total_amount,
            i.currency,
            i.confidence_score
        FROM invoices i
        LEFT JOIN vendors v ON v.id = i.vendor_id
        LEFT JOIN categories c ON c.id = i.category_id
        {where_sql}
        ORDER BY i.invoice_date DESC NULLS LAST
        LIMIT %s
    """
    params.append(min(limit, 100))
    rows = query(sql, tuple(params))
    return json.dumps([dict(r) for r in rows], indent=2, default=str)


@mcp.tool()
def get_invoice(identifier: str) -> str:
    """
    Devuelve el detalle de una factura por ID (UUID) o número de factura.

    Args:
        identifier: UUID o número de factura (invoice_number)
    """
    if "-" in identifier and len(identifier) > 30:
        sql = "SELECT * FROM invoices WHERE id = %s"
        params = (identifier,)
    else:
        sql = "SELECT * FROM invoices WHERE invoice_number = %s LIMIT 1"
        params = (identifier,)

    rows = query(sql, params)
    if not rows:
        return json.dumps({"error": f"Factura '{identifier}' no encontrada"})

    inv = dict(rows[0])
    # Enriquecer con vendor y categoría
    enrich = query(
        """
        SELECT v.name AS vendor, v.tax_id, c.name AS category
        FROM invoices i
        LEFT JOIN vendors v ON v.id = i.vendor_id
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE i.id = %s
        """,
        (inv["id"],),
    )
    if enrich:
        inv.update(dict(enrich[0]))
    return json.dumps(inv, indent=2, default=str)


@mcp.tool()
def monthly_summary(year: int = 0, type: str = "all") -> str:
    """
    Resumen mensual de facturas.

    Args:
        year: año (0 = año actual)
        type: 'expense', 'income' o 'all' (ambos)
    """
    if year == 0:
        year_sql = "EXTRACT(YEAR FROM CURRENT_DATE)"
    else:
        year_sql = str(year)

    where_extra = ""
    params = []
    if type != "all":
        where_extra = "AND type = %s"
        params.append(type)

    sql = f"""
        SELECT
            EXTRACT(YEAR FROM invoice_date)::int AS year,
            EXTRACT(MONTH FROM invoice_date)::int AS month,
            type,
            COUNT(*) AS invoice_count,
            COALESCE(SUM(base_amount), 0) AS total_base,
            COALESCE(SUM(tax_amount), 0) AS total_tax,
            COALESCE(SUM(total_amount), 0) AS total_amount
        FROM invoices
        WHERE EXTRACT(YEAR FROM invoice_date) = {year_sql} {where_extra}
        GROUP BY year, month, type
        ORDER BY year DESC, month DESC, type
    """
    rows = query(sql, tuple(params))
    return json.dumps([dict(r) for r in rows], indent=2, default=str)


@mcp.tool()
def vendor_summary(limit: int = 10, year: int = 0, type: str = "expense") -> str:
    """
    Top proveedores por importe facturado.

    Args:
        limit: top N proveedores (max 50)
        year: año (0 = todos)
        type: 'expense' o 'income'
    """
    where_extra = ""
    params = []
    if year > 0:
        where_extra += "AND EXTRACT(YEAR FROM i.invoice_date) = %s"
        params.append(year)
    if type != "all":
        where_extra += " AND i.type = %s"
        params.append(type)

    sql = f"""
        SELECT
            v.name AS vendor,
            v.tax_id,
            COUNT(*) AS invoice_count,
            COALESCE(SUM(i.total_amount), 0) AS total_amount,
            COALESCE(AVG(i.total_amount), 0) AS avg_amount,
            MAX(i.invoice_date) AS last_invoice_date
        FROM invoices i
        JOIN vendors v ON v.id = i.vendor_id
        WHERE 1=1 {where_extra}
        GROUP BY v.name, v.tax_id
        ORDER BY total_amount DESC
        LIMIT %s
    """
    params.append(min(limit, 50))
    rows = query(sql, tuple(params))
    return json.dumps([dict(r) for r in rows], indent=2, default=str)


@mcp.tool()
def pending_payments(limit: int = 20) -> str:
    """
    Lista facturas (gastos) sin pagar, ordenadas por fecha de vencimiento.

    Args:
        limit: máximo de resultados (max 100)
    """
    sql = """
        SELECT
            i.invoice_number,
            v.name AS vendor,
            i.invoice_date,
            i.due_date,
            i.total_amount,
            i.currency,
            (i.due_date - CURRENT_DATE) AS days_until_due
        FROM invoices i
        JOIN vendors v ON v.id = i.vendor_id
        LEFT JOIN payments p ON p.invoice_id = i.id
        WHERE i.type = 'expense'
          AND p.id IS NULL
          AND i.status != 'duplicate'
        ORDER BY i.due_date ASC NULLS LAST
        LIMIT %s
    """
    rows = query(sql, (min(limit, 100),))
    return json.dumps([dict(r) for r in rows], indent=2, default=str)


@mcp.tool()
def count_invoices(
    type: str = "all",
    status: str = "all",
    date_from: str = "",
    date_to: str = "",
) -> str:
    """
    Cuenta facturas según criterios (más rápido que list_invoices si solo quieres el número).

    Args:
        type: 'expense', 'income' o 'all'
        status: 'pending', 'processed', 'paid', 'failed', 'duplicate' o 'all'
        date_from: fecha inicio (YYYY-MM-DD)
        date_to: fecha fin (YYYY-MM-DD)
    """
    where = []
    params = []
    if type != "all":
        where.append("type = %s")
        params.append(type)
    if status != "all":
        where.append("status = %s")
        params.append(status)
    if date_from:
        where.append("invoice_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("invoice_date <= %s")
        params.append(date_to)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    sql = f"SELECT COUNT(*) AS total FROM invoices {where_sql}"
    rows = query(sql, tuple(params))
    return json.dumps(dict(rows[0]) if rows else {"total": 0})


if __name__ == "__main__":
    mcp.run()
