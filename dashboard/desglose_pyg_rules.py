"""
desglose_pyg_rules.py — Reglas de clasificación para el PYG jerárquico.

v1 (2026-07-21): Tabla de reglas externalizable (YAML) con fallback a
constantes internas. Permite override por cliente vía ~/.liados/pyg_rules.yaml
sin tocar código.

Cada regla mapea un bucket PYG (aprovisionamientos, comisiones, personal,
servicios, otros_gastos_produccion, otros_gastos) a condiciones sobre los
campos `category_raw` y `vendor_name` de cada factura.

Las reglas se evalúan en OR: una factura entra en el PRIMER bucket cuya
condición se cumpla (orden = prioridad). Si no entra en ninguno, va a
`otros_gastos` (catch-all).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


# Orden = prioridad. Una factura se asigna al PRIMER bucket que case.
PygBucket = str  # Literal type, see BUCKETS

BUCKETS: tuple[str, ...] = (
    "aprovisionamientos",   # 1) Food cost
    "comisiones",           # 2) Comisiones marketplaces
    "personal",             # 3) Personal / nóminas
    "otros_gastos_produccion",  # 4) Otros gastos directos de producción
    "servicios",            # 5) Servicios y Suministros (estructura)
    "otros_gastos",         # 6) Catch-all
)


# Reglas por defecto (alineadas con el Excel del cliente restaurantero
# y los verbalizados en los vídeos 1-3 del 2026-07-08).
DEFAULT_RULES: dict[str, dict[str, list[str]]] = {
    "aprovisionamientos": {
        "categories": [
            "Alimentación", "Bebida", "Packaging", "Materias Primas",
            "Suministros cocina", "Food cost", "Mercancía", "Mercaderia",
            "Comida", "Drink", "Materia prima",
        ],
        "vendors_any": [
            "Makro", "Sercodí", "Sercodi", "Indaiplesa", "Atlanta",
            "Ramillo", "Coca Cola", "Pepsi", "Bidafarma",
            "Envapro", "Envanature", "Rotapack", "Packaging Pro",
        ],
        "vendor_regex": [],
    },
    "comisiones": {
        "categories": [
            "Comisiones", "Marketplace", "Marketplaces", "Plataformas",
        ],
        "vendors_any": [
            "Glovo", "Glovoapp", "Uber Eats", "UberEats",
            "LastShop", "Last Shop", "Just Eat", "Deliveroo",
            "PedidosYa", "DoorDash",
        ],
        "vendor_regex": [r"^(?:uber|uber\s+eats(?:\s+.*)?)$", r".*deliveroo.*"],
    },
    "personal": {
        "categories": [
            "Personal", "Nóminas", "Seguridad Social", "Sueldos",
            "Salarios", "RRHH", "HR",
        ],
        "vendors_any": [
            "TGSS", "Seguridad Social", "Hacienda",
            "Nomina", "Payroll",
        ],
        "vendor_regex": [r".*nomina.*", r".*payroll.*"],
    },
    "otros_gastos_produccion": {
        "categories": [
            "Caja", "Limpieza", "Material de oficina", "Material cocina",
            "Uniformes", "Menaje", "Utensilios", "Mantenimiento cocina",
            "Insumos producción", "Producción", "Material producción",
        ],
        "vendors_any": [],
        "vendor_regex": [r".*limpieza.*", r".*cocina.*"],
    },
    "servicios": {
        "categories": [
            "Alquiler", "Luz", "Agua", "Internet", "Servicios y Suministros",
            "Asesoría", "Asesoria", "Servicios profesionales",
            "Suministros", "Combustible", "Carbón", "Carbon",
        ],
        "vendors_any": [
            "Iberdrola", "Endesa", "Naturgy", "Vodafone", "Movistar",
            "Orange", "Jazztel", "Eulen", "Asesoría X",
        ],
        "vendor_regex": [
            r".*iberdrola.*", r".*endesa.*", r".*naturgy.*",
            r".*vodafone.*", r".*movistar.*", r".*orange\.es.*",
            r".*alquiler.*",
        ],
    },
    # "otros_gastos" es el catch-all; no necesita reglas (siempre matchea).
    "otros_gastos": {
        "categories": [],
        "vendors_any": [],
        "vendor_regex": [],
    },
}


def _norm(s: str | None) -> str:
    """Normaliza para matching case/diacritics-insensitive."""
    if not s:
        return ""
    s = str(s).strip().lower()
    # Quitar acentos
    repl = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
            ("à", "a"), ("è", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u"),
            ("ñ", "n"), ("ü", "u"))
    for a, b in repl:
        s = s.replace(a, b)
    return s


def _matches_vendor_regex(vendor_norm: str, patterns: list[str]) -> bool:
    for p in patterns or []:
        try:
            if re.search(p, vendor_norm, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def classify_factura(
    category_raw: str | None,
    vendor_name: str | None,
    rules: dict[str, dict[str, list[str]]] | None = None,
) -> str:
    """Devuelve el bucket PYG al que pertenece una factura.

    Orden de evaluación = orden en `BUCKETS`. Primera coincidencia gana.
    Si nada casa, devuelve "otros_gastos".
    """
    rules = rules or DEFAULT_RULES
    cat_n = _norm(category_raw)
    ven_n = _norm(vendor_name)

    for bucket in BUCKETS:
        rule = rules.get(bucket)
        if not rule:
            continue
        if rule.get("categories") and any(_norm(c) == cat_n for c in rule["categories"]):
            return bucket
        # Las facturas reales suelen incluir razón social, país o forma
        # societaria después del nombre comercial (p.ej. Glovoapp Spain
        # Platform S.L.). La regla debe casar el nombre normalizado como
        # fragmento, no exigir igualdad literal.
        if rule.get("vendors_any") and any(
            re.search(r"(?<!\w)" + re.escape(_norm(v)) + r"(?!\w)", ven_n)
            for v in rule["vendors_any"]
        ):
            return bucket
        if _matches_vendor_regex(ven_n, rule.get("vendor_regex", [])):
            return bucket
    return "otros_gastos"


def load_rules(override_path: str | None = None) -> dict[str, dict[str, list[str]]]:
    """Carga reglas desde YAML si existe; si no, devuelve DEFAULT_RULES.

    Buscar en:
      1. override_path explícito
      2. $LIADOS_PYG_RULES (env)
      3. ~/.liados/pyg_rules.yaml
      4. /root/liados/pyg_rules.yaml (VPS)
      5. /home/dualai/liados_workspace/pyg_rules.yaml (local)
    """
    candidates = []
    if override_path:
        candidates.append(override_path)
    env = os.environ.get("LIADOS_PYG_RULES")
    if env:
        candidates.append(env)
    candidates.extend([
        str(Path.home() / ".liados" / "pyg_rules.yaml"),
        "/root/liados/pyg_rules.yaml",
        "/home/dualai/liados_workspace/pyg_rules.yaml",
        str(Path(__file__).resolve().parent.parent.parent / "pyg_rules.yaml"),
    ])
    for p in candidates:
        if p and os.path.exists(p):
            try:
                import yaml  # type: ignore
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                # Merge: default + override
                merged = {b: dict(DEFAULT_RULES.get(b, {})) for b in BUCKETS}
                for b, override in data.items():
                    if b not in merged:
                        merged[b] = {"categories": [], "vendors_any": [], "vendor_regex": []}
                    for k in ("categories", "vendors_any", "vendor_regex"):
                        if k in override:
                            merged[b][k] = list(override[k])
                return merged
            except Exception:
                # Si falla el parseo, fallback a defaults (no romper producción)
                return DEFAULT_RULES
    return DEFAULT_RULES


def all_buckets() -> tuple[str, ...]:
    return BUCKETS
