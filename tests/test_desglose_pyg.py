"""
test_desglose_pyg.py — Tests del módulo dashboard/desglose_pyg.py

Cubre:
- Reglas de clasificación (5 buckets, 1 test cada uno = 5)
- Cálculo de totales y márgenes (5)
- Casos edge: vacío, filtro por cuenta, regla custom (3)
"""
import sys
import os
import pytest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dashboard'))

from desglose_pyg import (
    build_pyg, PygError, cross_check_subcat,
)
from desglose_pyg_rules import (
    classify_factura, DEFAULT_RULES, BUCKETS, load_rules,
)


# ── Datos de muestra ──
# Convención Liados: total_amount en CÉNTIMOS (int) por la BD.
# El motor detecta céntimos (|x| > 1000) y divide entre 100.

SAMPLE = [
    # Ventas (cts): 150€ + 120€ + 30€ = 300€
    {"vendor_name": "Cliente A", "category_raw": "Ventas", "source_account": "principal",
     "invoice_date": "2026-01-05", "total_amount": 15000},
    {"vendor_name": "Cliente B", "category_raw": "Ventas", "source_account": "principal",
     "invoice_date": "2026-01-15", "total_amount": 12000},
    {"vendor_name": "Cliente C", "category_raw": "Ventas", "source_account": "principal",
     "invoice_date": "2026-01-25", "total_amount": 3000},
    # Descuentos (cts): 10€
    {"vendor_name": "Cliente A", "category_raw": "Descuentos", "source_account": "principal",
     "invoice_date": "2026-01-10", "total_amount": 1000},
    # Aprovisionamientos (cts): 40€ + 10€ + 10€ = 60€ → food cost 60/290 = 20.7%
    {"vendor_name": "Makro", "category_raw": "Alimentación", "source_account": "principal",
     "invoice_date": "2026-01-08", "total_amount": 4000},
    {"vendor_name": "Ramillo", "category_raw": "Bebida", "source_account": "principal",
     "invoice_date": "2026-01-12", "total_amount": 1000},
    {"vendor_name": "Envapro", "category_raw": "Packaging", "source_account": "principal",
     "invoice_date": "2026-01-18", "total_amount": 1000},
    # Comisiones (cts): 30€ + 15€ + 10€ = 55€ → 55/290 = 18.9% (entre 17% y 20%, no warn estricto)
    {"vendor_name": "Glovo", "category_raw": "Comisiones", "source_account": "principal",
     "invoice_date": "2026-01-20", "total_amount": 3000},
    {"vendor_name": "Uber", "category_raw": "Comisiones", "source_account": "principal",
     "invoice_date": "2026-01-22", "total_amount": 1500},
    {"vendor_name": "LastShop", "category_raw": "Comisiones", "source_account": "principal",
     "invoice_date": "2026-01-26", "total_amount": 1000},
    # Personal (cts): 40€ + 100€ = 140€
    {"vendor_name": "TGSS", "category_raw": "Seguridad Social", "source_account": "principal",
     "invoice_date": "2026-01-30", "total_amount": 4000},
    {"vendor_name": "Nómina Ana", "category_raw": "Nóminas", "source_account": "principal",
     "invoice_date": "2026-01-30", "total_amount": 10000},
    # Servicios (cts): 60€ + 120€ = 180€
    {"vendor_name": "Iberdrola", "category_raw": "Luz", "source_account": "principal",
     "invoice_date": "2026-01-05", "total_amount": 6000},
    {"vendor_name": "Propietario", "category_raw": "Alquiler", "source_account": "principal",
     "invoice_date": "2026-01-01", "total_amount": 12000},
    # Out-of-period (no debe entrar)
    {"vendor_name": "Iberdrola", "category_raw": "Luz", "source_account": "principal",
     "invoice_date": "2025-12-30", "total_amount": 6000},
]


# ── Tests de clasificación ─────────────────────────────────

class TestClassification:
    def test_clasificacion_alimentacion(self):
        assert classify_factura("Alimentación", "Makro") == "aprovisionamientos"

    def test_clasificacion_bebida_packaging(self):
        assert classify_factura("Bebida", "Coca Cola") == "aprovisionamientos"
        assert classify_factura("Packaging", "Envapro") == "aprovisionamientos"

    def test_clasificacion_comisiones(self):
        assert classify_factura("Comisiones", "Glovo") == "comisiones"
        assert classify_factura("Comisiones", "Uber Eats") == "comisiones"
        # Regex match
        assert classify_factura("Otro", "uber eats") == "comisiones"

    def test_clasificacion_personal(self):
        assert classify_factura("Nóminas", "Nómina Ana") == "personal"
        assert classify_factura("Seguridad Social", "TGSS") == "personal"
        # Regex payroll
        assert classify_factura("Otro", "ADP Payroll Services") == "personal"

    def test_clasificacion_servicios(self):
        assert classify_factura("Luz", "Iberdrola") == "servicios"
        assert classify_factura("Alquiler", "Propietario") == "servicios"
        # Regex iberdrola
        assert classify_factura("Otro", "Iberdrola SA") == "servicios"

    def test_clasificacion_otros_catchall(self):
        # Una factura que no encaja va a otros_gastos
        assert classify_factura("Imprevistos varios", "Desconocido SL") == "otros_gastos"
        assert classify_factura(None, None) == "otros_gastos"


# ── Tests de cálculo ───────────────────────────────────────

class TestPygCalculation:
    def test_ingresos_basico(self):
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        t = out["totals"]
        # total_amount en céntimos (>1000 → se divide). Ventas = 15000+12000+3000 = 30000 céntimos = 300€
        # Descuentos = 1000 céntimos = 10€; ingresos = 290€
        assert t["ventas_brutas"] == 300.0
        assert t["descuentos"] == 10.0
        assert t["ingresos"] == 290.0

    def test_aprovisionamientos_y_food_cost(self):
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        # Aprovisionamientos (céntimos): 4000+1000+1000 = 6000 cts = 60€ → food cost 60/290 = 20.7%
        assert out["buckets"]["aprovisionamientos"] == 60.0
        # Margen bruto = 290 - 60 = 230
        assert out["totals"]["margen_bruto"] == 230.0
        # food cost % ≈ 0.207 < 0.35 → no warn
        issue_codes = [i["code"] for i in out["issues"]]
        assert "food_cost_alto" not in issue_codes

    def test_comisiones_y_mc(self):
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        # Comisiones (cts): 3000+1500+1000 = 5500 cts = 55€ → 55/290 = 19.0% < 20% no warn
        assert out["buckets"]["comisiones"] == 55.0
        # MC = 230 - 55 = 175
        assert out["totals"]["mc"] == 175.0

    def test_personal_y_servicios_y_ebitda(self):
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        # Personal (cts): 4000+10000 = 14000 cts = 140€
        assert out["buckets"]["personal"] == 140.0
        # Servicios (cts): 6000+12000 = 18000 cts = 180€
        assert out["buckets"]["servicios"] == 180.0
        # EBITDA = MC - Personal - Servicios - OtrosProd = 175 - 140 - 180 - 0 = -145
        assert out["totals"]["ebitda"] == -145.0
        # El issue 'ebitda_negativo' debe estar presente
        issue_codes = [i["code"] for i in out["issues"]]
        assert "ebitda_negativo" in issue_codes

    def test_totals_congruency(self):
        """Suma de buckets nivel 1 = total_gastos."""
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        sum_buckets = sum(out["buckets"].values())
        assert abs(sum_buckets - out["totals"]["total_gastos"]) < 0.01


# ── Tests de casos edge ────────────────────────────────────

class TestEdgeCases:
    def test_periodo_vacio(self):
        out = build_pyg([], "2026-01-01", "2026-01-31", cuenta="principal")
        assert out["totals"]["ingresos"] == 0.0
        assert out["totals"]["ebitda"] == 0.0
        assert out["rows_used"] == 0

    def test_filtro_por_cuenta_excluye_otras(self):
        # Añadir factura de cuenta "secundaria"
        rows = SAMPLE + [
            {"vendor_name": "Otro", "category_raw": "Luz", "source_account": "secundaria",
             "invoice_date": "2026-01-10", "total_amount": 5000},
        ]
        out_p = build_pyg(rows, "2026-01-01", "2026-01-31", cuenta="principal")
        out_s = build_pyg(rows, "2026-01-01", "2026-01-31", cuenta="secundaria")
        # Principal no incluye la factura de secundaria
        assert out_p["buckets"]["servicios"] == 180.0
        # Secundaria solo tiene esa factura
        assert out_s["buckets"]["servicios"] == 50.0

    def test_out_of_period_excluido(self):
        """Facturas fuera del rango no entran."""
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        # La factura de 2025-12-30 NO debe entrar
        assert out["buckets"]["servicios"] == 180.0  # 60 + 120, no 60 + 120 + 60

    def test_fechas_invalidas(self):
        with pytest.raises(PygError, match="Fechas inválidas"):
            build_pyg(SAMPLE, "2026-13-99", "2026-01-31", cuenta="principal")

    def test_period_from_mayor(self):
        with pytest.raises(PygError, match="period_from"):
            build_pyg(SAMPLE, "2026-02-01", "2026-01-01", cuenta="principal")

    def test_drilldown_estructura(self):
        """El drilldown de aprovisionamientos tiene las 3 sub-categorías."""
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        dd = out["drilldown"]["aprovisionamientos"]
        assert "Alimentación" in dd
        assert "Bebida" in dd
        assert "Packaging" in dd
        assert dd["Alimentación"]["vendors"][0]["name"] == "Makro"
        assert dd["Alimentación"]["vendors"][0]["value"] == 40.0

    def test_cross_check_sin_datos_venta(self):
        """cross_check devuelve filas aunque no haya datos de venta."""
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        cc = cross_check_subcat(out, ventas_por_subcat=None)
        # 3 sub-categorías
        assert len(cc) == 3
        # Todas con status sin_dato_venta
        assert all(r["status"] == "sin_dato_venta" for r in cc)

    def test_cross_check_con_ventas_ok(self):
        """Si las ventas dan margen >= target, status=ok."""
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        # Bebida: gasto en cts=1000 → 10€ en euros; venta=80€ → margin = (80-10)/80 = 0.875 ≥ 0.80 → ok
        cc = cross_check_subcat(out, ventas_por_subcat={"Bebida": 80.0, "Alimentación": 200.0, "Packaging": 30.0})
        bebida = next(r for r in cc if r["subcat"] == "Bebida")
        assert bebida["status"] == "ok"
        assert bebida["margin_real"] == pytest.approx(0.875, abs=0.01)

    def test_cross_check_con_ventas_alerta(self):
        """Si margen < target, status=alerta (posible fuga)."""
        out = build_pyg(SAMPLE, "2026-01-01", "2026-01-31", cuenta="principal")
        # Bebida: gasto=10€ (de 1000 cts), venta=20€ → margin = 0.5 < 0.80 → alerta
        cc = cross_check_subcat(out, ventas_por_subcat={"Bebida": 20.0, "Alimentación": 100.0, "Packaging": 30.0})
        bebida = next(r for r in cc if r["subcat"] == "Bebida")
        assert bebida["status"] == "alerta"

    def test_all_buckets_present(self):
        """Los 6 buckets están en BUCKETS."""
        assert len(BUCKETS) == 6
        assert "aprovisionamientos" in BUCKETS
        assert "comisiones" in BUCKETS
        assert "personal" in BUCKETS
        assert "servicios" in BUCKETS
        assert "otros_gastos" in BUCKETS
