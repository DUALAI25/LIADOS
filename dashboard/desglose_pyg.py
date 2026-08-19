"""
desglose_pyg.py — Motor de cálculo del PYG jerárquico (waterfall).

v1 (2026-07-21): Construye el P&L de un periodo a partir de filas de
facturas, clasifica cada una en uno de los 6 buckets PYG, agrega totales,
calcula márgenes (Margen bruto, MC, EBITDA) y permite drill-down por
sub-categoría y vendor. Pensado para responder las preguntas del jefe
en el vídeo del 2026-07-08:

    "¿Cómo hemos quedado en aprovisionamiento / comisiones / personal /
     otros gastos de producción? Con todo esto calculamos el EBITDA,
     la rentabilidad operativa del restaurante."

API:
    build_pyg(rows, period_from, period_to, cuenta=None, rules=None) -> dict
        rows: lista de dicts con campos de factura (vendor_name, category_raw,
              source_account, invoice_date, total_amount, status).
              total_amount puede venir en céntimos (int) o euros (float);
              se detecta por magnitud (>1000 = céntimos, se divide entre 100).
        period_from / period_to: 'YYYY-MM-DD' (inclusivo).
        cuenta: 'principal' / 'secundaria' / None = todas.
        rules: dict de reglas PYG (ver desglose_pyg_rules.DEFAULT_RULES).
               Si None, se carga con load_rules().

    Devuelve dict con:
        - period: {from, to}
        - cuenta
        - lines: lista jerárquica con totales, % y drill-down
        - totals: {ingresos, margen_bruto, mc, ebitda, beneficio,
                   margen_bruto_pct, mc_pct, ebitda_pct}
        - drilldown: {aprovisionamientos: {alimentacion: {vendors: ...}, ...}, ...}
        - buckets: {bucket: value} plano (para gráficos)
        - issues: lista de avisos (p.ej. 'food_cost > 35%', margen negativo)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as _date, datetime as _dt
from typing import Iterable

try:
    from .desglose_pyg_rules import (
        DEFAULT_RULES,
        BUCKETS,
        classify_factura,
        load_rules,
    )
except (ImportError, ValueError):
    from desglose_pyg_rules import (
        DEFAULT_RULES,
        BUCKETS,
        classify_factura,
        load_rules,
    )


# ── Excepciones ─────────────────────────────────────────────

class PygError(ValueError):
    """Error en input o configuración del PYG."""


# ── Sub-categorías por bucket ────────────────────────────────
# v2 (2026-08-19): cada bucket tiene una lista canónica de sub-categorías
# que se proyectan en la UI. El orden es el que aparece en el Excel del
# cliente (PYG - SIN IVA, Resumen Ejecutivo).
# Cualquier `category_raw` que no se mapee cae en "__otros__".
SUBCATS = {
    "aprovisionamientos": [
        "Alimentación", "Bebida", "Packaging", "__otros__",
    ],
    "comisiones": [
        "Glovo", "Uber", "LastShop", "Just Eat", "__otros__",
    ],
    "personal": [
        "Nóminas", "Seguridad Social", "__otros__",
    ],
    "otros_gastos_produccion": [
        "Material oficina", "Envases", "Mantenimiento", "__otros__",
    ],
    # 5) Servicios y Suministros — coincide con las filas del vídeo:
    #    Alquiler, Luz, Agua, Internet, Carbón, Asesoría lab,
    #    Máquina del agua, Gasolina.
    "servicios": [
        "Alquiler", "Luz", "Agua", "Internet",
        "Asesoría", "Combustible", "Carbón", "__otros__",
    ],
    # 6) Otros gastos de explotación — 7 sub-secciones del Excel:
    #    1) Publicidad y Marketing
    #    2) Material
    #    3) Reparación y mantenimiento
    #    4) Suministros
    #    5) Gestión administrativa
    #    6) Servicios de lavandería
    #    7) Otros
    "otros_gastos": [
        "Publicidad y Marketing", "Oficina", "Software",
        "Servicios Profesionales", "Restauración y Hostelería",
        "Impuestos y Tasas", "Gastos Bancarios", "Seguros",
        "__otros__",
    ],
}

# Márgenes objetivo por sub-categoría (para cross-check fugas).
# Verbalizado v3: "el margen que tengo que tener sobre la bebida es de un 80%".
# Interpretación: si gasto X en bebida y vendo Y en bebida, (Y - X) / Y >= 0.80.
# En la app mostraremos gasto_real vs venta_esperada y alertamos si gap.
TARGET_MARGIN_PCT = {
    "Bebida": 0.80,
    "Alimentación": 0.70,
    "Packaging": 0.50,
}


# ── Helpers ────────────────────────────────────────────────

def _coerce_date(v) -> _date | None:
    if not v:
        return None
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
            try:
                return _dt.strptime(s[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
    return None


def _is_intercompany(vendor_name: str | None) -> bool:
    """Detecta si el vendor es una entidad del propio grupo (VAMOS AL LIO).

    Las facturas entre sociedades del grupo (VAMOS AL LIO SL ↔ VAMOS AL
    LÍO S.L. ↔ HAMBURGUESERIA VAMOS AL LIO ↔ LIADOS VAMOS AL LIO SL)
    representan movimientos internos y no son gasto real para el PYG.
    Devuelve True si parece intercompany.
    """
    if not vendor_name:
        return False
    v = str(vendor_name).strip().lower()
    # Sociedad titular del cliente + sus vehículos
    markers = [
        "vamos al lio", "vamol al lio", "hamburgueseria vamos",
        "liados vamos", "hamburgueseria", "restaurante liados",
    ]
    return any(m in v for m in markers)


def _amount_eur(raw) -> float:
    """Convierte el importe canónico de producción a euros.

    `invoices.total_amount` se almacena en euros (DECIMAL(14,2)). Los campos
    `*_cents` de Last.app se convierten a euros en la consulta del endpoint
    antes de llegar aquí; no se aplica heurística por magnitud.
    """
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _is_venta(category_raw: str | None) -> bool:
    if not category_raw:
        return False
    cr = str(category_raw).strip().lower()
    return cr in ("venta", "ventas", "ingreso", "ingresos", "factura emitida",
                  "facturacion", "facturación")


def _is_descuento(category_raw: str | None) -> bool:
    if not category_raw:
        return False
    cr = str(category_raw).strip().lower()
    return cr in ("descuento", "descuentos", "promocion", "promoción",
                  "promo", "bonificacion", "bonificación")


def _is_devolucion(category_raw: str | None) -> bool:
    if not category_raw:
        return False
    cr = str(category_raw).strip().lower()
    return cr in ("devolucion", "devolución", "devoluciones", "abono",
                  "abonos", "retorno")


def _is_gasto(amount_eur: float, category_raw: str | None) -> bool:
    """Gasto: importes negativos O categorías explícitas de gasto."""
    if amount_eur < 0:
        return True
    if not category_raw:
        return amount_eur > 0  # por defecto, sin categoría, lo tratamos como gasto
    cr = str(category_raw).strip().lower()
    if cr in ("venta", "ventas", "ingreso", "ingresos", "descuento",
              "descuentos", "devolucion", "devolución", "abono"):
        return False
    return True


def _subcat(bucket: str, category_raw: str | None, vendor_name: str | None = "") -> str:
    """Sub-categoría canónica para drill-down (v2).

    Devuelve la sub-categoría del bucket usando heurísticas sobre
    category_raw + vendor_name. Si no casa con ninguna, devuelve "__otros__".
    Coincide con la lista SUBCATS[bucket].
    """
    subs = SUBCATS.get(bucket, ["__todos__"])
    if subs == ["__todos__"]:
        return "__todos__"
    cat = (str(category_raw) if category_raw else "").strip().lower()
    if cat:
        cat = _norm_accents(cat)
    ven = (str(vendor_name) if vendor_name else "").strip().lower()
    if ven:
        ven = _norm_accents(ven)
    cat_compact = cat.replace(" ", "")
    ven_compact = ven.replace(" ", "")

    # ── Matching por bucket ──
    if bucket == "servicios":
        if "alquil" in cat or "alquil" in ven or "hermanostonda" in ven_compact or "propietario" in ven:
            return "Alquiler"
        if any(k in ven for k in ["iberdrola", "endesa", "naturgy", "cye", "met energia", "metenergi"]):
            return "Luz"
        if any(k in ven for k in ["aqualia", "redexis", "efigas"]):
            return "Agua"
        if any(k in ven for k in ["telef", "movistar", "vodafone", "orange", "jazztel", "ionos"]):
            return "Internet"
        if any(k in ven for k in ["asesor", "cochera", "silca", "control y certific", "control y certif"]):
            return "Asesoría"
        if any(k in ven for k in ["repsol", "gestilan", "butano", "gasolina"]) or "gasolina" in cat:
            return "Combustible"
        if cat in ("carbon", "carbn"):
            return "Carbón"
        return "__otros__"

    if bucket == "otros_gastos":
        if "marketing" in cat or "publicidad" in cat:
            return "Publicidad y Marketing"
        if cat in ("oficina", "materialdeoficina"):
            return "Oficina"
        if "software" in cat:
            return "Software"
        if "impuesto" in cat:
            return "Impuestos y Tasas"
        if "bancario" in cat:
            return "Gastos Bancarios"
        if "seguro" in cat:
            return "Seguros"
        if "serviciosprofesional" in cat_compact or "profesional" in cat:
            return "Servicios Profesionales"
        if "restauracion" in cat or "hostele" in cat or "hosteleria" in cat:
            return "Restauración y Hostelería"
        return "__otros__"

    if bucket == "otros_gastos_produccion":
        if "envase" in ven or "rotapel" in ven or "bluco" in ven:
            return "Envases"
        if cat in ("oficina", "materialdeoficina", "materialdeoficinayoficios"):
            return "Material oficina"
        if any(k in ven for k in ["sanysan", "restatec", "instalacioneselectric", "danimobel"]):
            return "Mantenimiento"
        return "__otros__"

    if bucket == "comisiones":
        if "glovo" in ven:
            return "Glovo"
        if "uber" in ven:
            return "Uber"
        if "last.app" in ven or "lastshop" in ven or "last shop" in ven or "last.app" in ven.replace(" ", ""):
            return "LastShop"
        if "just" in ven and "eat" in ven:
            return "Just Eat"
        return "__otros__"

    if bucket == "personal":
        if "seguridadsocial" in cat_compact or "seguridad" in cat:
            return "Seguridad Social"
        if any(k in cat for k in ["nomina", "nominas", "sueldo", "salario", "personal"]):
            return "Nóminas"
        return "__otros__"

    if bucket == "aprovisionamientos":
        if cat in ("bebida", "drink"):
            return "Bebida"
        if cat in ("packaging", "envases"):
            return "Packaging"
        if "packaging" in ven or "envase" in ven:
            return "Packaging"
        if "bebida" in ven or "coca" in ven or "pepsi" in ven:
            return "Bebida"
        return "Alimentación"

    return "__otros__"


def _norm_accents(s: str) -> str:
    repl = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
            ("à", "a"), ("è", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u"),
            ("ñ", "n"), ("ü", "u"))
    for a, b in repl:
        s = s.replace(a, b)
    return s


# ── API principal ─────────────────────────────────────────

def build_pyg(
    rows: Iterable[dict],
    period_from: str,
    period_to: str,
    cuenta: str | None = None,
    rules: dict | None = None,
) -> dict:
    """Calcula el PYG jerárquico para un periodo."""
    if rules is None:
        rules = load_rules()

    # Parsear periodo
    try:
        d_from = _dt.strptime(period_from, "%Y-%m-%d").date()
        d_to = _dt.strptime(period_to, "%Y-%m-%d").date()
    except ValueError as e:
        raise PygError(f"Fechas inválidas: {period_from} / {period_to}") from e
    if d_from > d_to:
        raise PygError(f"period_from > period_to: {period_from} > {period_to}")

    # Normalizar filas
    clean_rows = []
    for r in rows or []:
        if not r:
            continue
        d = _coerce_date(r.get("invoice_date"))
        if d is None:
            continue
        if d < d_from or d > d_to:
            continue
        if cuenta is not None:
            src = (r.get("source_account") or r.get("account") or "").strip().lower()
            if cuenta.lower() not in src and src != cuenta.lower():
                # Permitir match laxo: 'principal' matchea 'principal_pg', etc.
                if not src.startswith(cuenta.lower()):
                    continue
        amount = _amount_eur(r.get("total_amount"))
        clean_rows.append({
            "date": d,
            "amount": amount,
            "category": r.get("category_raw") or r.get("category") or "",
            "vendor": r.get("vendor_name") or r.get("vendor") or "",
        })

    # Ingresos y ajustes
    ventas_brutas = 0.0
    descuentos = 0.0
    devoluciones = 0.0
    # Gastos por bucket × sub-categoría × vendor
    gastos: dict[str, dict[str, dict[str, float]]] = {
        b: defaultdict(lambda: defaultdict(float)) for b in BUCKETS
    }
    bucket_totals: dict[str, float] = {b: 0.0 for b in BUCKETS}

    for r in clean_rows:
        cat = r["category"]
        amount = r["amount"]
        if _is_venta(cat) and amount > 0:
            ventas_brutas += amount
        elif _is_descuento(cat) and amount > 0:
            descuentos += amount
        elif _is_devolucion(cat) and amount > 0:
            devoluciones += amount
        elif _is_gasto(amount, cat):
            # v2.1: Filtrar gastos con amount=0 (datos corruptos / cancelaciones)
            if amount <= 0.005:
                continue
            # v2.1: Filtrar movimientos intercompany (VAMOS AL LIO ↔ LIADOS).
            # Esas facturas no representan gasto real para el restaurante.
            if _is_intercompany(r["vendor"]):
                continue
            # Clasificar en bucket
            bucket = classify_factura(cat, r["vendor"], rules=rules)
            if bucket not in gastos:
                bucket = "otros_gastos"
            sub = _subcat(bucket, cat, r["vendor"])
            vendor = (r["vendor"] or "Sin vendor").strip() or "Sin vendor"
            gastos[bucket][sub][vendor] += abs(amount)
            bucket_totals[bucket] += abs(amount)

    ingresos = ventas_brutas - descuentos - devoluciones
    if ingresos < 0:
        ingresos = 0.0  # safeguard

    # Construir jerarquía
    lines: list[dict] = []

    # Nivel 0: ingresos
    lines.append({
        "code": "ventas_brutas", "label": "Ventas brutas",
        "value": round(ventas_brutas, 2), "pct": None, "level": 0,
        "kind": "line",
    })
    if descuentos > 0:
        lines.append({
            "code": "descuentos", "label": "Descuentos / promociones",
            "value": -round(descuentos, 2), "pct": None, "level": 0,
            "kind": "line",
        })
    if devoluciones > 0:
        lines.append({
            "code": "devoluciones", "label": "Devoluciones",
            "value": -round(devoluciones, 2), "pct": None, "level": 0,
            "kind": "line",
        })
    lines.append({
        "code": "ingresos", "label": "Ventas N-Descuentos (Ingresos)",
        "value": round(ingresos, 2), "pct": 1.0, "level": 0,
        "kind": "subtotal", "highlight": "yellow",
    })

    # Nivel 1: gastos
    for b in BUCKETS:
        v = bucket_totals[b]
        if v <= 0.001:
            continue
        # Cabecera de bucket
        label_map = {
            "aprovisionamientos": "1) Aprovisionamientos (Food cost)",
            "comisiones": "2) Comisiones",
            "personal": "3) Personal",
            "otros_gastos_produccion": "4) Otros gastos de producción",
            "servicios": "5) Servicios y Suministros",
            "otros_gastos": "6) Otros gastos de explotación",
        }
        lines.append({
            "code": b, "label": label_map.get(b, b),
            "value": round(v, 2),
            "pct": round(v / ingresos, 4) if ingresos else 0.0,
            "level": 1, "kind": "section",
            "children_count": len(gastos[b]),
        })
        # Drill-down por sub-categoría
        for sub, vendors in gastos[b].items():
            sub_value = sum(vendors.values())
            sub_label = sub if sub not in ("__todos__", "__otros__") else (
                "Todos" if sub == "__todos__" else "Otros"
            )
            lines.append({
                "code": f"{b}.{sub}", "label": f"   └ {sub_label}",
                "value": round(sub_value, 2),
                "pct": round(sub_value / ingresos, 4) if ingresos else 0.0,
                "level": 2, "kind": "subcat",
                "parent": b,
            })
            # Top vendors
            sorted_v = sorted(vendors.items(), key=lambda kv: kv[1], reverse=True)
            for vendor, vval in sorted_v[:5]:
                lines.append({
                    "code": f"{b}.{sub}.{vendor}", "label": f"        • {vendor}",
                    "value": round(vval, 2),
                    "pct": round(vval / ingresos, 4) if ingresos else 0.0,
                    "level": 3, "kind": "vendor",
                    "parent": f"{b}.{sub}",
                })

    # Márgenes
    aprovisionamientos_v = bucket_totals["aprovisionamientos"]
    comisiones_v = bucket_totals["comisiones"]
    personal_v = bucket_totals["personal"]
    otros_prod_v = bucket_totals["otros_gastos_produccion"]
    servicios_v = bucket_totals["servicios"]
    otros_v = bucket_totals["otros_gastos"]

    margen_bruto = ingresos - aprovisionamientos_v
    mc = margen_bruto - comisiones_v
    ebitda = mc - personal_v - servicios_v - otros_prod_v
    beneficio = ebitda - otros_v

    lines.append({
        "code": "margen_bruto", "label": "Margen bruto",
        "value": round(margen_bruto, 2),
        "pct": round(margen_bruto / ingresos, 4) if ingresos else 0.0,
        "level": 0, "kind": "subtotal", "highlight": "yellow",
    })
    lines.append({
        "code": "mc", "label": "Margen de Contribución (MC)",
        "value": round(mc, 2),
        "pct": round(mc / ingresos, 4) if ingresos else 0.0,
        "level": 0, "kind": "subtotal", "highlight": "yellow",
    })
    lines.append({
        "code": "ebitda", "label": "EBITDA (rentabilidad operativa)",
        "value": round(ebitda, 2),
        "pct": round(ebitda / ingresos, 4) if ingresos else 0.0,
        "level": 0, "kind": "kpi", "highlight": "green",
    })
    if otros_v > 0:
        lines.append({
            "code": "beneficio", "label": "Beneficio neto (provisional)",
            "value": round(beneficio, 2),
            "pct": round(beneficio / ingresos, 4) if ingresos else 0.0,
            "level": 0, "kind": "subtotal", "highlight": "yellow",
        })

    # Issues / alertas
    issues: list[dict] = []
    if ingresos > 0:
        food_cost_pct = aprovisionamientos_v / ingresos
        if food_cost_pct > 0.35:
            issues.append({
                "level": "warn",
                "code": "food_cost_alto",
                "message": f"Food cost {food_cost_pct*100:.1f}% > 35% (objetivo ~23%)",
            })
        elif food_cost_pct > 0.30:
            issues.append({
                "level": "info",
                "code": "food_cost_atencion",
                "message": f"Food cost {food_cost_pct*100:.1f}% cerca del límite",
            })
        comision_pct = comisiones_v / ingresos
        if comision_pct > 0.20:
            issues.append({
                "level": "warn",
                "code": "comision_alta",
                "message": f"Comisión media {comision_pct*100:.1f}% > 20% (objetivo ~17%)",
            })
        if ebitda < 0:
            issues.append({
                "level": "error",
                "code": "ebitda_negativo",
                "message": f"EBITDA negativo: {ebitda:.2f}€",
            })
        elif ebitda / ingresos < 0.05:
            issues.append({
                "level": "warn",
                "code": "ebitda_margen_bajo",
                "message": f"EBITDA margin {ebitda/ingresos*100:.1f}% < 5%",
            })

    # Drilldown serializable
    drilldown: dict = {}
    for b in BUCKETS:
        if not gastos[b]:
            continue
        drilldown[b] = {}
        for sub, vendors in gastos[b].items():
            drilldown[b][sub] = {
                "value": round(sum(vendors.values()), 2),
                "vendors": [
                    {"name": k, "value": round(vv, 2)} for k, vv in
                    sorted(vendors.items(), key=lambda kv: kv[1], reverse=True)
                ],
            }

    return {
        "period": {"from": period_from, "to": period_to},
        "cuenta": cuenta,
        "lines": lines,
        "buckets": {b: round(bucket_totals[b], 2) for b in BUCKETS},
        "drilldown": drilldown,
        "totals": {
            "ventas_brutas": round(ventas_brutas, 2),
            "descuentos": round(descuentos, 2),
            "devoluciones": round(devoluciones, 2),
            "ingresos": round(ingresos, 2),
            "total_gastos": round(sum(bucket_totals.values()), 2),
            "margen_bruto": round(margen_bruto, 2),
            "mc": round(mc, 2),
            "ebitda": round(ebitda, 2),
            "beneficio": round(beneficio, 2),
            "margen_bruto_pct": round(margen_bruto / ingresos, 4) if ingresos else 0.0,
            "mc_pct": round(mc / ingresos, 4) if ingresos else 0.0,
            "ebitda_pct": round(ebitda / ingresos, 4) if ingresos else 0.0,
        },
        "issues": issues,
        "rows_used": len(clean_rows),
    }


def cross_check_subcat(
    pyg: dict,
    ventas_por_subcat: dict[str, float] | None = None,
) -> list[dict]:
    """Compara gasto real en aprovisionamientos vs venta esperada.

    Verbalizado v3: "si en bebida he gastado tanto y se he vendido tanto,
    el margen que tengo que tener sobre la bebida es de un 80%".

    ventas_por_subcat: dict { 'Bebida': 1500, 'Alimentación': 4000, ... }.
    Si no se facilita, devuelve solo el gasto_real por sub-categoría
    (la app puede completarlo con datos de ventas reales del cliente).
    """
    drill = pyg.get("drilldown", {}).get("aprovisionamientos", {})
    out: list[dict] = []
    for sub, info in drill.items():
        if sub in ("__todos__", "__otros__"):
            continue
        gasto_real = info["value"]
        target_margin = TARGET_MARGIN_PCT.get(sub)
        if ventas_por_subcat and sub in ventas_por_subcat:
            venta_real = ventas_por_subcat[sub]
            venta_necesaria_para_target = (
                gasto_real / (1 - target_margin) if target_margin and target_margin < 1 else None
            )
            margin_real = (venta_real - gasto_real) / venta_real if venta_real else None
            gap_venta = (
                (venta_necesaria_para_target - venta_real) if venta_necesaria_para_target else None
            )
            out.append({
                "subcat": sub,
                "gasto_real": gasto_real,
                "venta_real": venta_real,
                "target_margin": target_margin,
                "margin_real": margin_real,
                "venta_necesaria_para_target": venta_necesaria_para_target,
                "gap_venta": gap_venta,
                "status": (
                    "ok" if margin_real is not None and margin_real >= target_margin
                    else "alerta"
                ),
            })
        else:
            out.append({
                "subcat": sub,
                "gasto_real": gasto_real,
                "venta_real": None,
                "target_margin": target_margin,
                "status": "sin_dato_venta",
            })
    return out
