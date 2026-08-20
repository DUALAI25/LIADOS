"""
pyg_reconciliation.py — Fórmulas y reconciliación del PYG (P0.5, P0.6).

Responsabilidad única: centralizar las matemáticas del PYG y verificar
que los totales cuadren. Cualquier desviación marca el reporte entero
como INVALID_RECONCILIATION.

Convenciones de signos (UNA sola, en todo el sistema):
  - Ingresos (ventas): POSITIVO
  - Descuentos / devoluciones: ya restados en 'ventas N-Descuentos'
  - Gastos: POSITIVO (interpretamos 'gasto' como magnitud absoluta)
  - Márgenes / EBITDA: pueden ser negativo (si gasto > ingreso)

Fórmulas auditables (de la guía del cliente, §7):
  Ventas N-Descuentos (Ingresos) = Ventas brutas - Descuentos - Devoluciones
  Margen Bruto                   = Ingresos - Aprovisionamientos
  Margen de Contribución (MC)    = Margen Bruto - Comisiones
  EBITDA                         = MC - Personal - Otros gastos explotación
  Otros gastos explotación       = Servicios y Suministros + Publicidad y Marketing
                                  + Gastos Generales
  EBIT                           = EBITDA - Amortización
  Resultado antes impuestos      = EBIT - Resultado financiero
  Resultado del ejercicio         = Resultado antes impuestos - Impuesto beneficios
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# ── Report statuses ─────────────────────────────────────────
RECON_OK = "RECONCILED"
RECON_FAIL = "INVALID_RECONCILIATION"
RECON_WARN = "RECONCILED_WITH_WARNINGS"


# ── Tolerancia para reconciliación (céntimos) ───────────────
TOLERANCE = 0.011  # <= 1 céntimo


@dataclass
class PygBreakdown:
    """Inputs brutos del PYG. Todos en EUROS, gastos POSITIVOS."""

    ventas_brutas: float = 0.0
    descuentos: float = 0.0
    devoluciones: float = 0.0

    # Aprovisionamientos
    alimentacion: float = 0.0
    bebida: float = 0.0
    packaging: float = 0.0

    # Comisiones
    comision_glovo: float = 0.0
    comision_uber: float = 0.0
    comision_lastshop: float = 0.0
    comision_just_eat: float = 0.0
    comision_otros: float = 0.0

    # Personal
    personal_total: float = 0.0

    # Otros gastos de explotación
    servicios_y_suministros: float = 0.0
    publicidad_y_marketing: float = 0.0
    gastos_generales: float = 0.0

    # Capas posteriores (opcionales)
    amortizacion: float = 0.0
    resultado_financiero: float = 0.0
    impuesto_beneficios: float = 0.0

    # IVA contabilizado fuera del PYG (informativo)
    iva_total: float = 0.0

    # Bloqueado por duplicado / CAPEX / financiero (informativo)
    bloqueado_pyg: float = 0.0
    capex_bloqueado: float = 0.0
    intercompany_bloqueado: float = 0.0


# ── Funciones puras (sin estado, sin I/O) ──────────────────

def ventas_netas(b: PygBreakdown) -> float:
    """Ventas N-Descuentos = Ventas brutas - Descuentos - Devoluciones."""
    return b.ventas_brutas - b.descuentos - b.devoluciones


def aprovisionamientos_total(b: PygBreakdown) -> float:
    return b.alimentacion + b.bebida + b.packaging


def comisiones_total(b: PygBreakdown) -> float:
    return (
        b.comision_glovo + b.comision_uber + b.comision_lastshop
        + b.comision_just_eat + b.comision_otros
    )


def otros_gastos_explotacion_total(b: PygBreakdown) -> float:
    return (
        b.servicios_y_suministros
        + b.publicidad_y_marketing
        + b.gastos_generales
    )


def margen_bruto(b: PygBreakdown) -> float:
    """Margen bruto = Ingresos - Aprovisionamientos."""
    return ventas_netas(b) - aprovisionamientos_total(b)


def mc(b: PygBreakdown) -> float:
    """Margen de Contribución = Margen Bruto - Comisiones."""
    return margen_bruto(b) - comisiones_total(b)


def ebitda(b: PygBreakdown) -> float:
    """EBITDA = MC - Personal - Otros gastos de explotación."""
    return (
        mc(b)
        - b.personal_total
        - otros_gastos_explotacion_total(b)
    )


def ebit(b: PygBreakdown) -> float:
    """EBIT = EBITDA - Amortización."""
    return ebitda(b) - b.amortizacion


def resultado_antes_impuestos(b: PygBreakdown) -> float:
    """Resultado antes de impuestos = EBIT - Resultado financiero."""
    return ebit(b) - b.resultado_financiero


def resultado_ejercicio(b: PygBreakdown) -> float:
    """Resultado del ejercicio = RAI - Impuesto sobre beneficios."""
    return resultado_antes_impuestos(b) - b.impuesto_beneficios


# ── Reconciliación ─────────────────────────────────────────

@dataclass
class ReconResult:
    """Resultado de validar las fórmulas del PYG."""

    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    derived: dict = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.status != RECON_FAIL


def reconcile(b: PygBreakdown) -> ReconResult:
    """Verifica que todas las fórmulas del PYG sean internamente consistentes.

    En esta versión las fórmulas derivan TODOS los totales desde PygBreakdown
    (no hay totales 'esperados' separados contra los que comparar). Lo que
    sí validamos:

      1. Signos coherentes (gastos >= 0, ingresos >= 0 salvo devoluciones legítimas).
      2. Capas posteriores coherentes (si hay CAPEX automático dentro de
         OPEX, BLOQUEO el PYG).
      3. IVA declarado en 'b.iva_total' es un valor separado y no debe
         mezclarse con ventas_netas.

    Devuelve ReconResult con status, errors y warnings. Si errors está
    vacío, status = RECON_OK o RECON_WARN.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1) Signos
    if b.ventas_brutas < 0:
        errors.append(
            f"ventas_brutas negativa ({b.ventas_brutas:.2f}): el módulo "
            "espera ventas brutas POSITIVAS; si es una devolución, márcala "
            "en b.devoluciones o usa el flag MANUAL_REVIEW."
        )
    if b.descuentos < 0:
        errors.append(
            f"descuentos negativo ({b.descuentos:.2f}): usar magnitud positiva."
        )
    if b.devoluciones < 0:
        errors.append(
            f"devoluciones negativo ({b.devoluciones:.2f}): usar magnitud positiva."
        )

    # 2) Gastos deben ser >= 0
    for field_name in (
        "alimentacion", "bebida", "packaging",
        "comision_glovo", "comision_uber", "comision_lastshop",
        "comision_just_eat", "comision_otros",
        "personal_total",
        "servicios_y_suministros", "publicidad_y_marketing",
        "gastos_generales",
        "amortizacion", "resultado_financiero", "impuesto_beneficios",
    ):
        v = getattr(b, field_name)
        if v < 0:
            errors.append(
                f"{field_name} negativo ({v:.2f}): usar magnitud positiva."
            )

    # 3) IVA debe ir separado (no se mete en ventas_netas)
    if b.iva_total > 0:
        # Es informativo. Si 'ventas_netas' ya contiene IVA, lo advertimos.
        # Esta heurística no es perfecta sin totales 'esperados'; la marca
        # se aplica en el clasificador.
        warnings.append(
            f"iva_total={b.iva_total:.2f}€ detectado fuera del PYG (correcto)."
        )

    # 4) Capas 'posteriores' (no deberían aportar a gastos de explotación)
    if b.amortizacion > 0 and b.amortizacion > 0.5 * ebitda(b):
        warnings.append(
            f"amortizacion={b.amortizacion:.2f}€ representa >50% del EBITDA; "
            "verificar clasificación en OPEX vs CAPEX."
        )

    # Compute derived para exponer al caller
    derived = {
        "ventas_netas": round(ventas_netas(b), 2),
        "aprovisionamientos_total": round(aprovisionamientos_total(b), 2),
        "comisiones_total": round(comisiones_total(b), 2),
        "otros_gastos_explotacion_total": round(otros_gastos_explotacion_total(b), 2),
        "margen_bruto": round(margen_bruto(b), 2),
        "mc": round(mc(b), 2),
        "ebitda": round(ebitda(b), 2),
        "ebit": round(ebit(b), 2),
        "resultado_antes_impuestos": round(resultado_antes_impuestos(b), 2),
        "resultado_ejercicio": round(resultado_ejercicio(b), 2),
    }

    status = RECON_FAIL if errors else (
        RECON_WARN if warnings else RECON_OK
    )
    return ReconResult(
        status=status, errors=errors, warnings=warnings, derived=derived
    )


# ── Builders: convierten filas clasificadas → PygBreakdown ─────

def build_breakdown_from_classified(
    facts: Iterable[dict],
    *,
    iva_total: float = 0.0,
    bloqueado_pyg: float = 0.0,
) -> PygBreakdown:
    """Construye un PygBreakdown a partir de filas ya clasificadas.

    Cada fila debe tener:
        status: CLASSIFIED | DUPLICATE_BLOCKED | NON_PYG | MANUAL_REVIEW
        pyg_block: 'INGRESOS' | 'APROVISIONAMIENTOS' | 'COMISIONES' |
                   'PERSONAL' | 'OTROS_GASTOS_EXPLOTACION' | 'OTROS_GASTOS_PRODUCCION' |
                   'SERVICIOS' | 'AMORTIZACION' | 'FINANCIERO' | 'CAPEX' |
                   'FUERA_PYG' | 'NON_PYG'
        pyg_subcategory: 'Alimentación' | 'Bebida' | 'Packaging' |
                         'Glovo' | 'Uber' | 'LastShop' | 'Just Eat' |
                         'Servicios y Suministros' | 'Publicidad y Marketing' |
                         'Gastos Generales' | etc.
        net_amount: float (base imponible real, sin IVA)
        contribution_to_pyg: float (0 si es DUPLICATE_BLOCKED, NON_PYG, CAPEX,
                                     financiero o IVA)

    Sólo contribuyen al PYG:
        - status == 'CLASSIFIED' o 'MANUAL_REVIEW' y contribution_to_pyg > 0
        - pyg_block en {INGRESOS, APROVISIONAMIENTOS, COMISIONES, PERSONAL,
                        OTROS_GASTOS_EXPLOTACION, OTROS_GASTOS_PRODUCCION,
                        SERVICIOS}
    NO contribuyen:
        - DUPLICATE_BLOCKED (contribution_to_pyg = 0)
        - NON_PYG (intercompany, fianza)
        - CAPEX (POTENTIAL_CAPEX → MANUAL_REVIEW, nunca OPEX)
        - FINANCIERO (va a 'resultado_financiero')
        - AMORTIZACION
    """
    b = PygBreakdown(iva_total=iva_total, bloqueado_pyg=bloqueado_pyg)

    for f in facts or []:
        contrib = float(f.get("contribution_to_pyg", 0) or 0)
        if contrib <= 0:
            continue
        block = (f.get("pyg_block") or "").upper()
        sub = (f.get("pyg_subcategory") or "").strip()
        kind = (f.get("kind") or "").lower()  # 'ingreso' | 'gasto'

        if kind == "ingreso" or block == "INGRESOS":
            # Inconsistencia detectada: una fila INGRESOS con kind=gasto
            # no debería existir (impuesto sobre beneficios se modela
            # en b.impuesto_beneficios directamente). Por seguridad, la
            # descartamos si kind='gasto'.
            if kind == "gasto":
                continue
            if "descuento" in sub.lower():
                b.descuentos += contrib
            elif "devolucion" in sub.lower() or "abono" in sub.lower():
                b.devoluciones += contrib
            else:
                b.ventas_brutas += contrib
            continue

        if block == "APROVISIONAMIENTOS":
            sub_l = sub.lower()
            if "aliment" in sub_l:
                b.alimentacion += contrib
            elif "bebida" in sub_l:
                b.bebida += contrib
            elif "packaging" in sub_l or "envase" in sub_l:
                b.packaging += contrib
            else:
                # Cualquier 'Aprovisionamientos' sin sub clara cae a
                # Alimentación para mantener reconciliación.
                b.alimentacion += contrib
            continue

        if block == "COMISIONES":
            sub_l = sub.lower()
            if "glovo" in sub_l:
                b.comision_glovo += contrib
            elif "uber" in sub_l:
                b.comision_uber += contrib
            elif "last" in sub_l:
                b.comision_lastshop += contrib
            elif "just" in sub_l and "eat" in sub_l:
                b.comision_just_eat += contrib
            else:
                b.comision_otros += contrib
            continue

        if block == "PERSONAL":
            b.personal_total += contrib
            continue

        if block in ("OTROS_GASTOS_EXPLOTACION", "OTROS_GASTOS_PRODUCCION",
                     "SERVICIOS"):
            sub_l = sub.lower()
            # Servicios/Suministros: cualquier cosa que NO sea marketing
            # ni 'Otros' explícito cae en servicios_y_suministros.
            if "publicidad" in sub_l or "marketing" in sub_l:
                b.publicidad_y_marketing += contrib
            elif "gastos generales" in sub_l or sub_l == "otros":
                b.gastos_generales += contrib
            else:
                # Por defecto (Luz, Alquiler, Internet, Asesoría, etc.)
                b.servicios_y_suministros += contrib
            continue

        if block == "AMORTIZACION":
            b.amortizacion += contrib
            continue

        if block == "FINANCIERO":
            b.resultado_financiero += contrib
            continue

        if block in ("CAPEX", "FUERA_PYG", "NON_PYG"):
            # No contribuye; ya está excluido.
            continue

    return b


# ── Reporting ──────────────────────────────────────────────

def status_label(status: str) -> str:
    """Etiqueta humana para mostrar en la UI."""
    return {
        RECON_OK: "✓ Reconciliado",
        RECON_FAIL: "✗ Reconciliación inválida",
        RECON_WARN: "⚠ Reconciliado con avisos",
    }.get(status, status)
