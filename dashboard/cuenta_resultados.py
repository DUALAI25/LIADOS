"""Cuenta de resultados mensual estilo Excel para Liados."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from calendar import monthrange

try:
    from .desglose_pyg_rules import classify_factura, load_rules
except ImportError:
    from desglose_pyg_rules import classify_factura, load_rules

MONTH_NAMES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

_PROVIDER_ALIASES = (
    ("makro", "Makro"),
    ("envases para profesionales", "Envases para profesionales"),
    ("mercadona", "Mercadona"),
    ("vamos al lio", "Vamos al Lío"),
    ("liados vamos al lio", "Vamos al Lío"),
    ("hamburgueseria vamos al lio", "Vamos al Lío"),
    ("iberdrola", "Iberdrola"),
    ("trello", "Trello"),
    ("hp printing", "HP Printing"),
    ("met energia", "MET Energía"),
    ("creaciones danimobel", "Creaciones Danimobel"),
    ("leroy merlin", "Leroy Merlin"),
    ("ikea", "IKEA"),
    ("repsol", "Repsol"),
    ("atlanta frutas", "Atlanta Frutas"),
    ("glovo", "Glovo"),
    ("uber eats", "Uber Eats"),
    ("last shop", "Last Shop"),
)


def _strip_text(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower().strip()


def normalize_provider(value: str | None) -> str:
    """Clave estable: sin acentos, puntuación, sufijos societarios ni espacios dobles."""
    text = _strip_text(value)
    text = re.sub(r"[,.()]+", " ", text)
    text = re.sub(r"\b(?:s\s*l(?:\s*u)?|s\s*a(?:\s*u)?|cb|gmbh|ltd|inc)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def provider_label(value: str | None) -> str:
    key = normalize_provider(value)
    for alias, label in _PROVIDER_ALIASES:
        if alias in key:
            return label
    return str(value or "Proveedor sin nombre").strip() or "Proveedor sin nombre"


def _date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _eur(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _month_keys(start: date, end: date) -> list[str]:
    out = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def _values(months, data):
    result = {m: round(data.get(m, 0.0), 2) for m in months}
    result["YTD"] = round(sum(result.values()), 2)
    return result


def _row(code, label, months, data, *, kind="line", level=0, pct_of=None, children=None, availability="real", section=False):
    values = _values(months, data)
    pcts = {}
    if pct_of:
        pct_values = _values(months, pct_of)
        pcts = {m: round(values[m] / pct_values[m], 4) if pct_values[m] else 0.0 for m in months + ["YTD"]}
    return {"code": code, "label": label, "values": values, "pct_values": pcts, "kind": kind, "level": level, "children": children or [], "availability": availability, "section": section}


def _provider_children(rows, months, bucket, rules):
    totals = defaultdict(lambda: defaultdict(float))
    labels = {}
    for row in rows:
        category = str(row.get("category_raw") or row.get("category") or "")
        vendor = row.get("vendor_name") or row.get("vendor") or "Proveedor sin nombre"
        if classify_factura(category, vendor, rules=rules) != bucket:
            continue
        d = _date_value(row.get("invoice_date"))
        if not d:
            continue
        label = provider_label(vendor)
        key = normalize_provider(label) or "proveedor sin nombre"
        labels.setdefault(key, label)
        totals[key][f"{d.year:04d}-{d.month:02d}"] += abs(_eur(row.get("total_amount")))
    children = []
    for key in sorted(totals, key=lambda k: (-sum(totals[k].values()), labels[k].lower())):
        children.append({"code": f"{bucket}.provider.{key}", "label": labels[key], "provider_key": key, "values": _values(months, totals[key]), "kind": "provider", "level": 1, "children": [], "availability": "real"})
    return children


def _merge_provider_children(groups, months):
    merged = {}
    for group in groups:
        for child in group:
            key = child["provider_key"]
            if key not in merged:
                merged[key] = dict(child)
                merged[key]["values"] = dict(child["values"])
            else:
                for month in months + ["YTD"]:
                    merged[key]["values"][month] = round(merged[key]["values"].get(month, 0.0) + child["values"].get(month, 0.0), 2)
    return sorted(merged.values(), key=lambda c: (-c["values"].get("YTD", 0.0), c["label"].lower()))


def build_cuenta_resultados(invoice_rows, sales_rows, period_from: str, period_to: str, cuenta: str | None = None, rules=None):
    start = _date_value(period_from)
    end = _date_value(period_to)
    if not start or not end or start > end:
        raise ValueError("Periodo inválido")
    months = _month_keys(start, end)
    rules = rules or load_rules()
    sales_net = defaultdict(float); sales_base = defaultdict(float); sales_tax = defaultdict(float); discounts = defaultdict(float)
    for row in sales_rows or []:
        d = _date_value(row.get("invoice_date"))
        if not d or d < start or d > end:
            continue
        key = f"{d.year:04d}-{d.month:02d}"
        sales_net[key] += _eur(row.get("total_amount"))
        sales_base[key] += _eur(row.get("base_amount"))
        sales_tax[key] += _eur(row.get("tax_amount"))
        discounts[key] += _eur(row.get("discount_amount"))
    buckets = {b: defaultdict(float) for b in ("food_cost", "comisiones", "personal", "otros_explotacion")}
    expense_tax = defaultdict(float)
    expense_rows = []
    for row in invoice_rows or []:
        d = _date_value(row.get("invoice_date"))
        if not d or d < start or d > end:
            continue
        if cuenta and str(row.get("source_account") or "").lower() != cuenta.lower():
            continue
        key = f"{d.year:04d}-{d.month:02d}"
        amount = abs(_eur(row.get("total_amount")))
        category = str(row.get("category_raw") or row.get("category") or "")
        vendor = row.get("vendor_name") or ""
        bucket = classify_factura(category, vendor, rules=rules)
        if bucket == "aprovisionamientos": target = "food_cost"
        elif bucket == "comisiones": target = "comisiones"
        elif bucket == "personal": target = "personal"
        else: target = "otros_explotacion"
        buckets[target][key] += amount
        expense_tax[key] += _eur(row.get("tax_amount"))
        expense_rows.append(row)
    net = {m: sales_net.get(m, 0.0) for m in months}
    sales_base = {m: sales_base.get(m, 0.0) for m in months}
    sales_tax = {m: sales_tax.get(m, 0.0) for m in months}
    discounts = {m: discounts.get(m, 0.0) for m in months}
    gross = {m: net[m] + discounts[m] for m in months}
    food = {m: buckets["food_cost"].get(m, 0.0) for m in months}; commissions = {m: buckets["comisiones"].get(m, 0.0) for m in months}; personal = {m: buckets["personal"].get(m, 0.0) for m in months}; other = {m: buckets["otros_explotacion"].get(m, 0.0) for m in months}
    margin_gross = {m: net[m] - food[m] for m in months}
    margin_contrib = {m: margin_gross[m] - commissions[m] for m in months}
    ebitda = {m: margin_contrib[m] - personal[m] - other[m] for m in months}
    zero = {m: 0.0 for m in months}
    rows = []
    rows.append(_row("ventas", "1  Venta neta + descuentos", months, net, kind="section", level=0, section=True, children=[
        _row("venta_bruta_descuentos", "Venta bruta + descuentos", months, gross, level=1),
        _row("venta_neta", "Venta neta", months, net, level=1),
        _row("descuentos", "Descuentos", months, {m: -discounts[m] for m in months}, level=1),
        _row("ventas_sin_iva", "Ventas sin IVA", months, sales_base, level=1),
        _row("iva_ventas", "IVA repercutido", months, sales_tax, level=1),
        _row("canal_no_disponible", "Canal operativo (Last.app no lo proporciona)", months, zero, level=1, availability="unavailable"),
    ]))
    rows.append(_row("food_cost", "2  Food cost", months, {m: -food[m] for m in months}, kind="section", section=True, children=_provider_children(expense_rows, months, "aprovisionamientos", rules)))
    rows.append(_row("food_cost_pct", "% Food cost", months, {m: food[m] / net[m] if net[m] else 0.0 for m in months}, kind="percentage", availability="derived"))
    rows.append(_row("margen_bruto", "3  Margen Bruto", months, margin_gross, kind="subtotal", section=True, pct_of=net))
    rows.append(_row("margen_bruto_pct", "% Margen Bruto", months, {m: margin_gross[m] / net[m] if net[m] else 0.0 for m in months}, kind="percentage", availability="derived"))
    rows.append(_row("margen_contribucion", "4  Margen de Contribución", months, margin_contrib, kind="subtotal", section=True, pct_of=net, children=_provider_children(expense_rows, months, "comisiones", rules)))
    rows.append(_row("margen_contribucion_pct", "% Margen de Contribución", months, {m: margin_contrib[m] / net[m] if net[m] else 0.0 for m in months}, kind="percentage", availability="derived"))
    rows.append(_row("personal", "5  Gastos de personal", months, {m: -personal[m] for m in months}, kind="section", section=True, children=_provider_children(expense_rows, months, "personal", rules)))
    rows.append(_row("personal_pct", "% Gastos de personal", months, {m: -personal[m] / net[m] if net[m] else 0.0 for m in months}, kind="percentage", availability="derived"))
    other_children = _merge_provider_children([_provider_children(expense_rows, months, "otros_gastos", rules), _provider_children(expense_rows, months, "servicios", rules), _provider_children(expense_rows, months, "otros_gastos_produccion", rules)], months)
    rows.append(_row("otros_explotacion", "6  Otros gastos de explotación", months, {m: -other[m] for m in months}, kind="section", section=True, children=other_children))
    rows.append(_row("otros_explotacion_pct", "% Otros gastos de explotación", months, {m: -other[m] / net[m] if net[m] else 0.0 for m in months}, kind="percentage", availability="derived"))
    rows.append(_row("ebitda", "7  EBITDA", months, ebitda, kind="subtotal", section=True, pct_of=net))
    rows.append(_row("ebitda_pct", "% EBITDA", months, {m: ebitda[m] / net[m] if net[m] else 0.0 for m in months}, kind="percentage", availability="derived"))
    rows.extend([
        _row("amortizacion", "Amortización y depreciación", months, zero, availability="unavailable"),
        _row("ebit", "EBIT", months, ebitda, kind="subtotal", pct_of=net, availability="derived"),
        _row("resultado_financiero", "Resultado financiero", months, zero, availability="unavailable"),
        _row("resultado_antes_impuestos", "Resultado antes de impuestos", months, ebitda, kind="subtotal", pct_of=net, availability="derived"),
        _row("impuesto_sociedades", "Impuesto de sociedades", months, zero, availability="unavailable"),
        _row("resultado_ejercicio", "8  Resultado del ejercicio", months, ebitda, kind="subtotal", section=True, pct_of=net, availability="provisional"),
    ])
    totals = {
        "ventas_netas": round(sum(net.values()), 2), "ventas_sin_iva": round(sum(sales_base.values()), 2), "iva_ventas": round(sum(sales_tax.values()), 2), "iva_gastos": round(sum(expense_tax.values()), 2), "descuentos": round(sum(discounts.values()), 2), "food_cost": round(sum(food.values()), 2), "comisiones": round(sum(commissions.values()), 2), "personal": round(sum(personal.values()), 2), "otros_explotacion": round(sum(other.values()), 2), "margen_bruto": round(sum(margin_gross.values()), 2), "margen_contribucion": round(sum(margin_contrib.values()), 2), "ebitda": round(sum(ebitda.values()), 2), "resultado_ejercicio": round(sum(ebitda.values()), 2),
    }
    totals["margen_bruto_pct"] = round(totals["margen_bruto"] / totals["ventas_netas"], 4) if totals["ventas_netas"] else 0.0
    totals["margen_contribucion_pct"] = round(totals["margen_contribucion"] / totals["ventas_netas"], 4) if totals["ventas_netas"] else 0.0
    totals["ebitda_pct"] = round(totals["ebitda"] / totals["ventas_netas"], 4) if totals["ventas_netas"] else 0.0
    return {"period": {"from": start.isoformat(), "to": end.isoformat()}, "columns": months + ["YTD"], "rows": rows, "totals": totals, "issues": [{"code": "canales_no_disponibles", "level": "info", "message": "Last.app no entrega canal operativo en los datos descargados."}, {"code": "bloques_contables_no_disponibles", "level": "info", "message": "Amortización, resultado financiero e impuesto de sociedades requieren una fuente contable adicional."}], "rows_used": len(expense_rows) + len(sales_rows or [])}
