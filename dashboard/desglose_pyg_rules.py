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
  5) Servicios y Suministros
  6) Otros gastos de explotación

v3 (2026-08-19, Guía Liados v2.0): Integración con taxonomía oficial,
sinónimos, confianza (extraction/classification/audit), hard flags y
esquema JSON v2.0 (ver §30 de la guía). Se mantiene el contrato
previo (BUCKETS, classify_factura) por compatibilidad con tests
existentes; las nuevas funciones son aditivas.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


# ── Intentamos importar la taxonomía oficial ─────────────────
try:
    from .taxonomy import (
        CATEGORIES as OFFICIAL_CATEGORIES,
        SYNONYMS,
        HARD_FLAGS as OFFICIAL_HARD_FLAGS,
        MULTICATEGORY_VENDORS,
        is_capex_suspect,
        is_financial_expense,
        normalize_concept,
        is_valid_category,
        needs_multicategory_check,
    )
except (ImportError, ValueError):
    from taxonomy import (
        CATEGORIES as OFFICIAL_CATEGORIES,
        SYNONYMS,
        HARD_FLAGS as OFFICIAL_HARD_FLAGS,
        MULTICATEGORY_VENDORS,
        is_capex_suspect,
        is_financial_expense,
        normalize_concept,
        is_valid_category,
        needs_multicategory_check,
    )


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
# Categorías y vendors verificados con /tmp/probe_liados2.py.
DEFAULT_RULES: dict[str, dict[str, list[str]]] = {
    "aprovisionamientos": {
        "categories": [
            "Alimentación", "Bebida", "Packaging", "Materias Primas",
            "Suministros cocina", "Food cost", "Mercancía", "Mercaderia",
            "Comida", "Drink", "Materia prima",
            "hosteleria", "Hostelería",
            # Guía v2.0 §3: también entra lo categorizado como
            # "Restauración y Hostelería" si el CONCEPTO apunta a
            # aprovisionamientos (alimentos, bebida, packaging).
            # La sub-clasificación posterior lo afinará.
            "Restauración y Hostelería",
        ],
        "vendors_any": [
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
        "vendor_regex": [
            r"^uber\s*eats(\s*espa[ñn]a)?\s*s\.?l\.?$",
            r"^uber\s*espa[ñn]a\s*s\.?l\.?$",
            r"^uber$",
            r"^glovo(app)?(\s*spain)?(\s*platform)?(\s*s\.?l\.?)?$",
            r"^glovoapp\s*spain\s*platform\s*s\.?l\.?$",
            r"^last\.app$",
            r"^last\s*shop\s*,?\s*s\.?l\.?$",
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
        "categories": [
            "Caja", "Limpieza", "Material de oficina", "Material cocina",
            "Uniformes", "Menaje", "Utensilios", "Mantenimiento cocina",
            "Insumos producción", "Producción", "Material producción",
            "Packaging", "Envases",
        ],
        "vendors_any": [
            "Envases para Profesionales", "ENVASES PARA PROFESIONALES",
            "Rotapel", "ROTAPEL", "Bluco Brands",
            "HOSTELARTE", "Hostelearte",
            "Reciclados La Estrella",
            "HIELO ALMERIA",
        ],
        "vendor_regex": [
            r".*envases.*", r".*rotapel.*", r".*bluco.*",
            r".*limpieza.*", r".*cocina.*", r".*packaging.*",
            r".*hostelearte.*",
        ],
    },
    "servicios": {
        "categories": [
            "Alquiler", "Luz", "Agua", "Internet", "Servicios y Suministros",
            "Asesoría", "Asesoria", "Servicios profesionales",
            "Suministros", "Combustible", "Carbón", "Carbon",
            "Telecomunicaciones", "teleco", "Telecom",
        ],
        "vendors_any": [
            "Iberdrola", "IBERDROLA CLIENTES", "Iberdrola Clientes",
            "Endesa", "Naturgy", "CYE Energía", "MET Energía",
            "Repsol", "REPSOL", "Repsol Butano", "GESTILAN",
            "Aqualia", "FCC Aqualia", "EFIGAS", "REDEXIS",
            "Telefónica", "Movistar", "Vodafone", "Orange", "Jazztel",
            "IONOS Cloud",
            "HERMANOS TONDA", "Propietario",
            "Instalaciones Electricas Silca",
            "MOTOMOCION AF", "SANYSAN APPLIANCES",
            "RESTATEC", "CREACIONES DANIMOBEL",
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


# ── Vendors críticos: el vendor MANDA sobre la categoría ────────
# Cuando el vendor es uno de los marketplaces multicategoría (Glovo,
# Uber, LastShop, Just Eat), la factura es de COMISIONES sin importar
# el `category_raw` que pueda traer el parser (ej: 'Restauración y
# Hostelería' lo emite el restaurante cuando factura al marketplace).
# Esta lista es el "primer filtro" antes del loop por BUCKETS.
_MULTICATEGORY_MARKETPLACE_VENDORS: tuple[str, ...] = (
    "glovo", "glovoapp", "uber", "ubereats", "last.app", "lastshop",
    "last shop", "just eat", "justeat", "just-eat", "deliveroo",
    "pedidosya", "doordash",
)


def _is_marketplace_vendor(vendor_name: str | None) -> bool:
    """True si el vendor es un marketplace de delivery."""
    if not vendor_name:
        return False
    v = _norm(vendor_name)
    return any(m in v for m in _MULTICATEGORY_MARKETPLACE_VENDORS)


def classify_factura(
    category_raw: str | None,
    vendor_name: str | None,
    rules: dict[str, dict[str, list[str]]] | None = None,
) -> str:
    """Devuelve el bucket PYG al que pertenece una factura.

    Reglas de prioridad (de más fuerte a más débil):
      0. Si vendor es un marketplace multicategoría (Glovo, Uber, etc.)
         → SIEMPRE comisiones (el vendor manda sobre la categoría).
      1. Por cada bucket en orden:
         1a. match exacto de categoría
         1b. match exacto de vendor
         1c. regex de vendor
      2. Si nada casa → 'otros_gastos' (catch-all).

    Tests previos verifican que 'Glovoapp + Restauración' se clasifica
    como comisiones aunque la categoría diga otra cosa (es un caso real
    donde el restaurante emite la factura con cat='Restauración').
    """
    rules = rules or DEFAULT_RULES

    # 0) El vendor manda si es marketplace multicategoría (Glovo, Uber, etc.)
    #    Y la categoría NO es explícitamente Marketing/Software/Servicios/
    #    Impuestos/Bancarios/Oficina. Esto evita que "Glovo + Marketing"
    #    (visibilidad pagada) se clasifique como comisiones.
    #    Caso base: "Glovo + Restauración" → comisiones (caso del test).
    if _is_marketplace_vendor(vendor_name):
        NON_COMISION_MARKETPLACE_CATS = (
            "marketing", "marketing y publicidad", "publicidad",
            "software", "software y saas",
            "servicios profesionales", "asesoria", "asesoría",
            "impuestos", "impuestos y tasas",
            "bancarios", "gastos bancarios",
            "seguros", "alquiler",
            "oficina",
        )
        cat_n = _norm(category_raw)
        if cat_n not in NON_COMISION_MARKETPLACE_CATS:
            return "comisiones"
        # Si la categoría ES de las anteriores, el loop de buckets NO debe
        # matchear el vendor como comisiones. Hacemos skip del bucket
        # 'comisiones' en el siguiente loop.
        ven_n = _norm(vendor_name)
        for bucket in BUCKETS:
            if bucket == "comisiones":
                continue  # el vendor manda pero la categoría dice otra cosa
            rule = rules.get(bucket)
            if not rule:
                continue
            cat_n_loop = _norm(category_raw)
            if rule.get("categories") and any(
                _norm(c) == cat_n_loop for c in rule["categories"]
            ):
                return bucket
            if rule.get("vendors_any") and any(
                _norm(v) == ven_n for v in rule["vendors_any"]
            ):
                return bucket
            if _matches_vendor_regex(ven_n, rule.get("vendor_regex", [])):
                return bucket
        return "otros_gastos"

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
    """Carga reglas desde YAML si existe; si no, devuelve DEFAULT_RULES."""
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
                merged = {b: dict(DEFAULT_RULES.get(b, {})) for b in BUCKETS}
                for b, override in data.items():
                    if b not in merged:
                        merged[b] = {"categories": [], "vendors_any": [], "vendor_regex": []}
                    for k in ("categories", "vendors_any", "vendor_regex"):
                        if k in override:
                            merged[b][k] = list(override[k])
                return merged
            except Exception:
                return DEFAULT_RULES
    return DEFAULT_RULES


def all_buckets() -> tuple[str, ...]:
    return BUCKETS


# ── Sub-categorías canónicas por bucket ───────────────────────
SUBCATS_V2: dict[str, list[str]] = {
    "aprovisionamientos": ["Alimentación", "Bebida", "Packaging", "Otros"],
    "comisiones": ["Glovo", "Uber", "LastShop", "Just Eat", "Otros"],
    "personal": ["Nóminas", "Seguridad Social", "Otros"],
    "otros_gastos_produccion": ["Material oficina", "Envases",
                                  "Mantenimiento", "Otros"],
    "servicios": ["Alquiler", "Luz", "Agua", "Internet", "Asesoría",
                  "Combustible", "Carbón", "Otros"],
    "otros_gastos": ["Publicidad y Marketing", "Oficina", "Software",
                     "Impuestos y Tasas", "Gastos Bancarios", "Seguros",
                     "Servicios Profesionales",
                     "Restauración y Hostelería", "Otros"],
}


def subcat_for(bucket: str, category_raw: str | None, vendor_name: str | None) -> str:
    """Devuelve la sub-categoría canónica para una factura."""
    cat = _norm(category_raw)
    ven = _norm(vendor_name)

    if bucket == "servicios":
        if any(k in ven for k in ["alquiler", "hermanos tonda", "propietario"]):
            return "Alquiler"
        if any(k in ven for k in ["iberdrola", "endesa", "naturgy",
                                   "cye energia", "met energia"]):
            return "Luz"
        if any(k in ven for k in ["aqualia", "redexis", "efigas"]):
            return "Agua"
        if any(k in ven for k in ["telef", "movistar", "vodafone", "orange",
                                   "jazztel", "ionos"]):
            return "Internet"
        if any(k in ven for k in ["asesor", "cochera", "silca",
                                   "control y certificacion"]):
            return "Asesoría"
        if any(k in ven for k in ["repsol", "gestilan", "butano",
                                   "gasolina"]):
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
        if any(k in ven for k in ["sanysan", "restatec",
                                   "instalaciones electricas",
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


# ── v3: Esquema JSON v2.0 + confianza + hard flags (Guía §30) ─
# Las funciones siguientes son ADITIVAS. No rompen el contrato previo.

def classify_factura_v2(
    category_raw: str | None,
    vendor_name: str | None,
    concept: str | None = None,
    rules: dict | None = None,
) -> dict:
    """Devuelve el dict completo clasificación v2.0 (Guía §30) para una factura.

    Devuelve:
        {
          "expense_category": <categoría operativa oficial>,
          "semantic_subcategory": <subcategoría semántica>,
          "pyg_block": <bloque PYG>,
          "pyg_category": <categoría PYG>,
          "pyg_subcategory": <sub-subcategoría PYG>,
          "original_description": <texto crudo>,
          "normalized_concept": <concepto canónico vía SINONYMS>,
          "bucket": <bucket interno para drill-down>,
          "reason": <explicación>,
          "evidence": <lista de evidencias>,
          "confidence": {
            "extraction": float,
            "classification": float,
            "audit": float
          },
          "flags": [<hard flags detectadas>]
        }
    """
    cat = (str(category_raw) if category_raw else "").strip()
    ven = (str(vendor_name) if vendor_name else "").strip()
    con = (str(concept) if concept else "").strip()

    flags: list[str] = []
    evidence: list[str] = []

    # 1) Normalizar concepto
    normalized = normalize_concept(con or cat) or con or cat

    # 2) Bucket interno (reusamos classify_factura existente)
    bucket = classify_factura(cat or None, ven or None, rules=rules)
    subcat = subcat_for(bucket, cat or None, ven or None)

    # 3) Categoría operativa oficial
    # Mapeo inverso aproximado: si la categoría cruda coincide con
    # una de las 11 oficiales, se respeta; si no, se usa la heurística
    # bucket→categoría operativa más razonable.
    official = _map_bucket_to_official_category(bucket, cat, ven, subcat)
    if not is_valid_category(official):
        # Categoría operativa no resoluble → MANUAL_REVIEW
        flags.append("UNKNOWN_CATEGORY_MAPPING")
        official = "Otros"  # Nunca usar Otros como "papelera"; flag
        # ya advierte. La categoría final la decide un humano.

    # 4) PYG block + categoría + sub
    pyg_block, pyg_category, pyg_subcategory = _map_to_pyg(bucket, subcat)

    # 5) Detección de CAPEX / financiero / proveedores multicategoría
    if is_capex_suspect(con or cat):
        flags.append("POTENTIAL_CAPEX")
    if is_financial_expense(con or cat):
        flags.append("FINANCIAL_EXPENSE")
    if needs_multicategory_check(ven):
        if not con:
            flags.append("INSUFFICIENT_CONCEPT")
        else:
            evidence.append(
                f"vendor multicategoría {ven}: revisar concepto"
            )
            # Detección temprana del mismatch bucket vs concepto
            con_n = con.strip().lower()
            repl = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                    ("à", "a"), ("è", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u"),
                    ("ñ", "n"), ("ü", "u"))
            for a, b in repl:
                con_n = con_n.replace(a, b)
            if bucket == "comisiones" and any(
                k in con_n for k in ("visibilidad", "campana", "promocion",
                                      "publicidad", "marketing")
            ):
                flags.append("MIXED_LINES_UNRESOLVED")
            if bucket in ("aprovisionamientos",
                           "otros_gastos_produccion") and any(
                k in con_n for k in ("publicidad", "carteleria",
                                      "promocional", "marketing")
            ):
                flags.append("MIXED_LINES_UNRESOLVED")

    # 6) Confianza
    confidence = _compute_confidence(cat, ven, con, bucket, flags)

    # 7) Reason
    reason = _build_reason(cat, ven, con, bucket, subcat, official)

    return {
        "expense_category": official,
        "semantic_subcategory": subcat,
        "pyg_block": pyg_block,
        "pyg_category": pyg_category,
        "pyg_subcategory": pyg_subcategory,
        "original_description": con or cat,
        "normalized_concept": normalized,
        "bucket": bucket,
        "reason": reason,
        "evidence": evidence,
        "confidence": confidence,
        "flags": flags,
    }


def _map_bucket_to_official_category(
    bucket: str, cat: str | None, ven: str | None, subcat: str | None = None
) -> str | None:
    """Mapea bucket interno → categoría operativa oficial.

    Reglas de prioridad (de más fuerte a más débil):
    1. Si el subcat inferido es muy específico (Alquiler, Asesoría) y
       choca con cat_raw → manda subcat.
    2. Si cat_raw está en las 11 oficiales → se respeta.
    3. Match laxo case/acentos.
    4. Heurística bucket→categoría.
    """
    subcat_overrides = {
        "Alquiler": "Alquiler",
        "Asesoría": "Servicios Profesionales",
        "Internet": "Suministros",
        "Luz": "Suministros",
        "Agua": "Suministros",
    }
    if subcat and subcat in subcat_overrides:
        override = subcat_overrides[subcat]
        # Solo override si cat_raw NO es oficial o es genérico
        if not cat or _norm(cat) in ("suministros", "otros", "servicios y suministros",
                                       ""):
            return override

    if cat:
        cat_clean = cat.strip()
        # Match exacto
        if cat_clean in OFFICIAL_CATEGORIES:
            return cat_clean
        # Match laxo (case-insensitive, sin acentos)
        cat_n = _norm(cat_clean)
        for off in OFFICIAL_CATEGORIES:
            if _norm(off) == cat_n:
                return off

    # Heurística bucket → categoría operativa (sin tocar vendor)
    if bucket == "aprovisionamientos":
        return "Restauración y Hostelería"
    if bucket == "comisiones":
        return None
    if bucket == "personal":
        return None
    if bucket == "servicios":
        c = (cat or "").lower()
        v = (ven or "").lower()
        if "alquiler" in c or any(k in v for k in ("alquil", "hermanos tonda",
                                                     "propietario")):
            return "Alquiler"
        if "asesor" in c or "profesional" in c \
                or any(k in v for k in ("asesor", "cochera", "silca",
                                          "sanysan", "restatec",
                                          "danimobel", "control y certif")):
            return "Servicios Profesionales"
        return "Suministros"
    if bucket == "otros_gastos_produccion":
        c = (cat or "").lower()
        v = (ven or "").lower()
        if any(k in c for k in ("oficina", "material de oficina")):
            return "Oficina"
        if any(k in v for k in ("envase", "rotapel", "bluco")) \
                and any(k in c for k in ("packaging", "envase")):
            return "Restauración y Hostelería"
        return "Restauración y Hostelería"
    if bucket == "otros_gastos":
        # Mapeo por palabras clave del category_raw
        c = (cat or "").lower()
        if any(k in c for k in ("marketing", "publicidad", "meta ads",
                                  "google ads", "campana", "ads")):
            return "Marketing y Publicidad"
        if "software" in c or "saas" in c:
            return "Software y SaaS"
        if "seguro" in c:
            return "Seguros"
        if "banco" in c or "comision" in c:
            return "Gastos Bancarios"
        if "impuesto" in c or "tasa" in c or "licencia" in c:
            return "Impuestos y Tasas"
        if "oficina" in c:
            return "Oficina"
        if "restauracion" in c or "hostel" in c:
            return "Restauración y Hostelería"
        return None
    return None


def _map_to_pyg(bucket: str, subcat: str) -> tuple[str, str, str]:
    """Devuelve (pyg_block, pyg_category, pyg_subcategory) para un bucket."""
    if bucket == "aprovisionamientos":
        return ("GASTOS", "1) Aprovisionamientos", f"Alimentación/Bebida/Packaging > {subcat}")
    if bucket == "comisiones":
        return ("GASTOS", "2) Comisiones", f"Marketplace > {subcat}")
    if bucket == "personal":
        return ("GASTOS", "3) Personal", f"Coste laboral > {subcat}")
    if bucket == "otros_gastos_produccion":
        return ("GASTOS", "4) Otros gastos de producción", subcat)
    if bucket == "servicios":
        return ("GASTOS", "5) Servicios y Suministros", subcat)
    if bucket == "otros_gastos":
        return ("GASTOS", "6) Otros gastos de explotación", subcat)
    return ("GASTOS", "Desconocido", subcat)


def _compute_confidence(
    cat: str | None,
    ven: str | None,
    con: str | None,
    bucket: str,
    flags: list[str],
) -> dict:
    """Calcula confianza (guía §25)."""
    # Base por presencia de evidencia
    extraction = 0.90
    if cat:
        extraction += 0.05
    if con:
        extraction += 0.05
    extraction = min(extraction, 1.0)

    classification = 0.85
    if ven:
        classification += 0.05  # vendor conocido ayuda
    if con:
        classification += 0.05
    if bucket != "otros_gastos":
        classification += 0.05  # match específico
    classification = min(classification, 1.0)

    # Hard flags degradan audit
    audit = 0.95
    if flags:
        audit -= 0.20 * len(flags)
    audit = max(audit, 0.50)

    return {
        "extraction": round(extraction, 3),
        "classification": round(classification, 3),
        "audit": round(audit, 3),
    }


def _build_reason(
    cat: str | None,
    ven: str | None,
    con: str | None,
    bucket: str,
    subcat: str,
    official: str | None,
) -> str:
    """Construye una explicación humana de la clasificación."""
    parts: list[str] = []
    if cat:
        parts.append(f"cat_raw='{cat}'")
    if ven:
        parts.append(f"vendor='{ven}'")
    if con:
        parts.append(f"concepto='{con}'")
    parts.append(f"bucket={bucket}")
    parts.append(f"subcat={subcat}")
    if official:
        parts.append(f"operativa={official}")
    return "; ".join(parts) if parts else "sin evidencia"


# ── v3: Detector de duplicados (guía §16) ─────────────────────

def detect_duplicate(
    invoice_id: str | None,
    nif_cif: str | None,
    invoice_number: str | None,
    serie: str | None,
    issue_date: str | None,
    base: float | None,
    vat: float | None,
    total: float | None,
    seen: set[tuple] | None = None,
) -> dict:
    """Detecta si (proveedor fiscal + número/serie) ya existe en `seen`.

    Devuelve: {"is_duplicate": bool, "fingerprint": tuple}.
    El caller alimenta `seen` con los fingerprints anteriores.

    Importante: si el fingerprint es TODO vacío (sin NIF, sin
    invoice_number, sin serie), NO se considera duplicado (no hay
    forma de saber si dos facturas vacías son el mismo documento).
    """
    fp = (
        str(nif_cif or "").strip().lower(),
        str(invoice_number or "").strip().lower(),
        str(serie or "").strip().lower(),
    )
    # Fingerprint vacío = sin datos para identificar → no se compara.
    if fp == ("", "", ""):
        return {"is_duplicate": False, "fingerprint": fp}
    is_dup = seen is not None and fp in seen
    if seen is not None:
        seen.add(fp)
    return {"is_duplicate": is_dup, "fingerprint": fp}