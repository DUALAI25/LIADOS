"""
test_pyg_periods.py — Tests de la gestión de períodos (P0.7, P0.10).

Cubre:
  - period_key_from_date: nunca devuelve None, '', 0 ni 'undefined'.
  - display_label_from_key: nunca devuelve '0', 'undefined', 'null', ''.
  - ytd_dates / split_ytd_and_period: año natural.
  - fill_month_gaps: serie mensual continua.
  - validate_period_keys: limpia entradas inválidas.
"""
import sys
import os
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dashboard'))

from pyg_periods import (
    period_key_from_date,
    display_label_from_key,
    display_label_full,
    is_valid_period_key,
    validate_period_keys,
    ytd_dates,
    total_period_dates,
    is_multi_year,
    split_ytd_and_period,
    fill_month_gaps,
    build_monthly_row,
    build_ytd_row,
)


# ── period_key_from_date ──────────────────────────────────

class TestPeriodKeyFromDate:
    def test_none_devuelve_sentinel(self):
        assert period_key_from_date(None) == "0000-00"

    def test_string_vacio_devuelve_sentinel(self):
        assert period_key_from_date("") == "0000-00"
        assert period_key_from_date("   ") == "0000-00"

    def test_int_cero_devuelve_sentinel(self):
        assert period_key_from_date(0) == "0000-00"

    def test_int_valido(self):
        # No nos importa qué día; solo YYYY-MM
        d = date(2026, 8, 15)
        assert period_key_from_date(d) == "2026-08"

    def test_string_yyyy_mm(self):
        assert period_key_from_date("2026-08") == "2026-08"

    def test_string_yyyy_mm_dd(self):
        assert period_key_from_date("2026-08-15") == "2026-08"

    def test_string_yyyy_mm_dd_hh_mm(self):
        assert period_key_from_date("2026-08-15 10:30:00") == "2026-08"

    def test_string_iso_t(self):
        assert period_key_from_date("2026-08-15T10:30:00") == "2026-08"
        assert period_key_from_date("2026-08-15T10:30:00Z") == "2026-08"

    def test_string_invalido_devuelve_sentinel(self):
        assert period_key_from_date("xyz") == "0000-00"
        assert period_key_from_date("not a date") == "0000-00"

    def test_string_parcial(self):
        # '2026-08-' → tras slicing '2026-08' válido
        assert period_key_from_date("2026-08-") == "2026-08"


# ── is_valid_period_key / display_label ───────────────────

class TestIsValidPeriodKey:
    def test_keys_validas(self):
        for k in ("2026-01", "2025-12", "1900-01", "2999-12"):
            assert is_valid_period_key(k), f"{k} debería ser válida"

    def test_keys_invalidas(self):
        for k in ("", None, "2026-13", "2026-00", "abcd-ef", "2026",
                  "2026-8", "0000-00", "2999-13", "2026-1"):
            assert not is_valid_period_key(k), f"{k!r} debería ser inválida"


class TestDisplayLabel:
    def test_label_valido_es(self):
        assert display_label_from_key("2026-08") == "ago-26"
        assert display_label_from_key("2026-01") == "ene-26"
        assert display_label_from_key("2026-12") == "dic-26"

    def test_label_valido_en(self):
        assert display_label_from_key("2026-08", locale="en") == "Aug-26"

    def test_label_invalido_devuelve_fallback(self):
        # NUNCA '0', 'undefined', 'null', ''
        for k in (None, "", 0, "0000-00", "invalid", "2026-13"):
            out = display_label_from_key(k)
            assert out not in ("0", "undefined", "null", "", None)
            assert isinstance(out, str) and len(out) > 0
            # fallback por defecto es '—'
            assert out == "—"

    def test_label_fallback_custom(self):
        assert display_label_from_key(None, fallback="N/A") == "N/A"

    def test_label_recorta_yyyy_mm_dd(self):
        # '2026-08-15T10' no es 'YYYY-MM' pero sí parece fecha
        assert display_label_from_key("2026-08-15T10") == "ago-26"

    def test_label_full(self):
        assert display_label_full("2026-08") == "agosto 2026"
        assert display_label_full(None) == "—"


# ── YTD y Total período ───────────────────────────────────

class TestYtd:
    def test_ytd_dates_agosto(self):
        ytd_from, ytd_to = ytd_dates("2026-08-15")
        assert ytd_from == date(2026, 1, 1)
        assert ytd_to == date(2026, 8, 15)

    def test_ytd_dates_enero(self):
        ytd_from, ytd_to = ytd_dates("2026-01-05")
        assert ytd_from == date(2026, 1, 1)
        assert ytd_to == date(2026, 1, 5)

    def test_ytd_dates_31_diciembre(self):
        ytd_from, ytd_to = ytd_dates("2026-12-31")
        assert ytd_from == date(2026, 1, 1)
        assert ytd_to == date(2026, 12, 31)


class TestSplitYtdAndPeriod:
    def test_periodo_dentro_mismo_anno(self):
        sp = split_ytd_and_period(date(2026, 1, 1), date(2026, 8, 31))
        assert sp["spans_multiple_years"] is False
        assert sp["labels"]["ytd_label"] == "YTD 2026"
        # En este caso ytd y period coinciden
        assert sp["ytd"]["from"] == "2026-01-01"
        assert sp["period"]["to"] == "2026-08-31"

    def test_periodo_multi_anno(self):
        sp = split_ytd_and_period(date(2025, 11, 1), date(2026, 2, 28))
        assert sp["spans_multiple_years"] is True
        assert sp["labels"]["ytd_label"] == "YTD 2026"
        assert sp["labels"]["period_label"] == "Período seleccionado"
        # YTD siempre empieza 1 enero del año del 'to'
        assert sp["ytd"]["from"] == "2026-01-01"
        assert sp["ytd"]["to"] == "2026-02-28"
        # Period muestra el rango completo
        assert sp["period"]["from"] == "2025-11-01"
        assert sp["period"]["to"] == "2026-02-28"

    def test_is_multi_year(self):
        assert is_multi_year(date(2025, 12, 31), date(2026, 1, 1)) is True
        assert is_multi_year(date(2026, 1, 1), date(2026, 12, 31)) is False


# ── fill_month_gaps ───────────────────────────────────────

class TestFillMonthGaps:
    def test_huecos_se_rellenan(self):
        out = fill_month_gaps(["2026-05", "2026-08"],
                               end_reference="2026-08-31")
        assert out == ["2026-05", "2026-06", "2026-07", "2026-08"]

    def test_serie_continua_no_cambia(self):
        out = fill_month_gaps(["2026-05", "2026-06", "2026-07", "2026-08"])
        assert out == ["2026-05", "2026-06", "2026-07", "2026-08"]

    def test_sin_keys_devuelve_ultimos_6(self):
        out = fill_month_gaps([], end_reference="2026-08-31")
        assert out == ["2026-03", "2026-04", "2026-05", "2026-06",
                       "2026-07", "2026-08"]

    def test_salto_de_anno(self):
        out = fill_month_gaps(["2025-11", "2026-02"],
                               end_reference="2026-02-15")
        assert out == ["2025-11", "2025-12", "2026-01", "2026-02"]


# ── validate_period_keys ──────────────────────────────────

class TestValidatePeriodKeys:
    def test_limpia_invalidas(self):
        out = validate_period_keys(
            ["2026-08", None, "", "0000-00", 0, "invalid", "2026-08"]
        )
        # Solo queda '2026-08' (sin duplicados, sin null/0/''/'0000-00')
        assert out == ["2026-08"]

    def test_orden_asc(self):
        out = validate_period_keys(["2026-08", "2026-01", "2026-05"])
        assert out == ["2026-01", "2026-05", "2026-08"]

    def test_drop_invalid_false(self):
        # Si drop_invalid=False, '0000-00' y vacíos se mantienen
        out = validate_period_keys(
            ["2026-08", "0000-00", ""], drop_invalid=False
        )
        assert "2026-08" in out


# ── build_monthly_row / build_ytd_row ─────────────────────

class TestBuildRows:
    def test_monthly_row_label_nunca_invalido(self):
        row = build_monthly_row("0000-00", ingresos=100)
        # NUNCA '0', 'undefined', 'null', ''
        assert row["display_label"] not in ("0", "undefined", "null", "")
        assert row["display_label"] == "—"

    def test_monthly_row_valido(self):
        row = build_monthly_row("2026-08", ingresos=1000, gastos=300)
        assert row["period_key"] == "2026-08"
        assert row["display_label"] == "ago-26"
        assert row["year"] == 2026
        assert row["month"] == 8
        assert row["ingresos"] == 1000.0
        assert row["gastos"] == 300.0
        assert row["margen"] == 700.0

    def test_monthly_row_margen_explicito(self):
        row = build_monthly_row("2026-08", ingresos=1000, gastos=300, margen=600)
        assert row["margen"] == 600

    def test_ytd_row(self):
        row = build_ytd_row(2026, ingresos=12000, gastos=8000)
        assert row["period_key"] == "YTD-2026"
        assert row["display_label"] == "YTD 2026"
        assert row["year"] == 2026
        assert row["is_ytd"] is True
        assert row["margen"] == 4000.0
