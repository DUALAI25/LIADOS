"""
desglose.py — Sistema de desglose multidimensional de gastos.

v1 (2026-07-12): permite agrupar facturas por 1-N dimensiones y aplicar
una métrica agregada (count, sum, avg, min, max).

Diseñado para responder preguntas tipo:
- "¿Cuánto he gastado en Suministros por Makro este trimestre?"
- "¿Qué proveedor de la categoría X tiene ticket medio más alto?"
- "¿Cuánto se ha facturado por principal vs secundaria por mes?"

API:
    build_desglose(rows, group_by, metric) -> dict
        rows: lista de dicts con los campos de cada factura
        group_by: lista de claves por las que agrupar (1 a 4)
        metric: 'count' | 'sum' | 'avg' | 'min' | 'max'

Devuelve dict con:
    - rows: lista de dicts {dim1: ..., dim2: ..., value: ..., count: ...}
    - total: {value, count}
    - metric, group_by, dims (echo para debug)
"""
from collections import defaultdict
from typing import Iterable

# Dimensiones soportadas y el campo SQL/JSON al que mapean.
DIMENSION_MAP = {
    "vendor": "vendor_name",
    "category": "category_raw",
    "cuenta": "source_account",
    "source": "source",
    "month": "_month",       # derivado de invoice_date
    "quarter": "_quarter",   # derivado de invoice_date
    "year": "_year",         # derivado de invoice_date
    "status": "status",
}

METRICS = ("count", "sum", "avg", "min", "max")
ALLOWED_DIMS = tuple(DIMENSION_MAP.keys())
MAX_DIMS = 4
MAX_ROWS = 5000  # cap de seguridad


class DesgloseError(ValueError):
    """Error de input del usuario al construir un desglose."""


def _coerce_date(v):
    """Convierte string ISO/date a date. None si vacío."""
    if not v:
        return None
    try:
        from datetime import date as _date, datetime as _dt
        if isinstance(v, _dt):
            return v.date()
        if isinstance(v, _date):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                return _dt.fromisoformat(s.replace("Z", "+00:00")).date()
            except ValueError:
                # Sólo "YYYY-MM-DD"
                return _dt.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    return None


def _get_dim_value(row, dim):
    """Extrae el valor de la dimensión dim de la fila row."""
    field = DIMENSION_MAP.get(dim)
    if field is None:
        raise DesgloseError(f"Dimensión no soportada: {dim}. Válidas: {ALLOWED_DIMS}")

    if field.startswith("_"):
        # Derivadas de fecha
        d = _coerce_date(row.get("invoice_date"))
        if d is None:
            return None
        if field == "_month":
            return f"{d.year:04d}-{d.month:02d}"
        if field == "_quarter":
            q = (d.month - 1) // 3 + 1
            return f"{d.year:04d}-Q{q}"
        if field == "_year":
            return str(d.year)
    return row.get(field) or None


def _compute_metric(metric, amounts):
    """Aplica la métrica a la lista de importes (en euros, no céntimos)."""
    if not amounts:
        return 0.0
    if metric == "count":
        return float(len(amounts))
    if metric == "sum":
        return float(sum(amounts))
    if metric == "avg":
        return float(sum(amounts) / len(amounts))
    if metric == "min":
        return float(min(amounts))
    if metric == "max":
        return float(max(amounts))
    raise DesgloseError(f"Métrica no soportada: {metric}")


def build_desglose(rows: Iterable[dict], group_by: list[str], metric: str) -> dict:
    """Construye un desglose multidimensional a partir de filas de facturas.

    Args:
        rows: lista de dicts con campos normalizados (ver DIMENSION_MAP).
              Cada fila DEBE tener `invoice_date` y opcionalmente los demás
              campos de dimensión. `total_amount` se espera en euros, como en la tabla invoices.
        group_by: lista de 1 a 4 dimensiones válidas (ver ALLOWED_DIMS).
        metric: una de METRICS.

    Returns:
        dict con `rows` (lista de filas agrupadas), `total`, y echoes.
    """
    # Validar inputs
    if not isinstance(group_by, (list, tuple)):
        raise DesgloseError("group_by debe ser lista")
    if not (1 <= len(group_by) <= MAX_DIMS):
        raise DesgloseError(f"group_by debe tener entre 1 y {MAX_DIMS} dimensiones, "
                            f"recibido: {len(group_by)}")
    for d in group_by:
        if d not in DIMENSION_MAP:
            raise DesgloseError(f"Dimensión inválida: {d}. Válidas: {ALLOWED_DIMS}")
    if metric not in METRICS:
        raise DesgloseError(f"Métrica inválida: {metric}. Válidas: {METRICS}")

    # Agrupar
    groups = defaultdict(list)
    total_amounts = []

    rows = list(rows)
    if len(rows) > MAX_ROWS:
        raise DesgloseError(f"Demasiadas filas ({len(rows)} > {MAX_ROWS})")

    for r in rows:
        # Unidad canónica de producción: euros.
        ta = r.get("total_amount")
        try:
            amount_eur = float(ta) if ta is not None else 0.0
        except (TypeError, ValueError):
            amount_eur = 0.0

        # Construir clave compuesta
        key_parts = []
        for d in group_by:
            v = _get_dim_value(r, d)
            key_parts.append(v)
        key = tuple(key_parts)
        groups[key].append(amount_eur)
        total_amounts.append(amount_eur)

    # Construir respuesta
    out_rows = []
    for key, amounts in groups.items():
        row = {dim: val for dim, val in zip(group_by, key)}
        row["count"] = len(amounts)
        row["value"] = round(_compute_metric(metric, amounts), 2)
        out_rows.append(row)

    # Ordenar por value desc (top N)
    out_rows.sort(key=lambda x: x["value"], reverse=True)

    total_dict = {
        "value": round(_compute_metric(metric, total_amounts), 2),
        "count": len(total_amounts),
    }

    return {
        "group_by": list(group_by),
        "metric": metric,
        "dims": ALLOWED_DIMS,  # eco para UI
        "rows": out_rows,
        "total": total_dict,
        "rows_count": len(out_rows),
    }


def normalize_invoice_row(row: dict) -> dict:
    """Convierte una fila cruda de la BD en el shape que consume build_desglose.

    Acepta campos con alias (vendor vs vendor_name, etc.) para robustez.
    """
    if not row:
        return {}
    out = dict(row)
    # Aliases
    if "vendor" in out and "vendor_name" not in out:
        out["vendor_name"] = out["vendor"]
    if "category" in out and "category_raw" not in out:
        out["category_raw"] = out["category"]
    if "account" in out and "source_account" not in out:
        out["source_account"] = out["account"]
    return out