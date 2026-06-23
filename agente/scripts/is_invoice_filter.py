"""
is_invoice_filter.py — Filtro para distinguir adjuntos que son facturas reales
de contratos, propuestas, info legal, tiques y modelos Hacienda.

FILOSOFÍA (importante, aprendida sesión 028):
    Los filenames de facturas reales son MUY variables: a veces llevan "factura",
    "invoice", "FRA", "albarán", "ticket"; otras veces son UUIDs puros
    (ej: "88203c2f...018656.pdf"), IDs del ERP (ej: "MA26577.pdf"), o incluso
    nombres crípticos como "JESUS SANCHEZ.pdf" (es una factura de Climahostel).

    Por tanto el filtro NO debe intentar adivinar qué es factura por filename.
    Solo debe DESCARTAR lo que claramente NO es factura. Si no hay señales
    fuertes de descarte, ACEPTAR.

Patrones observados en la BD `desliado` (sesión 028, 64 filas huérfanas):
  - 17 sin vendor_name (parseo falló totalmente, contenido basura)
  - IONOS Cloud: "Condiciones y Términos Generales", "Información al consumidor..."
  - VAMOS AL LIO SL: "036_ALTA RETENCIONES", "FINIQUITO AITOR", "036_ALTA ACTIVIDAD"
  - Movistar, Telefónica: "CONTRATO FIJO..."
  - La Cochera, Viducean: "PROPUESTA...", "Contrato Puro Latino..."
  - REDEXIS, Unicaja: "Solicitud Conexión", "Certificado de cuenta..."
  - Just-Eat: "Solicitud de firma..."
  - AYUNTAMIENTO, Registro Mercantil: "reciboSolicitud", "provision.pdf"

API pública:
    is_invoice_attachment(filename, subject=None) -> tuple[bool, str | None]
        Devuelve (es_factura, razon_descarte) para uso en gmail_collector.

Recall objetivo: 100% (cero falsos positivos). Precision objetivo: >90%
(descartar al menos 90% de adjuntos basura).
"""
import re
from pathlib import Path

# Palabras clave que indican "no es factura" (case-insensitive).
# Solo patrones FUERTES: señales inequívocas de "esto NO es una factura".
NON_INVOICE_KEYWORDS = [
    # Contratos
    r"\bcontrato\w*\b",  # contrato, ContratoElec, contracto (con sufijo)
    r"\bcontract\b",
    # Modelos Hacienda / formularios censales
    r"\bcensal\b",
    r"\bretenciones\b",  # "036_ALTA RETENCIONES"
    r"036[_ -]*alt[ai]\s+actividad",  # "036_ALTA ACTIVIDAD" — alta censal
    # Info legal / condiciones (típico de emails automáticos de proveedores SaaS)
    r"términos?\s+generales",
    r"condiciones\s+generales",
    r"información\s+al\s+consumidor",
    r"derecho\s+de\s+desistimiento",
    r"acuse\s+de\s+recibo",
    # Propuestas / ofertas / presupuestos (NO factura)
    r"\bpropuesta\b",
    r"\boferta\b",
    r"\bpresupuesto\b",
    r"solicitud\s+de\s+firma",
    r"solicitud\s+conexi[oó]n",
    # Certificados / provisiones (sin factura asociada)
    r"certificado\s+de\s+cuenta",
    r"\bprovision\b",
    r"recibo[_-]?solicitud",
    # Documentos sin valor fiscal
    r"\bcartel\b",
    r"\ball[áa]rgenos\b",
    r"condiciones\s+y\s+t[ée]rminos",
    # Logos e imágenes decorativas
    r"logo[_-]?\w*\.(?:jpg|jpeg|png|gif)\b",
    r"^image\d+\.(?:png|jpe?g)\b",
    # Tiques de pedido (sin valor fiscal completo, ej: LEROY)
    r"tiquepedido",
]

# Patrones de RECHAZO INCONDICIONAL: ganan sobre cualquier hint.
# Si aparece uno de estos, NO es factura. Ni aunque tenga "factura" en el nombre.
FORCE_REJECT_EVEN_WITH_HINT = [
    r"\bmodelo\s*0?36\b",  # modelo 036 es siempre formulario, nunca factura
    r"\bfiniquito\b",  # finiquito laboral, no factura
    r"\bn[oó]minas?\b",  # nómina, no factura
    r"\btiquepedido\b",  # tique de compra, no factura completa
]

# Patrones positivos (whitelist): si alguno matchea, fuerzan es_factura=True
# HINTS_STRONG: palabra explícita de factura (acepta incluso si hay keyword no-factura)
# HINTS_WEAK: número de serie o nº (acepta SOLO si no hay keyword de no-factura)
HINTS_STRONG = [
    r"factura",
    r"invoice",
    r"albar[aá]n",
    r"\brecibo[-_]?\d{4}",  # recibo-2026-E-RE-195
]
HINTS_WEAK = [
    r"\bticket\b",
    r"\btique\b",
    r"\bn[ºo°]\s*\d{3,}",
    r"\b\d{2}/\d{4,}\b",
]

# Patrones de RECHAZO solo-si-no-hay-hint-fuerte: si matchean Y hay un
# INVOICE_HINTS matcheando, se acepta igual (factura con contrato anexo, ej.).
FORCE_REJECT_EVEN_WITH_HINT = [
    r"\bmodelo\s*0?36\b",  # modelo 036 es siempre formulario, nunca factura
    r"\bfiniquito\b",  # finiquito laboral, no factura
    r"\bn[oó]minas?\b",  # nómina, no factura
    r"\btiquepedido\b",  # tique de pedido (LEROY) — tique de compra, no factura
]


def _has_any(text: str, patterns: list) -> str | None:
    """Devuelve el primer patrón que matchea, o None."""
    if not text:
        return None
    text_lower = text.lower()
    for p in patterns:
        if re.search(p, text_lower):
            return p
    return None


def is_invoice_attachment(filename: str, subject: str | None = None) -> tuple[bool, str | None]:
    """
    Decide si un adjunto de Gmail es una factura real.

    Args:
        filename: nombre del archivo adjunto (ej: "factura_makro_2026-06-16.pdf")
        subject: asunto del email (opcional, refuerza la decisión)

    Returns:
        (es_factura, razon_descarte)
        - (True, None) si parece factura
        - (False, "keyword:contrato") si se descarta por patrón de no-factura

    Lógica:
        1. Si NO contiene ninguna pista de factura (INVOICE_HINTS) Y NO contiene
           ninguna keyword de no-factura → rechazar (defensa contra adjuntos basura).
        2. Si contiene keyword de no-factura Y no tiene hint fuerte de factura → rechazar.
        3. Si contiene hint fuerte de factura → aceptar.
    """
    text = (filename or "") + " " + (subject or "")
    text = text.strip()
    if not text:
        return False, "no_filename_or_subject"

    non_invoice_match = _has_any(text, NON_INVOICE_KEYWORDS)
    force_reject = _has_any(text, FORCE_REJECT_EVEN_WITH_HINT)

    # Filosofía: el filename de facturas reales es demasiado variable para
    # inferir. Solo descartamos si hay señal clara de "no factura".
    if force_reject:
        return False, f"force_reject:{force_reject}"
    if non_invoice_match:
        return False, f"keyword:{non_invoice_match}"

    # No hay señales fuertes de descarte → aceptar
    return True, None


def categorize_non_invoice(filename: str, subject: str | None = None) -> str:
    """Categoriza el motivo de descarte para guardar en gmail_non_invoices.reason."""
    is_inv, reason = is_invoice_attachment(filename, subject)
    if is_inv:
        return "invoice"
    if reason and reason.startswith("keyword:"):
        return reason[len("keyword:"):]
    return reason or "unknown"


# Auto-test rápido al importar
if __name__ == "__main__":
    test_cases = [
        ("factura_makro_2026-06-16.pdf", None, True),
        ("Contrato FIJO por favor no dar a guardar.pdf", None, False),
        ("036_ALTA RETENCIONES PROFESIONALES.pdf", None, False),
        ("FINIQUITO AITOR.PDF", None, False),
        ("Condiciones y Términos Generales.pdf", None, False),
        ("Solicitud de firma para Contrato con Just Eat.pdf", None, False),
        ("recibo-2026-E-RE-195.pdf", "Recibo agua", True),
        ("Ticket-919857.pdf", None, True),
        ("Contrato Puro Latino Liados  (V1).docx.pdf", None, False),
        ("Certificado de cuenta Almerigas.pdf", None, False),
        ("CARTEL DE ALERGENOS.pdf", None, False),
        ("036_ALTA ACTIVIDAD.pdf", None, False),
        ("image004.png", None, False),  # sin nombre
        ("factura-001.pdf", "Factura mayo 2026", True),
        ("albarán_2026-06-16_11-18-16.pdf", None, True),
        ("ContratoElec_2026-06-05T07:31:02.pdf", None, False),
    ]
    print(f"{'FILENAME':50s} {'EXPECTED':10s} {'GOT':10s} {'REASON'}")
    print("-" * 100)
    for fname, subj, expected in test_cases:
        got, reason = is_invoice_attachment(fname, subj)
        ok = "✓" if got == expected else "✗"
        print(f"{ok} {fname[:48]:48s} {str(expected):10s} {str(got):10s} {reason or ''}")