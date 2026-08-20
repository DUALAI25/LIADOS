"""
taxonomy.py — Taxonomía oficial del sistema LIADOS según la Guía v2.0.

Define:
  - CATEGORIES: las 11 categorías operativas oficiales (NO modificables
    sin autorización humana explícita; ver guía §3).
  - PYG_BLOCKS: los 5 bloques del PYG observados en el vídeo del cliente
    (Aprovisionamientos, Comisiones, Personal, Otros Gastos de la
    explotación, EBITDA). Incluye además un bloque especial
    OUTSIDE_VIDEO_PYG para intereses/amortizaciones.
  - HIERARCHY: árbol jerárquico de cada categoría operativa hasta el
    nivel de sub-sub-categoría (guía §6).
  - SYNONYMS: mapeo término crudo → concepto canónico (guía §24).
  - MULTICATEGORY_VENDORS: proveedores que pueden caer en >1 categoría
    según el concepto (guía §10).
  - HARD_FLAGS: lista canónica de flags duros (guía §26).

Este módulo es DATA-ONLY (sin lógica de negocio). El motor de
clasificación vive en desglose_pyg_rules.py y desglose_pyg.py; este
fichero solo describe qué debe respetarse.
"""
from __future__ import annotations

# ── 11 categorías operativas oficiales (guía §3) ───────────────
# ORDEN DE PRIORIDAD OPERATIVA. La guía prohíbe:
#   - eliminarlas, renombrarlas, fusionarlas
#   - sustituirlas por categorías "más estándar"
#   - crear nuevas sin autorización
CATEGORIES: tuple[str, ...] = (
    "Suministros",
    "Restauración y Hostelería",
    "Servicios Profesionales",
    "Alquiler",
    "Impuestos y Tasas",
    "Marketing y Publicidad",
    "Gastos Bancarios",
    "Software y SaaS",
    "Oficina",
    "Otros",
    "Seguros",
)


# ── Bloques del PYG observados (guía §4 y §29) ─────────────────
PYG_BLOCKS: dict[str, str] = {
    "ingresos": "PYG - SIN IVA > Ventas N-Descuentos",
    "aprovisionamientos": "GASTOS > 1) Aprovisionamientos",
    "comisiones": "GASTOS > 2) Comisiones",
    "personal": "GASTOS > 3) Personal",
    "otros_gastos_explotacion": "GASTOS > 4) Otros Gastos de la explotación",
    "ebitda": "RESULTADO > 5) EBITDA",
    "outside_video_pyg": "FUERA_PYG_VIDEO (intereses/amortización/CAPEX)",
    "non_pyg": "NO_PYG (intercompany/fianza/transferencia propia)",
}


# ── Bloques PYG con sub-categorías del vídeo ────────────────────
PYG_SUBCATS: dict[str, list[str]] = {
    "ingresos": ["Ventas brutas", "Descuentos", "Devoluciones",
                 "Ventas N-Descuentos"],
    "aprovisionamientos": ["Alimentación", "Bebida", "Packaging"],
    "comisiones": ["Glovo", "Uber", "LastShop"],
    "personal": ["Sueldos y nóminas", "Seguridad Social empresa",
                 "Otros costes laborales"],
    "otros_gastos_explotacion": [
        "Servicios y Suministros",
        "Publicidad y Marketing",
        "Gastos generales",
    ],
}


# ── Jerarquía interna de las 11 categorías (guía §6) ───────────
# Cada categoría operativa puede descomponerse en sub-categorías
# semánticas. La jerarquía es SOLO referencia; no es obligatorio
# materializarla como columnas de la app.
HIERARCHY: dict[str, list[str]] = {
    "Suministros": [
        "Energía > Electricidad",
        "Energía > Gas energético",
        "Agua > Suministro de red",
        "Telecomunicaciones > Internet",
        "Telecomunicaciones > Telefonía",
        "Cocina/operación > Carbón",
    ],
    "Restauración y Hostelería": [
        "Aprovisionamientos > Alimentación > Carnes/Pescados/Frutas/Verduras/"
        "Panadería/Lácteos/Congelados/Salsas/Aceites/Ingredientes",
        "Aprovisionamientos > Bebida > Agua embotellada/Refrescos/Zumos/"
        "Cerveza/Vino",
        "Aprovisionamientos > Packaging > Cajas/Bolsas/Envases/Vasos/Tapas/"
        "Recipientes/Envoltorios/Material takeaway",
    ],
    "Servicios Profesionales": [
        "Asesoría > Laboral/Fiscal/Contable/Administrativa",
        "Legal > Abogados/Consultoría jurídica",
        "Consultoría > Estratégica/Técnica/Negocio",
        "Servicios técnicos externos > Soporte/Instalación/"
        "Mantenimiento especializado",
    ],
    "Alquiler": [
        "Local/Inmueble", "Almacén", "Equipamiento", "Maquinaria",
        "Vehículo", "Otros arrendamientos operativos",
    ],
    "Impuestos y Tasas": [
        "Licencias", "Permisos", "Tasas operativas", "Tributos locales",
        "IVA (separar, no suma al PYG)", "Impuesto sobre beneficios "
        "(fuera de EBITDA)", "Multas y sanciones (revisión)",
    ],
    "Marketing y Publicidad": [
        "Publicidad digital > Meta Ads/Google Ads/TikTok Ads",
        "Plataformas delivery > Glovo - visibilidad/Uber - visibilidad",
        "Producción/Creatividad > Diseño/Foto/Vídeo/Copy",
        "Agencias/colaboradores > Merche/Pablo",
        "Material promocional > Rotapel/Envapro (cuando NO es packaging)",
        "Influencers", "Branding", "SEO/SEM", "Promociones",
    ],
    "Gastos Bancarios": [
        "Comisiones de cuenta", "Comisiones por transferencias",
        "Comisiones TPV", "Comisiones de cobro", "Pasarela de pago",
        "Cambio de divisa", "Intereses (fuera de EBITDA)",
    ],
    "Software y SaaS": [
        "TPV", "Reservas", "Gestión", "Contabilidad", "Facturación",
        "Productividad", "Google Workspace/correo", "Cloud/hosting",
        "Dominios", "Automatización", "IA", "Diseño/creatividad",
        "Seguridad",
    ],
    "Oficina": [
        "Papelería > Papel/Cuadernos/Sobres/Carpetas",
        "Escritura > Bolígrafos/Rotuladores/Lápices",
        "Impresión > Tinta/Tóner/Consumibles",
        "Pequeño material > Grapadoras/Archivadores",
        "Equipos (CAPEX → MANUAL_REVIEW)",
    ],
    "Otros": [
        "Gasto operativo menor identificado",
        "Gasto administrativo excepcional identificado",
        "Otro concepto conocido sin categoría específica",
        # Naturaleza desconocida → MANUAL_REVIEW (no usar Otros)
    ],
    "Seguros": [
        "Responsabilidad civil", "Multirriesgo del local", "Daños",
        "Vehículos de empresa", "Ciberseguro", "Equipos/maquinaria",
    ],
}


# ── Sinónimos para normalización (guía §24) ────────────────────
# Mapping lowercase sin acentos → concepto canónico. La normalización
# sirve para COMPRENDER; nunca debe borrar el texto original
# (mantener `original_description` y `normalized_concept` por separado).
SYNONYMS: dict[str, str] = {
    # Energía
    "luz": "Electricidad",
    "electricidad": "Electricidad",
    "energia electrica": "Electricidad",
    "energia": "Electricidad",
    "gas natural": "Gas energético",
    "butano": "Gas energético",
    "gas": "Gas energético",
    # Agua
    "agua del local": "Agua (Suministro de red)",
    "agua": "Agua (Suministro de red)",
    "suministro agua": "Agua (Suministro de red)",
    # Telecomunicaciones
    "fibra": "Internet",
    "fibra optica": "Internet",
    "adsl": "Internet",
    "internet": "Internet",
    "conexion": "Internet",
    "telefonia": "Telefonía",
    "movil": "Telefonía",
    "telefono": "Telefonía",
    # Aprovisionamientos
    "comida": "Alimentación",
    "alimentos": "Alimentación",
    "food cost": "Alimentación",
    "materia prima": "Alimentación",
    "mercancia": "Alimentación",
    "mercaderia": "Alimentación",
    "bebidas": "Bebida",
    "drink": "Bebida",
    "cajas takeaway": "Packaging",
    "cajas delivery": "Packaging",
    "packaging boxes": "Packaging",
    "envases": "Packaging",
    # Comisiones
    "commission": "Comisiones",
    "comision": "Comisiones",
    "fee por pedido": "Comisiones",
    "marketplace fee": "Comisiones",
    # Marketing
    "ads": "Marketing y Publicidad",
    "ad": "Marketing y Publicidad",
    "advertising": "Marketing y Publicidad",
    "publicidad": "Marketing y Publicidad",
    "campana": "Marketing y Publicidad",
    "campaign": "Marketing y Publicidad",
    # Alquiler
    "renta": "Alquiler",
    "renta local": "Alquiler",
    "alquiler local": "Alquiler",
    "lease": "Alquiler",
    # Software
    "saas": "Software y SaaS",
    "suscripcion": "Software y SaaS",
    "licencia software": "Software y SaaS",
    # Impuestos
    "licencia": "Licencias/permisos",
    "permiso": "Licencias/permisos",
    "tasa licencia": "Licencias/permisos",
    # Seguros
    "poliza": "Seguros",
    "prima seguro": "Seguros",
}


# ── Proveedores multicategoría (guía §10) ──────────────────────
# Activen una comprobación especial del CONCEPTO. Si el concepto
# no se puede leer, MANUAL_REVIEW (no asumir por nombre de vendor).
MULTICATEGORY_VENDORS: dict[str, dict[str, str]] = {
    "Glovo": {
        "comision_por_pedido": "Comisiones > Glovo",
        "visibilidad/campana": "Marketing y Publicidad > Glovo - visibilidad",
        "suscripcion": "Software y SaaS (revisión)",
    },
    "Uber": {
        "comision_por_pedido": "Comisiones > Uber",
        "visibilidad/campana": "Marketing y Publicidad > Uber - visibilidad",
        "suscripcion": "Software y SaaS (revisión)",
    },
    "Rotapel": {
        "cajas/envases/bolsas": "Restauración y Hostelería > Packaging",
        "carteleria/material promocional":
            "Marketing y Publicidad > Material promocional",
    },
    "Envapro": {
        "cajas/envases/bolsas": "Restauración y Hostelería > Packaging",
        "carteleria/material promocional":
            "Marketing y Publicidad > Material promocional",
    },
}


# ── Hard flags canónicos (guía §26) ────────────────────────────
HARD_FLAGS: tuple[str, ...] = (
    "UNKNOWN_DOCUMENT_TYPE",
    "POSSIBLE_DUPLICATE",
    "INSUFFICIENT_CONCEPT",
    "AMBIGUOUS_VENDOR",
    "TOTAL_MISMATCH",
    "MIXED_LINES_UNRESOLVED",
    "POTENTIAL_CAPEX",
    "FINANCIAL_EXPENSE",
    "UNKNOWN_TAX",
    "UNMATCHED_CREDIT_NOTE",
    "CROSS_PERIOD_MATERIAL",
    "UNKNOWN_CATEGORY_MAPPING",
    "TAX_EXTRACTION_UNCERTAIN",
)


# ── Mapeo sugerido categoría operativa → bloque PYG ────────────
# Mapeo propuesto en la guía §6 + §10. NO se ejecuta automáticamente
# sin validación humana; este mapeo es la propuesta por defecto.
# Categorías NO operativas (Personal, Comisiones) van a sus propios
# bloques PYG porque así lo observaron los vídeos.
CATEGORY_TO_PYG_BUCKET: dict[str, str] = {
    # 11 categorías operativas
    "Suministros": "otros_gastos_explotacion",
    "Restauración y Hostelería": "aprovisionamientos",
    "Servicios Profesionales": "otros_gastos_explotacion",
    "Alquiler": "otros_gastos_explotacion",
    "Impuestos y Tasas": "otros_gastos_explotacion",  # sin IVA
    "Marketing y Publicidad": "otros_gastos_explotacion",
    "Gastos Bancarios": "otros_gastos_explotacion",  # operativas; intereses fuera
    "Software y SaaS": "otros_gastos_explotacion",
    "Oficina": "otros_gastos_explotacion",
    "Otros": "otros_gastos_explotacion",  # revisar caso a caso
    "Seguros": "otros_gastos_explotacion",  # PYG mapping MANUAL_REVIEW
    # Bloques PYG no-canónicos (no son categorías operativas)
    "Personal": "personal",
    "Comisiones": "comisiones",
}


# ── Status de clasificación (guía §30) ─────────────────────────
CLASSIFICATION_STATUSES: tuple[str, ...] = (
    "CLASSIFIED",          # auto-clasificado con confianza ≥0.95
    "MANUAL_REVIEW",       # confianza <0.95 o hard flag
    "NON_PYG",             # intercompany, fianza, etc.
    "DUPLICATE_BLOCKED",   # bloqueado por duplicado
)


# ── Confidence thresholds (guía §25) ───────────────────────────
CONFIDENCE_AUTO_CLASSIFY = 0.95
CONFIDENCE_REVIEW = 0.95  # < 0.95 → MANUAL_REVIEW
MIN_CONFIDENCE_AUDIT = 0.95


# ── CAPEX keywords (guía §18) ───────────────────────────────────
CAPEX_KEYWORDS: tuple[str, ...] = (
    "maquinaria", "horno", "nevera industrial", "ordenador",
    "portatil", "impresora", "mobiliario", "reforma",
    "instalacion duradera", "equipo de larga vida util",
    "equipo informatico", "equipo profesional",
)


# ── FINANCIAL_EXPENSE keywords (guía §19) ──────────────────────
FINANCIAL_KEYWORDS: tuple[str, ...] = (
    "intereses", "interes", "préstamo", "descubierto",
    "coste financiero", "comision financiera",
)


def is_capex_suspect(concept: str | None) -> bool:
    """True si el concepto sugiere compra de activo durable."""
    if not concept:
        return False
    c = str(concept).strip().lower()
    return any(k in c for k in CAPEX_KEYWORDS)


def is_financial_expense(concept: str | None) -> bool:
    """True si el concepto sugiere interés o coste financiero."""
    if not concept:
        return False
    c = str(concept).strip().lower()
    return any(k in c for k in FINANCIAL_KEYWORDS)


def normalize_concept(text: str | None) -> str | None:
    """Normaliza un concepto crudo aplicando SINONYMS.

    Devuelve el texto original si no hay match. NO borra el original
    (guía §24).
    """
    if not text:
        return text
    t = str(text).strip().lower()
    # Quitar acentos
    repl = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
            ("à", "a"), ("è", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u"),
            ("ñ", "n"), ("ü", "u"))
    for a, b in repl:
        t = t.replace(a, b)
    if t in SYNONYMS:
        return SYNONYMS[t]
    return text


def is_valid_category(cat: str | None) -> bool:
    """True si la categoría está dentro de las 11 oficiales."""
    if not cat:
        return False
    return str(cat).strip() in CATEGORIES


def needs_multicategory_check(vendor: str | None) -> bool:
    """True si el vendor es uno de los 4 críticos (Glovo/Uber/Rotapel/Envapro)."""
    if not vendor:
        return False
    v = str(vendor).strip().lower()
    for critico in ("glovo", "uber", "rotapel", "envapro"):
        if critico in v:
            return True
    return False