"""
is_invoice_filter.py — Filtro para distinguir adjuntos que son facturas reales.

FIX 2026-07-01 v3 (ciclo 4 del bug):
- v1: variable redefinida, semantica rota
- v2: agregada logica de weak invalidators pero los regex patterns con \b
     fallaban cuando los delimitadores eran "_" en vez de espacios (ej
     "FINIQUITO_AITOR.pdf" no matcheaba "\bfiniquito\b").
- v3: usa [\W_]+ en vez de \b para que guion bajo tambien sea delimitador.
     Asi "FINIQUITO_AITOR", "NOMINAS_JUNIO", "factura-2026" y "factura 2026"
     funcionan todos.
"""
import re

# ─── Blacklist INCONDICIONAL ─────────────────────────────────────────────────
# Si matchea en filename O subject, NO es factura. Gana sobre cualquier hint.
# IMPORTANTE: usamos [\W_]+ (no guion bajo) y [\W_]+$|^| para que
# guiones bajos y otros separadores no eviten el match.
FORCE_REJECT = [
    r"(?:^|[\W_])modelo[\W_]?0?36(?:[\W_]|$)",     # modelo 036 / modelo-036
    r"(?:^|[\W_])finiquito(?:[\W_]|$)",             # finiquito_AITOR / finiquito laboral
    r"(?:^|[\W_])n[oó]minas?(?:[\W_]|$)",           # nominas_JUNIO / nomina
    r"(?:^|[\W_])tiquepedido(?:[\W_]|$)",
    r"(?:^|[\W_])contrato[\W_]+(?:de[\W_]+)?(?:trabajo|arrendamiento|prestaci[oó]n)(?:[\W_]|$)",
    r"(?:^|[\W_])propuesta[\W_]+(?:comercial|econ[oó]mica)(?:[\W_]|$)",
]

HINTS_STRONG = [
    r"(?:^|[\W_])factura(?:[\W_]|$)",
    r"(?:^|[\W_])invoice(?:[\W_]|$)",
    r"(?:^|[\W_])albar[aá]n(?:[\W_]|$)",
    r"(?:^|[\W_])recibo[-_]?\d{4}",
]

HINTS_WEAK = [
    r"(?:^|[\W_])ticket(?:[\W_]|$)",
    r"(?:^|[\W_])tique(?:[\W_]|$)",
    r"(?:^|[\W_])n[ºo°][\W_]?\s*\d{3,}",
    r"(?:^|[\W_])\d{2}/\d{4,}(?:[\W_]|$)",
]

# HINT_WEAK_INVALIDATORS: si filename contiene contrato/propuesta SIN hint fuerte
# -> NO es factura
HINT_WEAK_INVALIDATORS = [
    r"(?:^|[\W_])contrato(?:[\W_]|$)",
    r"(?:^|[\W_])propuesta(?:[\W_]|$)",
    r"(?:^|[\W_])presupuesto(?:[\W_]|$)",
    r"(?:^|[\W_])certificado(?:[\W_]|$)",
    r"(?:^|[\W_])solicitud(?:[\W_]|$)",
    r"(?:^|[\W_])confirmaci[oó]n(?:[\W_]|$)",
    r"(?:^|[\W_])normas?(?:[\W_]|$)",
]


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE | re.UNICODE) for p in patterns]


_FORCE_REJECT_C = _compile(FORCE_REJECT)
_HINTS_STRONG_C = _compile(HINTS_STRONG)
_HINTS_WEAK_C = _compile(HINTS_WEAK)
_HINT_WEAK_INV_C = _compile(HINT_WEAK_INVALIDATORS)


def _any_match(patterns_compiled, text):
    if not text:
        return False, None
    for p in patterns_compiled:
        m = p.search(text)
        if m:
            return True, m.group(0)
    return False, None


def is_invoice_attachment(filename, subject=None):
    """Decide si un adjunto es una factura real.

    Args:
        filename: nombre del archivo del adjunto
        subject: asunto del email (opcional)

    Returns:
        (is_invoice, reason)
    """
    if not filename:
        return False, "reject:empty_filename"

    filename_str = filename or ""
    subject_str = subject or ""

    # 1. Blacklist: AMBOS por separado (no combined, para no contaminar con hint)
    #    Si filename=finiquito.pdf o subject contiene finiquito -> reject.
    matched, kw = _any_match(_FORCE_REJECT_C, filename_str)
    if matched:
        return False, f"reject:force:fn:{kw}"
    matched, kw = _any_match(_FORCE_REJECT_C, subject_str)
    if matched:
        return False, f"reject:force:sub:{kw}"

    # 2. Hints fuertes (buscamos en ambos)
    matched, kw = _any_match(_HINTS_STRONG_C, filename_str)
    if matched:
        return True, f"matched:strong:fn:{kw}"
    matched, kw = _any_match(_HINTS_STRONG_C, subject_str)
    if matched:
        return True, f"matched:strong:sub:{kw}"

    # 3. Hints debiles: solo en filename, requieren NO invalidator
    has_invalidator, _ = _any_match(_HINT_WEAK_INV_C, filename_str)
    if has_invalidator:
        return False, "reject:weak_with_invalidator"

    matched, kw = _any_match(_HINTS_WEAK_C, filename_str)
    if matched:
        return True, f"matched:weak:{kw}"

    # 4. Sin hint positivo
    return False, "reject:no_hint"


if __name__ == "__main__":
    test_cases = [
        ("factura_2026_001.pdf", None, True, "filename con 'factura'"),
        ("2026-06-15_albaran.pdf", None, True, "albaran con guion"),
        ("FINIQUITO_AITOR.pdf", "factura fin de contrato", False, "finiquito_AITOR"),
        ("modelo_036.pdf", None, False, "modelo_036 con guion bajo"),
        ("modelo 036.pdf", "declaracion", False, "modelo 036 espacio"),
        ("entrega_albaran_795.pdf", None, True, "albaran con numero"),
        ("contrato_arrendamiento.pdf", None, False, "contrato_arrendamiento"),
        ("factura_anexo_contrato.pdf", None, True, "factura + contrato: factura gana"),
        ("some_random.pdf", "asunto cualquiera", False, "sin hints"),
        ("NOMINAS_JUNIO.pdf", None, False, "nominas_JUNIO"),
        ("", None, False, "filename vacio"),
        ("recibo-2026-E-RE-195.pdf", None, True, "recibo con guion"),
        ("presupuesto_anual.pdf", None, False, "presupuesto no factura"),
        ("ticket_775.pdf", None, True, "ticket con numero"),
        ("036_ALTA RETENCIONES.pdf", None, False, "036"),
        ("factura_001.pdf", "adjunto contrato anexo", True, "factura fuerte incluso con 'contrato' en subject"),
    ]

    print("\n=== TESTS ===")
    passed = 0
    for filename, subject, expected, desc in test_cases:
        result, reason = is_invoice_attachment(filename, subject)
        ok = (result == expected)
        icon = "OK" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"{icon} {desc:50s} -> is_invoice={result} reason={reason or '-'}")

    print(f"\n{passed}/{len(test_cases)} tests passed")
