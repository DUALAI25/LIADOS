"""
test_desglose.py — Tests del módulo dashboard/desglose.py

Cubre:
- Validación de inputs (dims, metric)
- Métricas count/sum/avg/min/max
- Dimensiones directas (vendor, category) y derivadas (month, quarter, year)
- Multi-dim pivot
- Normalización de importes (céntimos vs euros)
- Casos edge: filas vacías, dims NULL, >MAX_ROWS
"""
import sys
import os
import pytest
from datetime import date

# Path para importar el módulo
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dashboard'))

from desglose import build_desglose, DesgloseError, normalize_invoice_row, ALLOWED_DIMS


# ── Datos de test ─────────────────────────────────────────────

SAMPLE_ROWS = [
    # vendor, category, source_account, status, invoice_date, total_amount (céntimos)
    {"vendor_name": "Makro", "category_raw": "Suministros", "source_account": "principal",
     "status": "classified", "invoice_date": "2026-05-10", "total_amount": 123.45},  # 123.45€
    {"vendor_name": "Makro", "category_raw": "Suministros", "source_account": "principal",
     "status": "classified", "invoice_date": "2026-05-20", "total_amount": 50.0},   # 50€
    {"vendor_name": "Makro", "category_raw": "Suministros", "source_account": "secundaria",
     "status": "classified", "invoice_date": "2026-06-15", "total_amount": 88.0},   # 88€
    {"vendor_name": "Glovo", "category_raw": "Servicios", "source_account": "principal",
     "status": "classified", "invoice_date": "2026-06-01", "total_amount": 15.0},   # 15€
    {"vendor_name": "Glovo", "category_raw": "Servicios", "source_account": "principal",
     "status": "pending", "invoice_date": "2026-07-01", "total_amount": 23.0},      # 23€
    {"vendor_name": "Iberdrola", "category_raw": "Suministros", "source_account": "secundaria",
     "status": "classified", "invoice_date": "2026-04-10", "total_amount": 65.0},   # 65€
    # Edge: invoice_date vacía
    {"vendor_name": "Vacio", "category_raw": "Otros", "source_account": "principal",
     "status": "classified", "invoice_date": None, "total_amount": 1.0},
    # Edge: total_amount None
    {"vendor_name": "SinTotal", "category_raw": "Otros", "source_account": "principal",
     "status": "classified", "invoice_date": "2026-05-05", "total_amount": None},
]


# ── Tests de validación ──────────────────────────────────────

class TestValidation:
    def test_group_by_vacio(self):
        with pytest.raises(DesgloseError, match="1 y 4"):
            build_desglose(SAMPLE_ROWS, [], "count")

    def test_group_by_demasiadas(self):
        with pytest.raises(DesgloseError, match="1 y 4"):
            build_desglose(SAMPLE_ROWS, ["vendor", "category", "month", "cuenta", "source"], "count")

    def test_group_by_4_dims_ok(self):
        # 4 dimensiones = el máximo permitido
        out = build_desglose(SAMPLE_ROWS, ["vendor", "category", "cuenta", "month"], "count")
        assert "rows" in out
        assert len(out["rows"]) >= 1

    def test_dim_invalida(self):
        with pytest.raises(DesgloseError, match="Dimensión inválida"):
            build_desglose(SAMPLE_ROWS, ["bogus"], "count")

    def test_metric_invalida(self):
        with pytest.raises(DesgloseError, match="Métrica inválida"):
            build_desglose(SAMPLE_ROWS, ["vendor"], "median")


# ── Tests de métricas ────────────────────────────────────────

class TestMetrics:
    def test_count_por_vendor(self):
        out = build_desglose(SAMPLE_ROWS, ["vendor"], "count")
        d = {r["vendor"]: r["value"] for r in out["rows"]}
        assert d["Makro"] == 3
        assert d["Glovo"] == 2
        assert d["Vacio"] == 1

    def test_sum_por_vendor_eur(self):
        out = build_desglose(SAMPLE_ROWS, ["vendor"], "sum")
        d = {r["vendor"]: r["value"] for r in out["rows"]}
        # Makro: 123.45 + 50 + 88 = 261.45
        assert d["Makro"] == 261.45
        # Glovo: 15 + 23 = 38
        assert d["Glovo"] == 38.0

    def test_avg_por_categoria(self):
        out = build_desglose(SAMPLE_ROWS, ["category"], "avg")
        d = {r["category"]: r["value"] for r in out["rows"]}
        # Suministros: Makro*3 (123.45+50+88=261.45) + Iberdrola 65 = 326.45 / 4 = 81.6125
        assert abs(d["Suministros"] - 81.61) < 0.05

    def test_min_y_max(self):
        out_min = build_desglose(SAMPLE_ROWS, ["vendor"], "min")
        out_max = build_desglose(SAMPLE_ROWS, ["vendor"], "max")
        min_d = {r["vendor"]: r["value"] for r in out_min["rows"]}
        max_d = {r["vendor"]: r["value"] for r in out_max["rows"]}
        assert min_d["Makro"] == 50.0  # 5000 cts = 50€
        assert max_d["Makro"] == 123.45


# ── Tests de dimensiones derivadas (fecha) ───────────────────

class TestDateDimensions:
    def test_month_deriva_de_invoice_date(self):
        out = build_desglose(SAMPLE_ROWS, ["month"], "sum")
        d = {r["month"]: r["value"] for r in out["rows"]}
        # 2026-05: Makro(123.45+50=173.45) + Vacio no tiene mes + SinTotal(100 cts=1€) = 174.45
        assert "2026-05" in d

    def test_quarter(self):
        out = build_desglose(SAMPLE_ROWS, ["quarter"], "count")
        d = {r["quarter"]: r["value"] for r in out["rows"]}
        # Q2 2026 = abril, mayo, junio
        assert d.get("2026-Q2", 0) >= 4

    def test_year(self):
        out = build_desglose(SAMPLE_ROWS, ["year"], "sum")
        d = {r["year"]: r["value"] for r in out["rows"]}
        assert "2026" in d


# ── Tests de multi-dim pivot ─────────────────────────────────

class TestMultiDim:
    def test_vendor_x_cuenta(self):
        out = build_desglose(SAMPLE_ROWS, ["vendor", "cuenta"], "count")
        # Makro x principal = 2, Makro x secundaria = 1, Glovo x principal = 2, Iberdrola x secundaria = 1
        d = {(r["vendor"], r["cuenta"]): r["count"] for r in out["rows"]}
        assert d[("Makro", "principal")] == 2
        assert d[("Makro", "secundaria")] == 1
        assert d[("Glovo", "principal")] == 2

    def test_categoria_x_mes_sum(self):
        out = build_desglose(SAMPLE_ROWS, ["category", "month"], "sum")
        # Verifica estructura
        for r in out["rows"]:
            assert "category" in r
            assert "month" in r
            assert "value" in r
            assert "count" in r


# ── Tests de edge cases ──────────────────────────────────────

class TestEdgeCases:
    def test_filas_vacias(self):
        out = build_desglose([], ["vendor"], "count")
        assert out["rows"] == []
        assert out["total"]["count"] == 0
        assert out["total"]["value"] == 0

    def test_total_en_respuesta(self):
        out = build_desglose(SAMPLE_ROWS, ["vendor"], "sum")
        assert "total" in out
        assert out["total"]["count"] == len(SAMPLE_ROWS)

    def test_ordenado_por_value_desc(self):
        out = build_desglose(SAMPLE_ROWS, ["vendor"], "sum")
        values = [r["value"] for r in out["rows"]]
        assert values == sorted(values, reverse=True)

    def test_normalize_aliases(self):
        row = {"vendor": "AliasVendor", "category": "AliasCat", "total_amount": 1000}
        n = normalize_invoice_row(row)
        assert n["vendor_name"] == "AliasVendor"
        assert n["category_raw"] == "AliasCat"
        assert n["total_amount"] == 1000

    def test_normalize_passthrough(self):
        row = {"vendor_name": "DirectVendor", "category_raw": "DirectCat"}
        n = normalize_invoice_row(row)
        assert n["vendor_name"] == "DirectVendor"

    def test_eur_canonical_unit(self):
        # total_amount = 123.45 -> euros canónicos -> 123.45€
        out = build_desglose(
            [{"vendor_name": "Test", "category_raw": "C", "invoice_date": "2026-01-01", "total_amount": 123.45}],
            ["vendor"], "sum"
        )
        assert out["rows"][0]["value"] == 123.45

        # total_amount = 50.0 -> euros canónicos
        out2 = build_desglose(
            [{"vendor_name": "Test2", "category_raw": "C", "invoice_date": "2026-01-01", "total_amount": 50.0}],
            ["vendor"], "sum"
        )
        assert out2["rows"][0]["value"] == 50.0

    def test_importe_real_mayor_de_1000_eur_no_se_divide(self):
        out = build_desglose(
            [{"vendor_name": "ROTAPEL", "category_raw": "Servicios",
              "invoice_date": "2026-08-01", "total_amount": 3138.68}],
            ["vendor"], "sum"
        )
        assert out["rows"][0]["value"] == 3138.68


# ── Smoke: caso real con datos del VPS ───────────────────────

class TestRealDataSmoke:
    """No se ejecuta en CI (necesita BD). Marca para ejecutar manualmente."""

    @pytest.mark.skip(reason="requiere BD conexión real")
    def test_real_query_vps(self):
        """Ejecutar manualmente con: pytest -k test_real_query_vps --tb=short"""
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(host="localhost", dbname="desliado", user="desliado",
                                password=os.environ["DB_PASSWORD"])
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT vendor_name, category_raw, source_account, status,
                   invoice_date, total_amount
            FROM invoices
            WHERE type='expense' AND status != 'rejected' AND is_invoice = true
              AND COALESCE(category_raw, '') NOT IN ('nomina','administrativo','basura')
            LIMIT 1000
        """)
        rows = [dict(r) for r in cur.fetchall()]
        out = build_desglose(rows, ["category", "month"], "sum")
        assert out["rows_count"] >= 5
        assert out["total"]["count"] == len(rows)
        print(f"\nSmoke: {out['rows_count']} grupos, {len(rows)} facturas, "
              f"total={out['total']['value']:.2f}€")