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
        classify_factura_v2,
        load_rules,
        detect_duplicate,
    )
    from .taxonomy import (
        CATEGORIES as OFFICIAL_CATEGORIES,
        HARD_FLAGS,
        CONFIDENCE_AUTO_CLASSIFY,
        CONFIDENCE_REVIEW,
        needs_multicategory_check,
        is_capex_suspect,
        is_financial_expense,
    )
except (ImportError, ValueError):
    from desglose_pyg_rules import (
        DEFAULT_RULES,
        BUCKETS,
        classify_factura,
        classify_factura_v2,
        load_rules,
        detect_duplicate,
    )
    from taxonomy import (
        CATEGORIES as OFFICIAL_CATEGORIES,
        HARD_FLAGS,
        CONFIDENCE_AUTO_CLASSIFY,
        CONFIDENCE_REVIEW,
        needs_multicategory_check,
        is_capex_suspect,
        is_financial_expense,
    )


# ── Excepciones ─────────────────────────────────────────────

class PygError(ValueError):
    """Error en input o configuración del PYG."""


# ── Bloques PYG oficiales (según spec del cliente) ───────────
# Estructura canónica del PYG SIN IVA:
#
#   Ventas N-Descuentos (Ingresos)
#   Aprovisionamientos
#   ├─ Alimentación
#   ├─ Bebida
#   └─ Packaging
#   Margen Bruto
#   Comisiones
#   ├─ Glovo
#   ├─ Uber
#   └─ LastShop
#   Margen de Contribución
#   Personal
#   Otros gastos de explotación
#   ├─ Servicios y Suministros
#   ├─ Publicidad y Marketing
#   └─ Gastos Generales
#   EBITDA
#   ── (capa posterior) ──
#   Amortización
#   EBIT
#   Resultado financiero
#   Resultado antes de impuestos
#   Impuesto sobre beneficios
#   Resultado del ejercicio
PYG_BLOCKS_ORDER: tuple[str, ...] = (
    "ventas",
    "aprovisionamientos",
    "margen_bruto",
    "comisiones",
    "mc",
    "personal",
    "otros_gastos_explotacion",
    "ebitda",
    "amortizacion",
    "ebit",
    "resultado_financiero",
    "resultado_antes_impuestos",
    "impuesto_beneficios",
    "resultado_ejercicio",
)


# Mapeo: bloque PYG canónico → etiqueta humana
PYG_BLOCK_LABELS: dict[str, str] = {
    "ventas": "Ventas N-Descuentos",
    "aprovisionamientos": "Aprovisionamientos",
    "margen_bruto": "Margen Bruto",
    "comisiones": "Comisiones",
    "mc": "Margen de Contribución",
    "personal": "Personal",
    "otros_gastos_explotacion": "Otros gastos de explotación",
    "ebitda": "EBITDA",
    "amortizacion": "Amortización",
    "ebit": "EBIT (Resultado de Explotación)",
    "resultado_financiero": "Resultado financiero",
    "resultado_antes_impuestos": "Resultado antes de impuestos",
    "impuesto_beneficios": "Impuesto sobre beneficios",
    "resultado_ejercicio": "Resultado del ejercicio",
}


# ── Sub-categorías por bucket (legacy, compatibilidad) ───────
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


# ── v3 (Guía v2.0 §30): Esquema JSON de salida ────────────────

def build_pyg_v2_doc(
    rows: Iterable[dict],
    period_from: str,
    period_to: str,
    cuenta: str | None = None,
    rules: dict | None = None,
) -> dict:
    """Produce el esquema JSON v2.0 (Guía §30) para un periodo.

    Cada factura se clasifica con `classify_factura_v2` y se audita
    después con `audit_classification`. Devuelve:

        {
          "schema_version": "liados-improvement-v2.0",
          "mode": "IMPROVE_EXISTING_SYSTEM",
          "period": {...},
          "cuenta": ...,
          "documents": [<doc>],   # uno por factura
          "summary": {<resumen agregado>},
          "totals": {<métricas globales>},
          "issues": [<avisos>],
          "audit_summary": {<resumen de auditoría>}
        }

    Cada `document` contiene los campos del esquema de la guía:
      status, supplier, document, amounts, classifications[],
      confidence, flags, audit, system_improvement.
    """
    if rules is None:
        rules = load_rules()

    try:
        d_from = _dt.strptime(period_from, "%Y-%m-%d").date()
        d_to = _dt.strptime(period_to, "%Y-%m-%d").date()
    except ValueError as e:
        raise PygError(f"Fechas inválidas: {period_from} / {period_to}") from e
    if d_from > d_to:
        raise PygError(f"period_from > period_to: {period_from} > {period_to}")

    documents: list[dict] = []
    seen_fingerprints: set[tuple] = set()
    audit_decisions = {"pass": 0, "review": 0, "non_pyg": 0,
                        "duplicate_blocked": 0}

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
                if not src.startswith(cuenta.lower()):
                    continue
        amount = _amount_eur(r.get("total_amount"))
        vendor = (r.get("vendor_name") or r.get("vendor") or "").strip()
        cat = r.get("category_raw") or r.get("category") or ""
        concept = r.get("concept") or r.get("description") or ""

        # Intercompany → NON_PYG directo
        if _is_intercompany(vendor):
            documents.append({
                "schema_version": "liados-improvement-v2.0",
                "mode": "IMPROVE_EXISTING_SYSTEM",
                "document_id": r.get("invoice_id")
                              or f"{vendor}-{r.get('invoice_number', '')}-{d}",
                "status": "NON_PYG",
                "supplier": {"name": vendor, "tax_id": None},
                "document": {
                    "type": r.get("doc_type"),
                    "invoice_number": r.get("invoice_number"),
                    "issue_date": str(d),
                    "accounting_date": None,
                    "reporting_month": f"{d.year:04d}-{d.month:02d}",
                },
                "amounts": {
                    "net": abs(amount),
                    "vat": None,
                    "gross": abs(amount),
                },
                "classifications": [],
                "system_improvement": {
                    "issue_detected": False,
                    "issue_type": "INTERCOMPANY",
                    "proposal": None,
                    "requires_human_approval": False,
                },
                "confidence": {
                    "extraction": 1.0,
                    "classification": 1.0,
                    "audit": 1.0,
                },
                "flags": [],
                "audit": {
                    "decision": "non_pyg",
                    "notes": ["movimiento intercompany; no es gasto real"],
                },
            })
            audit_decisions["non_pyg"] += 1
            continue

        # Duplicados
        dup = detect_duplicate(
            invoice_id=r.get("invoice_id"),
            nif_cif=r.get("vendor_tax_id"),
            invoice_number=r.get("invoice_number"),
            serie=r.get("invoice_series"),
            issue_date=str(d),
            base=r.get("base_amount"),
            vat=r.get("vat_amount"),
            total=r.get("total_amount"),
            seen=seen_fingerprints,
        )
        if dup["is_duplicate"]:
            documents.append({
                "schema_version": "liados-improvement-v2.0",
                "mode": "IMPROVE_EXISTING_SYSTEM",
                "document_id": r.get("invoice_id")
                              or f"{vendor}-{r.get('invoice_number', '')}-{d}",
                "status": "DUPLICATE_BLOCKED",
                "supplier": {"name": vendor, "tax_id": r.get("vendor_tax_id")},
                "document": {
                    "type": r.get("doc_type"),
                    "invoice_number": r.get("invoice_number"),
                    "issue_date": str(d),
                },
                "amounts": {"net": abs(amount), "vat": None,
                             "gross": abs(amount)},
                "classifications": [],
                "confidence": {"extraction": 0.95, "classification": 1.0,
                                "audit": 1.0},
                "flags": ["POSSIBLE_DUPLICATE"],
                "audit": {
                    "decision": "duplicate_blocked",
                    "notes": ["fingerprint duplicado por proveedor+número"],
                },
            })
            audit_decisions["duplicate_blocked"] += 1
            continue

        # Clasificación v2.0
        cls = classify_factura_v2(
            category_raw=cat or None,
            vendor_name=vendor or None,
            concept=concept or None,
            rules=rules,
        )

        # Audit posterior (13 chequeos, guía §27)
        audit = audit_classification(cls, r, vendor, cat, concept, amount)

        # Status final
        cls_conf = cls["confidence"]["classification"]
        audit_conf = audit["confidence"]["audit"]
        # Hard flags que NO bloquean auto-clasificación (guía §26:
        # son alertas, no bloqueos cuando la evidencia es sólida).
        advisory_only = {"TAX_EXTRACTION_UNCERTAIN",
                          "UNKNOWN_DOCUMENT_TYPE"}
        blocking_flags = (
            set(cls["flags"]) | set(audit["flags"])
        ) - advisory_only

        if (cls_conf < CONFIDENCE_AUTO_CLASSIFY
                or audit_conf < CONFIDENCE_AUTO_CLASSIFY
                or blocking_flags):
            status = "MANUAL_REVIEW"
            decision = "manual_review"
            audit_decisions["review"] += 1
        else:
            status = "CLASSIFIED"
            decision = "pass"
            audit_decisions["pass"] += 1

        # Montar doc según esquema §30
        doc = {
            "schema_version": "liados-improvement-v2.0",
            "mode": "IMPROVE_EXISTING_SYSTEM",
            "document_id": r.get("invoice_id")
                          or f"{vendor}-{r.get('invoice_number', '')}-{d}",
            "status": status,
            "supplier": {
                "name": vendor,
                "tax_id": r.get("vendor_tax_id"),
            },
            "document": {
                "type": r.get("doc_type"),
                "invoice_number": r.get("invoice_number"),
                "serie": r.get("invoice_series"),
                "issue_date": str(d),
                "accounting_date": str(d),
                "reporting_month": f"{d.year:04d}-{d.month:02d}",
            },
            "amounts": {
                "net": r.get("base_amount"),
                "vat": r.get("vat_amount"),
                "gross": abs(amount),
            },
            "classifications": [
                {
                    "line_id": r.get("invoice_id") or "single",
                    "original_description": cls["original_description"],
                    "normalized_concept": cls["normalized_concept"],
                    "expense_category": cls["expense_category"],
                    "semantic_subcategory": cls["semantic_subcategory"],
                    "pyg_block": cls["pyg_block"],
                    "pyg_category": cls["pyg_category"],
                    "pyg_subcategory": cls["pyg_subcategory"],
                    "net_amount": r.get("base_amount") or abs(amount),
                    "reason": cls["reason"],
                    "evidence": cls["evidence"],
                }
            ],
            "system_improvement": {
                "issue_detected": bool(audit["improvement_proposal"]),
                "issue_type": audit["improvement_type"],
                "proposal": audit["improvement_proposal"],
                "requires_human_approval": True,
            },
            "confidence": cls["confidence"],
            "flags": list(set(cls["flags"] + audit["flags"])),
            "audit": {
                "decision": decision,
                "notes": audit["notes"],
            },
        }
        documents.append(doc)

    # Resumen
    totals = {
        "documents_total": len(documents),
        "classified": audit_decisions["pass"],
        "manual_review": audit_decisions["review"],
        "non_pyg": audit_decisions["non_pyg"],
        "duplicates_blocked": audit_decisions["duplicate_blocked"],
    }
    issues = _aggregate_issues(documents)

    return {
        "schema_version": "liados-improvement-v2.0",
        "mode": "IMPROVE_EXISTING_SYSTEM",
        "period": {"from": period_from, "to": period_to},
        "cuenta": cuenta,
        "documents": documents,
        "totals": totals,
        "audit_summary": audit_decisions,
        "issues": issues,
    }


# ── v3 (Guía v2.0 §27): Auditoría posterior (13 chequeos) ─────

def audit_classification(
    cls: dict,
    row: dict,
    vendor: str,
    cat: str,
    concept: str,
    amount: float,
) -> dict:
    """Aplica los 13 chequeos de la guía §27.

    Devuelve: {
      "flags": [<hard flags nuevas>],
      "notes": [<notas humanas>],
      "confidence": {"audit": float},
      "improvement_proposal": str | None,
      "improvement_type": str | None,
    }
    """
    flags: list[str] = []
    notes: list[str] = []
    improvement_proposal: str | None = None
    improvement_type: str | None = None

    # 1. INSUFFICIENT_CONCEPT (categoría sin línea ni concepto)
    if not cat and not concept:
        flags.append("INSUFFICIENT_CONCEPT")
        notes.append("Sin categoría ni concepto: no se puede clasificar")

    # 2. AMBIGUOUS_VENDOR (multicategoría sin concepto)
    if needs_multicategory_check(vendor) and not concept:
        flags.append("AMBIGUOUS_VENDOR")
        notes.append(
            f"vendor {vendor} es multicategoría; falta concepto"
        )

    # 3. POTENTIAL_CAPEX (palabras clave de activo durable)
    if is_capex_suspect(concept or cat):
        flags.append("POTENTIAL_CAPEX")
        notes.append("posible activo (CAPEX), no gasto corriente")
        improvement_proposal = (
            "Sugerir crear categoría CAPEX o separar como activo"
        )
        improvement_type = "CAPEX_DETECTED"

    # 4. FINANCIAL_EXPENSE (intereses)
    if is_financial_expense(concept or cat):
        flags.append("FINANCIAL_EXPENSE")
        notes.append("interés/coste financiero: fuera de EBITDA")
        improvement_proposal = (
            "Mover fuera de EBITDA en el PYG; OUTSIDE_VIDEO_PYG"
        )
        improvement_type = "FINANCIAL_OUTSIDE_EBITDA"

    # 5. TOTAL_MISMATCH (base+iva ≠ total cuando están los 3 campos)
    base = row.get("base_amount")
    vat = row.get("vat_amount")
    if base is not None and vat is not None and amount:
        diff = abs((base + vat) - abs(amount))
        if diff > 0.05:
            flags.append("TOTAL_MISMATCH")
            notes.append(
                f"base+iva={base+vat:.2f} ≠ total={abs(amount):.2f}"
            )

    # 6. UNKNOWN_TAX / TAX_EXTRACTION_UNCERTAIN
    if amount and (base is None or vat is None):
        flags.append("TAX_EXTRACTION_UNCERTAIN")
        notes.append(
            "no se pudo extraer IVA/base; PYG debe ir SIN IVA"
        )

    # 7. UNMATCHED_CREDIT_NOTE (categoría devolución sin factura original)
    if cat and cat.lower() in ("devolucion", "abono", "abonos",
                                "retorno", "factura rectificativa"):
        if not row.get("original_invoice_id"):
            flags.append("UNMATCHED_CREDIT_NOTE")
            notes.append(
                "abono sin factura original vinculada"
            )

    # 8. CROSS_PERIOD_MATERIAL (servicio que cubre varios meses)
    if row.get("cross_period") is True:
        flags.append("CROSS_PERIOD_MATERIAL")
        notes.append("servicio cross-period; revisar periodificación")

    # 9. UNKNOWN_CATEGORY_MAPPING
    if cls.get("expense_category") == "Otros" and "UNKNOWN_CATEGORY_MAPPING" in cls["flags"]:
        flags.append("UNKNOWN_CATEGORY_MAPPING")
        notes.append(
            "categoría operativa no resoluble automáticamente"
        )
        improvement_proposal = (
            "Proponer manualmente la categoría operativa correcta"
        )
        improvement_type = "UNCLEAR_CATEGORY"

    # 10. MIXED_LINES_UNRESOLVED (vendor multicategoría + concepto ambiguo)
    if needs_multicategory_check(vendor) and concept:
        # Si el concepto no encaja con el bucket asignado, flag
        con_n = _norm_accents((concept or cat or "")).lower()
        if cls["bucket"] == "comisiones" and any(
            k in con_n for k in ("visibilidad", "campana", "promocion",
                                  "publicidad")
        ):
            flags.append("MIXED_LINES_UNRESOLVED")
            notes.append(
                "vendor comisiones con concepto de visibilidad → "
                "debería ir a marketing"
            )
            improvement_proposal = (
                "Reclasificar como Marketing y Publicidad"
            )
            improvement_type = "VENDOR_BUCKET_MISMATCH"
        if cls["bucket"] in ("aprovisionamientos", "otros_gastos_produccion") \
                and any(k in con_n for k in ("publicidad", "carteleria",
                                              "promocional")):
            flags.append("MIXED_LINES_UNRESOLVED")
            notes.append(
                "Rotapel/Envapro con concepto publicitario → "
                "Marketing, no Packaging"
            )
            improvement_proposal = (
                "Reclasificar como Marketing y Publicidad"
            )
            improvement_type = "VENDOR_BUCKET_MISMATCH"

    # 11. POSSIBLE_DUPLICATE — ya se chequea arriba, no duplicamos
    # 12. UNKNOWN_DOCUMENT_TYPE
    if not row.get("doc_type"):
        notes.append("doc_type ausente; no impide clasificación")

    # 13. coherencia histórica (no la aplicamos aquí; saldría de un
    #     estado externo mantenido por la app)

    # Confianza auditor
    audit_conf = 0.95
    # Flags advisory no degradan la confianza (son anotaciones, no
    # alertas duras para el auditor).
    hard_for_audit = [f for f in flags
                       if f not in ("TAX_EXTRACTION_UNCERTAIN",
                                     "UNKNOWN_DOCUMENT_TYPE")]
    if hard_for_audit:
        audit_conf -= 0.20 * len(hard_for_audit)
    audit_conf = max(audit_conf, 0.50)

    return {
        "flags": flags,
        "notes": notes,
        "confidence": {"audit": round(audit_conf, 3)},
        "improvement_proposal": improvement_proposal,
        "improvement_type": improvement_type,
    }


def _aggregate_issues(documents: list[dict]) -> list[dict]:
    """Cuenta flags duros por tipo y devuelve issues agregados."""
    flag_counts: dict[str, int] = {}
    for d in documents:
        for f in d.get("flags", []):
            flag_counts[f] = flag_counts.get(f, 0) + 1

    out: list[dict] = []
    for f in HARD_FLAGS:
        cnt = flag_counts.get(f, 0)
        if cnt > 0:
            out.append({
                "level": "warn",
                "code": f,
                "message": f"{f}: {cnt} documentos afectados",
            })
    return out



# ── v4 (P0.1): build_pyg_canonical ───────────────────────────────────
# Jerarquía EXACTA del cliente (P0.1, P0.2, P0.3, P0.4, P0.5, P0.6, P0.9)
# Esta función reemplaza la versión jerárquica de build_pyg con la
# estructura de 4 dimensiones independientes:
#   - PYG (jerarquía financiera)
#   - Categoría analítica (dimensión)
#   - Proveedor (dimensión)
#   - Canal (dimensión)
# Mantenemos `build_pyg` original 100% compatible (la app.py actual
# sigue usándola); `build_pyg_canonical` es la nueva API.

def _canonical_sub_aprovisionamientos(
    bucket: str, cat: str | None, vendor: str | None,
    concept: str | None = None, description: str | None = None,
) -> str:
    """Sub-categoría canónica de Aprovisionamientos.

    Resolución:
      1. Si concept/description contiene palabras de bebida (refresco,
         coca, pepsi, zumos, cerveza, vino, agua embotellada) → Bebida.
      2. Si concept/description contiene palabras de packaging
         (cajas, bolsas, envases, vasos, tapas, takeaway, delivery) →
         Packaging.
      3. Si category_raw ya marca Bebida/Packaging → Bebida/Packaging.
      4. Si vendor sugiere packaging (Rotapel, Envapro, Envases para
         Profesionales) → Packaging.
      5. Default → Alimentación.

    Esto evita que 55 facturas de Makro (todas 'Alimentación') bloqueen
    el sub-desglose Bebida/Packaging que existe conceptualmente.
    """
    cat_l = (cat or "").strip().lower()
    ven_l = (vendor or "").strip().lower()
    con_l = ((concept or "") + " " + (description or "")).strip().lower()

    BEBI = ("bebida", "refresco", "refrescos", "coca", "pepsi", "fanta",
            "zumo", "zumos", "cerveza", "vino", "agua embotellada", "drink")
    PACK = ("packaging", "cajas", "bolsas", "envase", "envases", "vasos",
            "tapas", "recipientes", "envoltorios", "takeaway", "delivery")
    ALI  = ("alimento", "alimentos", "carne", "pescado", "verdura", "fruta",
            "panader", "lacteo", "lácteo", "queso", "aceite", "salsa",
            "comida", "mercader", "mercanc", "materia prima")

    # 1) Bebida por concepto
    if any(k in con_l for k in BEBI):
        return "Bebida"
    if cat_l in ("bebida", "drink", "bebidas"):
        return "Bebida"
    if any(k in ven_l for k in ("coca", "pepsi", "fanta")):
        return "Bebida"

    # 2) Packaging por concepto
    if any(k in con_l for k in PACK):
        return "Packaging"
    if cat_l in ("packaging", "envases"):
        return "Packaging"
    if any(k in ven_l for k in ("rotapel", "envapro", "envases",
                                 "packaging")):
        return "Packaging"

    # 3) Si concept sugiere alimentación explícitamente
    if any(k in con_l for k in ALI):
        return "Alimentación"

    # 4) Default: Alimentación
    return "Alimentación"


def _canonical_sub_comisiones(vendor: str | None) -> str:
    """Sub-categoría canónica de Comisiones: Glovo / Uber / LastShop / Just Eat / Otros."""
    ven_l = (vendor or "").strip().lower()
    if "glovo" in ven_l:
        return "Glovo"
    if "uber" in ven_l:
        return "Uber"
    if "last" in ven_l and ("app" in ven_l or "shop" in ven_l):
        return "LastShop"
    if "just" in ven_l and "eat" in ven_l:
        return "Just Eat"
    return "Otros"


def _canonical_sub_otros_gastos(
    bucket: str, cat: str | None, vendor: str | None
) -> str:
    """Mapea a: Servicios y Suministros / Publicidad y Marketing / Gastos Generales.

    Reglas (P0.3):
    - Publicidad y Marketing: vendor o categoría con 'marketing', 'publicidad',
      'meta ads', 'google ads', 'visibilidad', 'campana', 'rotapel/Envapro
      con concepto publicitario'.
    - Servicios y Suministros: bucket 'servicios' o categorías de Suministros
      (Luz, Agua, Internet, Alquiler, Asesoría, etc.).
    - Gastos Generales: el resto (Material oficina, Reparación, Seguros,
      Software, Impuestos, Bancarios, etc.).
    """
    cat_l = (cat or "").strip().lower()
    ven_l = (vendor or "").strip().lower()

    # Marketing primero
    if "marketing" in cat_l or "publicidad" in cat_l or "ads" in cat_l:
        return "Publicidad y Marketing"
    if "visibilidad" in ven_l or "campana" in ven_l or "marketing" in ven_l:
        return "Publicidad y Marketing"

    # Servicios y Suministros (no marketing)
    if "suministr" in cat_l or "luz" in cat_l or "agua" in cat_l or "alquiler" in cat_l:
        return "Servicios y Suministros"
    if any(k in ven_l for k in [
        "iberdrola", "endesa", "naturgy", "aqualia", "movistar", "vodafone",
        "orange", "telef", "hermanos tonda", "propietario",
    ]):
        return "Servicios y Suministros"

    # Gastos Generales (catch-all)
    return "Gastos Generales"


def build_pyg_canonical(
    rows: Iterable[dict],
    period_from: str,
    period_to: str,
    cuenta: str | None = None,
    rules: dict | None = None,
) -> dict:
    """PYG jerárquico canónico (P0.1).

    Devuelve:
        {
          "period": {"from": ..., "to": ...},
          "cuenta": ...,
          "report_status": "RECONCILED" | "RECONCILED_WITH_WARNINGS" |
                           "INVALID_RECONCILIATION",
          "totals": {
            "ventas_netas", "margen_bruto", "mc", "ebitda",
            "ebit", "resultado_ejercicio", ...
          },
          "lines": [
            {"code", "label", "value", "pct", "level", "kind", "children"},
          ],
          "drilldown": {
            "proveedores": [{"name", "value", "pyg_path", "facturas"}],
            "categorias": [{"name", "value", "pyg_path"}],
            "canales": [{"name", "value", "pyg_path"}],
          },
          "issues": [...],
          "reconciliation": {"status", "errors", "warnings", "derived"},
        }

    Esta función:
    - Aplica el árbol EXACTO del PYG canónico (P0.1).
    - NO mezcla categorías con sub-categorías PYG (P0.3).
    - NO usa canales como categorías PYG (P0.8).
    - Aísla IVA fuera del PYG (P0.4).
    - Reconcilía MBruto, MC, EBITDA (P0.5, P0.6).
    - Sin fila "Beneficio" que duplica MC (P0.9).
    """
    if rules is None:
        rules = load_rules()

    try:
        d_from = _dt.strptime(period_from, "%Y-%m-%d").date()
        d_to = _dt.strptime(period_to, "%Y-%m-%d").date()
    except ValueError as e:
        raise PygError(f"Fechas inválidas: {period_from} / {period_to}") from e
    if d_from > d_to:
        raise PygError(f"period_from > period_to: {period_from} > {period_to}")

    # Limpiar filas
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
                if not src.startswith(cuenta.lower()):
                    continue
        amount = _amount_eur(r.get("total_amount"))
        clean_rows.append({
            "date": d,
            "amount": amount,
            "category": r.get("category_raw") or r.get("category") or "",
            "vendor": r.get("vendor_name") or r.get("vendor") or "",
            "channel": r.get("channel") or r.get("canal") or "",
            "iva": r.get("iva_amount") or r.get("vat") or 0.0,
            "base": r.get("base_amount") or r.get("net") or None,
            "concept": r.get("concept") or "",
            "description": r.get("description") or "",
        })

    # ── Clasificar filas en bloques PYG canónicos ─────────────
    # Cada fila → (pyg_block, pyg_subcategory, contribution_to_pyg)
    # Bloques canónicos:
    #   ventas, aprovisionamientos, comisiones, personal,
    #   servicios_y_suministros, publicidad_y_marketing, gastos_generales,
    #   amortizacion, resultado_financiero, impuesto_beneficios,
    #   fuera_pyg (NON_PYG, CAPEX, INTERCOMPANY, IVA, manual_review)
    ventas_brutas = 0.0
    descuentos = 0.0
    devoluciones = 0.0
    alimentos = 0.0
    bebidas = 0.0
    packaging = 0.0
    com_glovo = 0.0
    com_uber = 0.0
    com_lastshop = 0.0
    com_justeat = 0.0
    com_otros = 0.0
    personal = 0.0
    servicios_y_suministros = 0.0
    publicidad_y_marketing = 0.0
    gastos_generales = 0.0
    amortizacion = 0.0
    resultado_financiero = 0.0
    impuesto_beneficios = 0.0
    iva_total = 0.0
    bloqueado_pyg = 0.0
    capex_bloqueado = 0.0  # POTENTIAL_CAPEX → cola de revisión
    intercompany_bloqueado = 0.0  # NON_PYG → fuera del PYG

    # Drill-down por dimensión
    proveedores: dict[str, dict] = {}  # name → {value, facturas, pyg_paths}
    categorias: dict[str, dict] = {}  # cat → {value, pyg_paths}
    canales: dict[str, dict] = {}  # canal → {value, pyg_paths}

    for r in clean_rows:
        cat = r["category"]
        vendor = r["vendor"]
        amount = r["amount"]
        base = r["base"]
        iva = r["iva"]
        channel = r["channel"].strip() or "Sin canal"

        if iva and iva > 0:
            # iva puede venir como Decimal de la BD
            iva_total += float(abs(iva))

        # ── Ingresos / descuentos / devoluciones ──
        if _is_venta(cat) and amount > 0:
            ventas_brutas += amount
            _track_dim(categorias, "Ventas", amount, "ventas")
            _track_dim(canales, channel, amount, "ventas")
            _track_dim(proveedores, "Ventas clientes", amount, "ventas")
            continue
        if _is_descuento(cat) and amount > 0:
            descuentos += amount
            continue
        if _is_devolucion(cat) and amount > 0:
            devoluciones += amount
            continue

        # ── Gastos ──
        if not _is_gasto(amount, cat):
            continue
        if amount <= 0.005:
            continue
        if _is_intercompany(vendor):
            intercompany_bloqueado += float(abs(amount))
            continue

        # Si tiene IVA extraído, usar base_amount como base imponible real
        # (sin IVA). Si no, usar amount como base.
        # OJO: la BD devuelve Decimal, no float — convertir explícitamente.
        net = float(abs(base)) if base is not None else float(abs(amount))

        bucket = classify_factura(cat, vendor, rules=rules)
        concept = r["concept"]
        description = r["description"]
        sub = (_canonical_sub_aprovisionamientos(bucket, cat, vendor,
                                                 concept, description)
               if bucket == "aprovisionamientos"
               else _canonical_sub_comisiones(vendor)
               if bucket == "comisiones"
               else _canonical_sub_otros_gastos(bucket, cat, vendor))

        # CAPEX → POTENTIAL_CAPEX (cola de revisión, NO OPEX)
        if is_capex_suspect(cat) or is_capex_suspect(vendor):
            capex_bloqueado += net
            continue
        # Financiero → fuera de EBITDA
        if is_financial_expense(cat) or is_financial_expense(vendor):
            resultado_financiero += net
            continue

        # Bucket → bloque PYG canónico
        if bucket == "aprovisionamientos":
            if sub == "Alimentación":
                alimentos += net
            elif sub == "Bebida":
                bebidas += net
            elif sub == "Packaging":
                packaging += net
            else:
                alimentos += net  # fallback
        elif bucket == "comisiones":
            if sub == "Glovo":
                com_glovo += net
            elif sub == "Uber":
                com_uber += net
            elif sub == "LastShop":
                com_lastshop += net
            elif sub == "Just Eat":
                com_justeat += net
            else:
                com_otros += net
        elif bucket == "personal":
            personal += net
        elif bucket == "servicios":
            servicios_y_suministros += net
        elif bucket == "otros_gastos":
            if sub == "Servicios y Suministros":
                servicios_y_suministros += net
            elif sub == "Publicidad y Marketing":
                publicidad_y_marketing += net
            else:
                gastos_generales += net
        elif bucket == "otros_gastos_produccion":
            # '4) Otros gastos de producción' del vídeo anterior.
            # Por la nueva spec, se reagrupa en 'Otros gastos de explotación'
            # (Gastos Generales).
            gastos_generales += net
        else:
            # Catch-all
            gastos_generales += net

        # Track dimensiones
        _track_dim(proveedores, vendor, net,
                   "PYG " + _bucket_to_pyg_block(bucket))
        _track_dim(categorias, cat or "Sin categoría", net,
                   "PYG " + _bucket_to_pyg_block(bucket))
        _track_dim(canales, channel, net,
                   "PYG " + _bucket_to_pyg_block(bucket))

    # ── Construir PygBreakdown y reconciliar ────────────────
    import importlib
    try:
        _pr = importlib.import_module("pyg_reconciliation")
    except (ImportError, ModuleNotFoundError):
        try:
            _pr = importlib.import_module("dashboard.pyg_reconciliation")
        except (ImportError, ModuleNotFoundError):
            _pr = importlib.import_module(".pyg_reconciliation", __name__)
    PygBreakdown = _pr.PygBreakdown
    reconcile = _pr.reconcile
    build_breakdown_from_classified = _pr.build_breakdown_from_classified
    RECON_OK = _pr.RECON_OK
    RECON_WARN = _pr.RECON_WARN
    RECON_FAIL = _pr.RECON_FAIL
    ventas_netas = _pr.ventas_netas
    aprovisionamientos_total = _pr.aprovisionamientos_total
    comisiones_total = _pr.comisiones_total
    otros_gastos_explotacion_total = _pr.otros_gastos_explotacion_total
    margen_bruto = _pr.margen_bruto
    mc = _pr.mc
    ebitda = _pr.ebitda
    ebit = _pr.ebit
    resultado_antes_impuestos = _pr.resultado_antes_impuestos
    resultado_ejercicio = _pr.resultado_ejercicio

    # Construir breakdown desde los inputs acumulados
    b = PygBreakdown(
        ventas_brutas=ventas_brutas,
        descuentos=descuentos,
        devoluciones=devoluciones,
        alimentacion=alimentos,
        bebida=bebidas,
        packaging=packaging,
        comision_glovo=com_glovo,
        comision_uber=com_uber,
        comision_lastshop=com_lastshop,
        comision_just_eat=com_justeat,
        comision_otros=com_otros,
        personal_total=personal,
        servicios_y_suministros=servicios_y_suministros,
        publicidad_y_marketing=publicidad_y_marketing,
        gastos_generales=gastos_generales,
        amortizacion=amortizacion,
        resultado_financiero=resultado_financiero,
        impuesto_beneficios=impuesto_beneficios,
        iva_total=iva_total,
        bloqueado_pyg=bloqueado_pyg,
        capex_bloqueado=capex_bloqueado,
        intercompany_bloqueado=intercompany_bloqueado,
    )

    r = reconcile(b)

    # ── Construir jerarquía con la estructura del cliente ─────────
    lines: list[dict] = []

    def add(code, label, value, level=0, kind="line", pct=None,
            children=None, highlight=None):
        lines.append({
            "code": code, "label": label, "value": round(value, 2),
            "pct": pct, "level": level, "kind": kind,
            "children": children or [],
            "highlight": highlight,
        })

    # ── Ingresos ──
    if ventas_brutas > 0:
        add("ventas_brutas", "Ventas brutas", ventas_brutas, level=0, kind="data")
    if descuentos > 0:
        add("descuentos", "Descuentos", -descuentos, level=0, kind="data")
    if devoluciones > 0:
        add("devoluciones", "Devoluciones", -devoluciones, level=0, kind="data")
    add("ventas_netas", "Ventas N-Descuentos", ventas_netas(b),
        level=0, kind="subtotal", highlight="yellow",
        pct=1.0 if ventas_netas(b) > 0 else None)

    # ── Aprovisionamientos ──
    if aprovisionamientos_total(b) > 0.001:
        children = []
        if alimentos > 0.001:
            children.append({"label": "Alimentación", "value": round(alimentos, 2)})
        if bebidas > 0.001:
            children.append({"label": "Bebida", "value": round(bebidas, 2)})
        if packaging > 0.001:
            children.append({"label": "Packaging", "value": round(packaging, 2)})
        add("aprovisionamientos", "Aprovisionamientos",
            aprovisionamientos_total(b), level=1, kind="section",
            pct=aprovisionamientos_total(b) / ventas_netas(b)
            if ventas_netas(b) else 0.0,
            children=children)

    # ── Margen Bruto ──
    add("margen_bruto", "Margen Bruto", margen_bruto(b),
        level=0, kind="subtotal", highlight="yellow",
        pct=margen_bruto(b) / ventas_netas(b) if ventas_netas(b) else 0.0)

    # ── Comisiones ──
    if comisiones_total(b) > 0.001:
        children = []
        if com_glovo > 0.001:
            children.append({"label": "Glovo", "value": round(com_glovo, 2)})
        if com_uber > 0.001:
            children.append({"label": "Uber", "value": round(com_uber, 2)})
        if com_lastshop > 0.001:
            children.append({"label": "LastShop",
                              "value": round(com_lastshop, 2)})
        if com_justeat > 0.001:
            children.append({"label": "Just Eat",
                              "value": round(com_justeat, 2)})
        if com_otros > 0.001:
            children.append({"label": "Otros",
                              "value": round(com_otros, 2)})
        add("comisiones", "Comisiones", comisiones_total(b),
            level=1, kind="section",
            pct=comisiones_total(b) / ventas_netas(b)
            if ventas_netas(b) else 0.0,
            children=children)

    # ── Margen de Contribución ──
    add("mc", "Margen de Contribución", mc(b),
        level=0, kind="subtotal", highlight="yellow",
        pct=mc(b) / ventas_netas(b) if ventas_netas(b) else 0.0)

    # ── Personal ──
    if personal > 0.001:
        add("personal", "Personal", personal, level=1, kind="section",
            pct=personal / ventas_netas(b) if ventas_netas(b) else 0.0)

    # ── Otros gastos de explotación ──
    if otros_gastos_explotacion_total(b) > 0.001:
        children = []
        if servicios_y_suministros > 0.001:
            children.append({"label": "Servicios y Suministros",
                              "value": round(servicios_y_suministros, 2)})
        if publicidad_y_marketing > 0.001:
            children.append({"label": "Publicidad y Marketing",
                              "value": round(publicidad_y_marketing, 2)})
        if gastos_generales > 0.001:
            children.append({"label": "Gastos Generales",
                              "value": round(gastos_generales, 2)})
        add("otros_gastos_explotacion", "Otros gastos de explotación",
            otros_gastos_explotacion_total(b), level=1, kind="section",
            pct=otros_gastos_explotacion_total(b) / ventas_netas(b)
            if ventas_netas(b) else 0.0,
            children=children)

    # ── EBITDA ──
    add("ebitda", "EBITDA", ebitda(b),
        level=0, kind="kpi", highlight="green",
        pct=ebitda(b) / ventas_netas(b) if ventas_netas(b) else 0.0)

    # ── Capa posterior: Amortización, EBIT, Financiero, RAI, IS, Resultado ──
    if amortizacion > 0.001:
        add("amortizacion", "Amortización", amortizacion,
            level=1, kind="data")
    if resultado_financiero > 0.001:
        add("resultado_financiero", "Resultado financiero",
            -resultado_financiero, level=1, kind="data")
    if amortizacion > 0.001 or resultado_financiero > 0.001:
        add("ebit", "EBIT", ebit(b),
            level=0, kind="subtotal", highlight="yellow",
            pct=ebit(b) / ventas_netas(b) if ventas_netas(b) else 0.0)
    if resultado_financiero > 0.001 or amortizacion > 0.001:
        add("resultado_antes_impuestos", "Resultado antes de impuestos",
            resultado_antes_impuestos(b), level=0, kind="subtotal",
            highlight="yellow",
            pct=resultado_antes_impuestos(b) / ventas_netas(b)
            if ventas_netas(b) else 0.0)
    if impuesto_beneficios > 0.001:
        add("impuesto_beneficios", "Impuesto sobre beneficios",
            -impuesto_beneficios, level=1, kind="data")
        add("resultado_ejercicio", "Resultado del ejercicio",
            resultado_ejercicio(b), level=0, kind="kpi",
            highlight="green",
            pct=resultado_ejercicio(b) / ventas_netas(b)
            if ventas_netas(b) else 0.0)

    return {
        "period": {"from": period_from, "to": period_to},
        "cuenta": cuenta,
        "report_status": r.status,
        "totals": {
            "ventas_brutas": round(ventas_brutas, 2),
            "descuentos": round(descuentos, 2),
            "devoluciones": round(devoluciones, 2),
            "ventas_netas": round(ventas_netas(b), 2),
            "aprovisionamientos": round(aprovisionamientos_total(b), 2),
            "margen_bruto": round(margen_bruto(b), 2),
            "comisiones": round(comisiones_total(b), 2),
            "mc": round(mc(b), 2),
            "personal": round(personal, 2),
            "otros_gastos_explotacion":
                round(otros_gastos_explotacion_total(b), 2),
            "ebitda": round(ebitda(b), 2),
            "amortizacion": round(amortizacion, 2),
            "ebit": round(ebit(b), 2),
            "resultado_financiero": round(resultado_financiero, 2),
            "resultado_antes_impuestos": round(resultado_antes_impuestos(b), 2),
            "impuesto_beneficios": round(impuesto_beneficios, 2),
            "resultado_ejercicio": round(resultado_ejercicio(b), 2),
            "iva_total": round(iva_total, 2),
            "bloqueado_pyg": round(bloqueado_pyg, 2),
            "capex_bloqueado": round(capex_bloqueado, 2),
            "intercompany_bloqueado": round(intercompany_bloqueado, 2),
        },
        "lines": lines,
        "drilldown": {
            "proveedores": sorted(proveedores.values(),
                                  key=lambda d: -d["value"])[:20],
            "categorias": sorted(categorias.values(),
                                 key=lambda d: -d["value"])[:20],
            "canales": sorted(canales.values(),
                              key=lambda d: -d["value"])[:20],
        },
        "issues": [],
        "reconciliation": {
            "status": r.status,
            "errors": r.errors,
            "warnings": r.warnings,
            "derived": r.derived,
        },
        "rows_used": len(clean_rows),
    }


def _track_dim(store, key, value, pyg_path):
    """Agrega valor en una dimensión (proveedor / categoría / canal)."""
    if key not in store:
        store[key] = {"name": key, "value": 0.0, "pyg_paths": set()}
    store[key]["value"] += value
    store[key]["pyg_paths"].add(pyg_path)


# Inyectar helper como atributo del módulo para que build_pyg_canonical
# pueda usarlo. (Python permite esto en runtime.)
import sys as _sys
_sys.modules[__name__]._track_dim = _track_dim
_sys.modules[__name__]._bucket_to_pyg_block = lambda b: {
    "aprovisionamientos": "Aprovisionamientos",
    "comisiones": "Comisiones",
    "personal": "Personal",
    "servicios": "Servicios y Suministros",
    "otros_gastos": "Otros gastos de explotación",
    "otros_gastos_produccion": "Otros gastos de explotación",
}.get(b, b)
