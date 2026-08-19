"""
desglose_pyg_rules.py — Reglas de clasificación para el PYG jerárquico.

v1 (2026-07-21): Tabla de reglas externalizable (YAML) con fallback a
constantes internas. Permite override por cliente vía ~/.liados/pyg_rules.yaml
sin tocar código.

v2 (2026-08-19): Ampliado con los buckets reales del vídeo del cliente
(Resumen Ejecutivo PYG):
  1) Aprovisionamientos (Food cost)
  2) Comisiones
  3) Personal
  4) Otros gastos de producción
  5) Servicios y Suministros     ← sub-nodos: Alquiler, Luz, Agua, Internet,
                                       Carbón, Asesoría lab, Máquina del agua,
                                       Gasolina, etc.
  6) Otros gastos de explotación ← sub-nodos: Publicidad y Marketing, Material,
                                       Reparación y mantenimiento, Suministros,
                                       Gestión administrativa, Servicios de
                                       lavandería, Otros.

Cada regla mapea un bucket PYG a condiciones sobre los campos `category_raw`
y `vendor_name` de cada factura. Las reglas se evalúan en OR: una factura
entra en el PRIMER bucket cuya condición se cumpla (orden = prioridad).
Si no entra en ninguno, va a `otros_gastos` (catch-all).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


# Orden = prioridad. Una factura se asigna al PRIMER bucket que case.
PygBucket = str  # Literal type, see BUCKETS

BUCKETS: tuple[str, ...] = (
    "aprovisionamientos",          # 1) Food cost
    "comisiones",                  # 2) Comisiones marketplaces
    "personal",                    # 3) Personal / nóminas
    "otros_gastos_produccion",     # 4) Otros gastos directos de producción
    "servicios",                   # 5) Servicios y Suministros (estructura)
    "otros_gastos",                # 6) Otros gastos de explotación (catch-all)
)


# Reglas por defecto. v2: basadas en 511 facturas reales del VPS.
# Categorías y vendors verificados con /tmp/probe_liados2.py:
#   - 'Suministros' (181) y 'suministros' (80) son la categoría con más gasto
#     (85.945€) → contiene TANTO food cost (Makro, Alipensa, Indalpesa,
#     Mercadona, GGM Gastro) COMO envases (Envases para Profesionales,
#     Rotapel) COMO materiales oficina (DIGALVI).
#   - 'hosteleria' (68) → Makro, Alipensa, Mercadona, GGM Gastro, etc.
#     Equivale a food cost también.
#
# Reglas refinadas con vendor_regex para afinar dentro de la categoría
# 'Suministros' (que es cajón de sastre).
DEFAULT_RULES: dict[str, dict[str, list[str]]] = {
    "aprovisionamientos": {
        "categories": [
            "Alimentación", "Bebida", "Packaging", "Materias Primas",
            "Suministros cocina", "Food cost", "Mercancía", "Mercaderia",
            "Comida", "Drink", "Materia prima",
            "hosteleria", "Hostelería",
            # NOTA: 'Restauración y Hostelería' lo dejamos FUERA porque
            # algunos vendors (Glovo, Uber Eats) lo llevan en su category_raw
            # cuando la factura la emite el restaurante. Esos casos los
            # captura la regla vendor_regex de "comisiones".
        ],
        "vendors_any": [
            # Distribución alimentaria
            "Makro", "Makro Málaga", "Makro Distribucion Mayorista",
            "MAKRO DISTRIBUCION MAYORISTA",
            "Alimentación Peninsular", "ALIMENTACION PENINSULAR",
            "Alipensa", "Indalpesa", "INDALPESA",
            "Indalica de Pescados", "INDALICA DE PESCADOS",
            "Indalica", "Pescados Indalica",
            "Mercadona", "MERCADONA", "Mercadona S.A.",
            "GGM Gastro", "Ibergastro", "Transgourmet",
            "ATLANTA FRUTAS", "MEDITERRANEA DE ALIMENTACION",
            "Pedro Diaz", "RICO LOPEZ",
            "Hotel Apartamentos Miguel Sánchez",
            "Ragatex", "FUTURE IS AN ATTITUDE",
            "MEDIALI COFFEE",
            "Luis Adrian Aparicio Torrejon",
            "Unicom SAS", "Unicom", "UNICOM SAS",
            "FUTURE IS AN ATTITUDE",
        ],
        # Catergorización dentro de "Suministros": si el vendor es claramente
        # de alimentación, va a aprovisionamientos aunque la categoría diga
        # "Suministros".
        "vendor_regex": [
            r".*makro.*", r".*alipensa.*", r".*alimentation.*",
            r".*indalpesa.*", r".*indalica.*", r".*pescado.*",
            r".*mercadona.*", r".*ggm.*",
            r".*ibergastro.*", r".*transgourmet.*",
            r".*atlanta.*frutas.*", r".*mediterranea.*alimen.*",
            r".*pedro.*diaz.*", r".*rico.*lopez.*",
            r".*unicom.*", r".*future.*is.*an.*attitude.*",
        ],
    },
    "comisiones": {
        "categories": [
            "Comisiones", "Marketplace", "Marketplaces", "Plataformas",
            "Comision", "Comisiones marketplace",
        ],
        "vendors_any": [
            "Glovo", "Glovoapp", "Glovoapp Spain Platform",
            "Uber Eats", "UberEats", "Uber",
            "LastShop", "Last Shop", "Last.app",
            "Just Eat", "JUST-EAT SPAIN", "Just-Eat",
            "Deliveroo", "PedidosYa", "DoorDash",
        ],
        # v2.1: regex más estricto para no capturar "Glovox", "LastShopping",
        # "Uber Technologies". Sólo match exacto o prefijo.
        "vendor_regex": [
            r"^uber\s*eats(\s*espa[ñn]a)?\s*s\.?l\.?$",
            r"^uber\s*espa[ñn]a\s*s\.?l\.?$",
            r"^uber$",
            r"^glovo(app)?(\s*spain)?(\s*platform)?(\s*s\.?l\.?)?$",
            r"^glovoapp\s*spain\s*platform\s*s\.?l\.?$",
            r"^last\.app$",
            r"^last\s*shop\s*,?\s*s\.?l\.?$",  # exacto, sin prefijos
            r"^lastshop\s*,?\s*s\.?l\.?$",
            r"^just[\s-]*eat(\s*spain)?\s*s\.?l\.?$",
            r".*deliveroo.*",
            r".*pedidosya.*",
            r".*doordash.*",
        ],
    },
    "personal": {
        "categories": [
            "Personal", "Nóminas", "Seguridad Social", "Sueldos",
            "Salarios", "RRHH", "HR", "nomina",
        ],
        "vendors_any": [
            "TGSS", "Seguridad Social", "Hacienda",
            "Nomina", "Payroll",
        ],
        "vendor_regex": [r".*nomina.*", r".*payroll.*", r".*tgss.*"],
    },
    "otros_gastos_produccion": {
        # Envases, packaging, material ligado a producción.
        # v2.1: incluye también "Mantenimiento" (mobiliario, reformas,
        # instalaciones) ya que el sub-nodo "Reparación y mantenimiento"
        # del Excel del cliente cabe aquí.
        "categories": [
            "Caja", "Limpieza", "Material de oficina", "Material cocina",
            "Uniformes", "Menaje", "Utensilios", "Mantenimiento cocina",
            "Insumos producción", "Producción", "Material producción",
            "Packaging", "Envases",
            "reparacion", "reparacion y mantenimiento", "reparaciones",
            "material", "gestión administrativa", "gestion administrativa",
        ],
        "vendors_any": [
            "Envases para Profesionales", "ENVASES PARA PROFESIONALES",
            "Rotapel", "ROTAPEL", "Bluco Brands",
            "HOSTELARTE", "Hostelearte",
            "Reciclados La Estrella",
            "HIELO ALMERIA",
            # Mobiliario / reformas / mantenimiento
            "Viducean Content", "Viduce Content", "VIDUCE CONTENT",
            "Creaciones Danimobel", "CREACIONES DANIMOBEL",
            "MOTOMOCION AF", "SANYSAN APPLIANCES",
            "RESTATEC", "INSTALACIONES ELECTRICAS SILCA",
            "IKEA", "LEROY MERLIN", "Leroy Merlin",
        ],
        "vendor_regex": [
            r".*envases.*", r".*rotapel.*", r".*bluco.*",
            r".*limpieza.*", r".*cocina.*", r".*packaging.*",
            r".*hostelearte.*",
            r".*viduce.*", r".*danimobel.*",
            r".*motomocion.*", r".*sanysan.*", r".*restatec.*",
            r".*instalaciones.*electric.*", r".*silca.*",
            r".*ikea.*", r".*leroy.*merlin.*",
        ],
    },
    "servicios": {
        # Servicios y Suministros del vídeo: Alquiler, Luz, Agua, Internet,
        # Carbón, Asesoría lab, Máquina del agua, Gasolina, etc.
        "categories": [
            "Alquiler", "Luz", "Agua", "Internet", "Servicios y Suministros",
            "Asesoría", "Asesoria", "Servicios profesionales",
            "Suministros", "Combustible", "Carbón", "Carbon",
            "Telecomunicaciones", "teleco", "Telecom",
        ],
        "vendors_any": [
            # Luz / energía
            "Iberdrola", "IBERDROLA CLIENTES", "Iberdrola Clientes",
            "Endesa", "Naturgy", "CYE Energía", "MET Energía",
            "Repsol", "REPSOL", "Repsol Butano", "GESTILAN",
            # Agua
            "Aqualia", "FCC Aqualia", "EFIGAS", "REDEXIS",
            # Telefonía / internet
            "Telefónica", "Movistar", "Vodafone", "Orange", "Jazztel",
            "IONOS Cloud",
            # Alquiler
            "HERMANOS TONDA", "Propietario",
            # Mantenimiento / reparaciones
            "Instalaciones Electricas Silca",
            "MOTOMOCION AF", "SANYSAN APPLIANCES",
            "RESTATEC", "CREACIONES DANIMOBEL",
            "Viducean Content", "Viduce Content", "VIDUCE CONTENT",
            "IKEA", "LEROY MERLIN", "Leroy Merlin", "IKEA A CORUÑA",
            "Digalvi", "DIGALVI",
            # Proveedor laboratorio/asesoría
            "ENTIDAD DE CONTROL Y CERTIFICACIÓN",
            "LA COCHERA STUDIO", "La Cochera Studio",
            "Proyectos y Servicios P76",
        ],
        "vendor_regex": [
            r".*iberdrola.*", r".*endesa.*", r".*naturgy.*",
            r".*vodafone.*", r".*movistar.*", r".*orange\.es.*",
            r".*alquiler.*", r".*aqualia.*", r".*redexis.*",
            r".*efigas.*", r".*repsol.*", r".*gestilan.*",
            r".*telef[oó]nica.*", r".*movistar.*",
            r".*iberdrola.*", r".*butano.*",
            r".*instalaciones.*electricas.*",
            r".*asesor.*", r".*cochera.*", r".*silca.*",
            r".*sanysan.*", r".*restatec.*",
            r".*creaciones.*danimobel.*",
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
        if rule.get("vendors_any") and any(_norm(v) == ven_n for v in rule["vendors_any"]):
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


# ── Sub-categorías canónicas por bucket (v2) ─────────────────────────
# Mapeo bucket → lista de sub-categorías usadas por la UI.
# Coinciden con la estructura jerárquica del Excel del cliente:
#   1) Aprovisionamientos → Alimentación, Bebida, Packaging, Otros
#   2) Comisiones         → Glovo, Uber, LastShop, Otros
#   3) Personal           → Nóminas, Seguridad Social, Otros
#   4) Otros Producción   → Material, Envases, Mantenimiento, Otros
#   5) Servicios y Sum.   → Alquiler, Luz, Agua, Internet, Asesoría,
#                           Gasolina / Combustible, Carbón, Otros
#   6) Otros Explotación  → Publicidad y Marketing, Oficina, Software,
#                           Impuestos, Bancarios, Seguros, Servicios Prof.,
#                           Restauración, Otros
SUBCATS_V2: dict[str, list[str]] = {
    "aprovisionamientos": [
        "Alimentación", "Bebida", "Packaging", "Otros",
    ],
    "comisiones": [
        "Glovo", "Uber", "LastShop", "Just Eat", "Otros",
    ],
    "personal": [
        "Nóminas", "Seguridad Social", "Otros",
    ],
    "otros_gastos_produccion": [
        "Material oficina", "Envases", "Mantenimiento", "Otros",
    ],
    "servicios": [
        "Alquiler", "Luz", "Agua", "Internet", "Asesoría",
        "Combustible", "Carbón", "Otros",
    ],
    "otros_gastos": [
        "Publicidad y Marketing", "Oficina", "Software",
        "Impuestos y Tasas", "Gastos Bancarios", "Seguros",
        "Servicios Profesionales", "Restauración y Hostelería", "Otros",
    ],
}


def subcat_for(bucket: str, category_raw: str | None, vendor_name: str | None) -> str:
    """Devuelve la sub-categoría canónica para una factura.

    Si no hay match específico, devuelve "Otros".
    """
    cat = _norm(category_raw)
    ven = _norm(vendor_name)

    if bucket == "servicios":
        if any(k in ven for k in ["alquiler", "hermanos tonda", "propietario"]):
            return "Alquiler"
        if any(k in ven for k in ["iberdrola", "endesa", "naturgy", "cye energia", "met energia"]):
            return "Luz"
        if any(k in ven for k in ["aqualia", "redexis", "efigas"]):
            return "Agua"
        if any(k in ven for k in ["telef", "movistar", "vodafone", "orange", "jazztel", "ionos"]):
            return "Internet"
        if any(k in ven for k in ["asesor", "cochera", "silca", "control y certificacion"]):
            return "Asesoría"
        if any(k in ven for k in ["repsol", "gestilan", "butano", "gasolina"]):
            return "Combustible"
        if cat in ("carbon", "carbn"):
            return "Carbón"
        return "Otros"

    if bucket == "otros_gastos":
        if cat in ("marketing", "marketing y publicidad", "publicidad"):
            return "Publicidad y Marketing"
        if cat in ("oficina", "material de oficina"):
            return "Oficina"
        if cat in ("software", "software y saas"):
            return "Software"
        if cat in ("impuestos y tasas",):
            return "Impuestos y Tasas"
        if cat in ("gastos bancarios",):
            return "Gastos Bancarios"
        if cat in ("seguros",):
            return "Seguros"
        if cat in ("servicios profesionales",):
            return "Servicios Profesionales"
        if cat in ("restauracion y hosteleria", "restauración y hostelería"):
            return "Restauración y Hostelería"
        return "Otros"

    if bucket == "otros_gastos_produccion":
        if "envase" in ven or "rotapel" in ven or "bluco" in ven:
            return "Envases"
        if cat in ("material de oficina", "oficina"):
            return "Material oficina"
        if any(k in ven for k in ["sanysan", "restatec", "instalaciones electricas",
                                   "danimobel"]):
            return "Mantenimiento"
        return "Otros"

    if bucket == "comisiones":
        if "glovo" in ven:
            return "Glovo"
        if "uber" in ven:
            return "Uber"
        if "last.app" in ven or "lastshop" in ven or "last shop" in ven:
            return "LastShop"
        if "just" in ven and "eat" in ven:
            return "Just Eat"
        return "Otros"

    if bucket == "personal":
        if cat in ("seguridad social",):
            return "Seguridad Social"
        if cat in ("nominas", "nomina", "sueldos", "salarios", "personal"):
            return "Nóminas"
        return "Otros"

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

    return "Otros"
