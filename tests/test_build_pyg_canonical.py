"""
test_build_pyg_canonical.py — Tests del PYG jerárquico canónico (P0.1).

Cubre la estructura EXACTA del PYG del cliente:
- Ventas N-Descuentos → Aprovisionamientos (Alimentación/Bebida/Packaging)
  → Margen Bruto → Comisiones (Glovo/Uber/LastShop) → MC → Personal →
  Otros gastos de explotación (Servicios y Suministros / Publicidad y Marketing
  / Gastos Generales) → EBITDA → Amortización → EBIT → Resultado financiero →
  RAI → Impuesto → Resultado del ejercicio.

Verifica también:
- 4 dimensiones independientes (PYG + categoría + proveedor + canal).
- Sin fila 'Beneficio' duplicada (P0.9).
- Sin CAPEX en OPEX (P1.5).
- Sin financieros en EBITDA (P1.6).
- Sin IVA en PYG (P0.4).
- Reconciliación con report_status (P0.6).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dashboard'))

from desglose_pyg import build_pyg_canonical


# ── Dataset de prueba realista ──
SAMPLE = [
    # Ventas
    {"vendor_name": "Cliente Mostrador", "category_raw": "Ventas",
     "invoice_date": "2026-08-01", "total_amount": 5000.0, "base_amount": 4545.45,
     "iva_amount": 454.55, "channel": "Restaurant"},
    {"vendor_name": "Cliente Mostrador", "category_raw": "Descuentos",
     "invoice_date": "2026-08-05", "total_amount": 100.0, "channel": "Restaurant"},
    # Aprovisionamientos
    {"vendor_name": "Makro", "category_raw": "Alimentación",
     "invoice_date": "2026-08-08", "total_amount": 1200.0, "channel": "Restaurant"},
    {"vendor_name": "Coca Cola", "category_raw": "Bebida",
     "invoice_date": "2026-08-10", "total_amount": 300.0, "channel": "Restaurant"},
    {"vendor_name": "Envapro", "category_raw": "Packaging",
     "invoice_date": "2026-08-12", "total_amount": 100.0, "channel": "Delivery"},
    # Comisiones
    {"vendor_name": "Glovo", "category_raw": "Comisiones",
     "invoice_date": "2026-08-15", "total_amount": 200.0, "channel": "Delivery"},
    {"vendor_name": "Uber", "category_raw": "Comisiones",
     "invoice_date": "2026-08-15", "total_amount": 150.0, "channel": "Delivery"},
    # Personal
    {"vendor_name": "TGSS", "category_raw": "Seguridad Social",
     "invoice_date": "2026-08-30", "total_amount": 800.0, "channel": "Restaurant"},
    # Servicios y Suministros
    {"vendor_name": "Iberdrola", "category_raw": "Luz",
     "invoice_date": "2026-08-05", "total_amount": 150.0, "channel": "Restaurant"},
    {"vendor_name": "Propietario", "category_raw": "Alquiler",
     "invoice_date": "2026-08-01", "total_amount": 500.0, "channel": "Restaurant"},
    # Marketing
    {"vendor_name": "Google Ads", "category_raw": "Marketing",
     "invoice_date": "2026-08-20", "total_amount": 100.0, "channel": "Restaurant"},
    # Gastos Generales
    {"vendor_name": "AXA", "category_raw": "Seguros",
     "invoice_date": "2026-08-25", "total_amount": 80.0, "channel": "Restaurant"},
    # Financiero (fuera de EBITDA)
    {"vendor_name": "Banco", "category_raw": "Intereses",
     "invoice_date": "2026-08-31", "total_amount": 30.0, "channel": "Restaurant"},
    # CAPEX (fuera de OPEX)
    {"vendor_name": "Horno Industrial", "category_raw": "Maquinaria",
     "invoice_date": "2026-08-28", "total_amount": 2000.0, "channel": "Restaurant"},
    # Intercompany (fuera del PYG)
    {"vendor_name": "VAMOS AL LIO S.L.", "category_raw": "Transferencia",
     "invoice_date": "2026-08-15", "total_amount": 500.0, "channel": "Restaurant"},
]


# ── Estructura jerárquica ───────────────────────────────

class TestEstructuraJerarquica:
    """El PYG debe tener exactamente la jerarquía del cliente."""

    def test_report_status_es_reconciliado_o_warning(self):
        # El dataset tiene IVA extraído → esperamos warning (no error).
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        assert out["report_status"] in ("RECONCILED", "RECONCILED_WITH_WARNINGS")
        assert out["reconciliation"]["errors"] == []

    def test_no_hay_fila_beneficio_duplicada(self):
        """P0.9: no debe existir 'Beneficio' después de EBITDA (era un
        duplicado visual de MC)."""
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        labels = [l["label"] for l in out["lines"]]
        assert not any("Beneficio" in l for l in labels), (
            f"Detectada fila 'Beneficio' duplicada: {labels}"
        )

    def test_jerarquia_tiene_aprov_con_3_subcategorias(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        # Encontrar la fila de Aprovisionamientos
        aprov = next(l for l in out["lines"] if l["code"] == "aprovisionamientos")
        assert aprov["level"] == 1
        sub_labels = {c["label"] for c in aprov["children"]}
        # Las 3 sub-categorías del cliente
        assert "Alimentación" in sub_labels
        assert "Bebida" in sub_labels
        assert "Packaging" in sub_labels

    def test_jerarquia_tiene_comisiones_con_subcategorias(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        com = next(l for l in out["lines"] if l["code"] == "comisiones")
        sub_labels = {c["label"] for c in com["children"]}
        # Plataformas del cliente
        assert "Glovo" in sub_labels
        assert "Uber" in sub_labels

    def test_jerarquia_tiene_otros_gastos_con_3_subcategorias(self):
        """P0.3: Otros gastos de explotación tiene exactamente 3 sub-categorías."""
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        otros = next(l for l in out["lines"]
                     if l["code"] == "otros_gastos_explotacion")
        sub_labels = {c["label"] for c in otros["children"]}
        # Estructura exacta del cliente
        assert "Servicios y Suministros" in sub_labels
        assert "Publicidad y Marketing" in sub_labels
        assert "Gastos Generales" in sub_labels
        # NO debe mezclarse proveedor con categoría (P0.3)
        for sl in sub_labels:
            assert "Makro" not in sl
            assert "Glovo" not in sl
            assert "Uber" not in sl


# ── 4 dimensiones independientes ─────────────────────────

class TestCuatroDimensiones:
    """PYG + categoría + proveedor + canal coexisten."""

    def test_drilldown_tiene_proveedores_categorias_canales(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        assert "proveedores" in out["drilldown"]
        assert "categorias" in out["drilldown"]
        assert "canales" in out["drilldown"]

    def test_canales_presentes(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        canales = {c["name"] for c in out["drilldown"]["canales"]}
        # Restaurant y Delivery son los canales reales del dataset
        assert "Restaurant" in canales
        assert "Delivery" in canales

    def test_proveedores_presentes(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        proveedores = {p["name"] for p in out["drilldown"]["proveedores"]}
        # No deben aparecer canales como proveedores (P0.8)
        for p in proveedores:
            assert p not in ("Restaurant", "Take away", "Delivery"), (
                f"Canal {p} usado como proveedor"
            )


# ── Exclusión correcta del PYG ───────────────────────────

class TestExclusionPyg:
    """CAPEX, financieros, intercompany NO entran en EBITDA."""

    def test_capex_no_en_aprov(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        # El 'Horno Industrial' de 2000€ no debe aparecer en aprovisionamientos
        aprov_line = next(l for l in out["lines"]
                           if l["code"] == "aprovisionamientos")
        for child in aprov_line["children"]:
            assert child["value"] != 2000.0

    def test_capex_no_en_ningun_bucket_opex(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        # El horno de 2000€ no debe estar en ningún OPEX
        for line in out["lines"]:
            if line["level"] == 1:
                for child in line["children"]:
                    assert child["value"] != 2000.0

    def test_intereses_fuera_de_ebitda(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        # El 'Intereses' de 30€ debe ir a resultado_financiero, no a EBITDA
        assert out["totals"]["resultado_financiero"] == 30.0
        # Y debe afectar a EBIT pero no a EBITDA
        assert out["totals"]["ebit"] == out["totals"]["ebitda"] - out["totals"]["amortizacion"]

    def test_intercompany_bloqueado(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        # VAMOS AL LIO 500€ → intercompany_bloqueado (no a bloqueado_pyg)
        assert out["totals"]["intercompany_bloqueado"] == 500.0

    def test_capex_bloqueado_separado_de_intercompany(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        # Horno Industrial 2000€ → capex_bloqueado
        assert out["totals"]["capex_bloqueado"] == 2000.0
        # Y bloqueado_pyg general sigue a 0 (sin mezclas)
        assert out["totals"]["bloqueado_pyg"] == 0.0

    def test_iva_fuera_del_pyg(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        # 454.55€ de IVA declarado, separado
        assert out["totals"]["iva_total"] == 454.55


# ── Fórmulas canónicas ──────────────────────────────────

class TestFormulasCanónicas:
    """Las 4 fórmulas del enunciado deben cuadrar."""

    def test_margen_bruto_igual_ingresos_menos_aprov(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        ingresos = out["totals"]["ventas_netas"]
        aprov = out["totals"]["aprovisionamientos"]
        mb = out["totals"]["margen_bruto"]
        assert mb == pytest.approx(ingresos - aprov, abs=0.01)

    def test_mc_igual_margen_bruto_menos_comisiones(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        mb = out["totals"]["margen_bruto"]
        com = out["totals"]["comisiones"]
        mc = out["totals"]["mc"]
        assert mc == pytest.approx(mb - com, abs=0.01)

    def test_ebitda_igual_mc_menos_personal_menos_otros(self):
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        mc = out["totals"]["mc"]
        personal = out["totals"]["personal"]
        otros = out["totals"]["otros_gastos_explotacion"]
        ebitda = out["totals"]["ebitda"]
        assert ebitda == pytest.approx(mc - personal - otros, abs=0.01)

    def test_reconciliacion_status_derivado(self):
        """El report_status debe ser RECONCILED (o warning por IVA) si todo cuadra."""
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        assert out["reconciliation"]["status"] in (
            "RECONCILED", "RECONCILED_WITH_WARNINGS"
        )
        assert out["reconciliation"]["errors"] == []

    def test_reconciliation_derived_es_consistente(self):
        """Los derived de la reconciliación deben coincidir con totals."""
        out = build_pyg_canonical(SAMPLE, "2026-08-01", "2026-08-31")
        d = out["reconciliation"]["derived"]
        assert d["margen_bruto"] == pytest.approx(out["totals"]["margen_bruto"])
        assert d["mc"] == pytest.approx(out["totals"]["mc"])
        assert d["ebitda"] == pytest.approx(out["totals"]["ebitda"])
