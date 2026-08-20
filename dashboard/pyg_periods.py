"""
pyg_periods.py — Helpers de períodos (P0.7, P0.10).

Responsabilidad: garantizar que:
  - NUNCA aparezcan labels `0`, `undefined`, `null`, `""` en columnas
    temporales.
  - `period_key = "YYYY-MM"` siempre válido (interno, ordenable).
  - `display_label = "MMM-YY"` legible para humanos.
  - `ytd` se calcula desde 1 enero del año natural hasta fin del período.
  - `total_period` = suma total del período seleccionado (no YTD).

Uso típico:

    from pyg_periods import (
        period_key_from_date, display_label_from_key,
        ytd_dates, validate_period_keys,
    )
"""
from __future__ import annotations

import calendar
from datetime import date as _date, datetime as _dt
from typing import Iterable


_MONTHS_ES_SHORT = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)
_MONTHS_EN_SHORT = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


# ── period_key ────────────────────────────────────────────

def period_key_from_date(d: _date | _dt | str | int | None) -> str:
    """Devuelve 'YYYY-MM' para una fecha.

    Robusta a None, '', 0, strings malformados: en esos casos devuelve
    '0000-00' (sentinel seguro que el frontend puede detectar y ocultar).
    """
    if d is None:
        return "0000-00"
    if isinstance(d, int) and d == 0:
        return "0000-00"
    if isinstance(d, str):
        s = d.strip()
        if not s:
            return "0000-00"
        # Aceptar 'YYYY-MM', 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS', etc.
        if len(s) >= 7 and s[4:5] == "-" and (len(s) <= 7 or s[7:8] in ("-", " ", "T")):
            year = s[0:4]
            month = s[5:7]
            if year.isdigit() and month.isdigit():
                return f"{year}-{month}"
        # ISO datetime con 'T'
        if "T" in s:
            s = s.split("T")[0]
            if len(s) >= 7 and s[4:5] == "-":
                return f"{s[0:4]}-{s[5:7]}"
        try:
            d = _dt.fromisoformat(s.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                d = _dt.strptime(s[:10], "%Y-%m-%d").date()
            except ValueError:
                return "0000-00"
    if isinstance(d, _dt):
        d = d.date()
    if not isinstance(d, _date):
        return "0000-00"
    return f"{d.year:04d}-{d.month:02d}"


def is_valid_period_key(key: str | None) -> bool:
    """True si la key tiene formato 'YYYY-MM' y año/mes razonables."""
    if not key or not isinstance(key, str):
        return False
    if len(key) != 7 or key[4] != "-":
        return False
    try:
        y, m = int(key[0:4]), int(key[5:7])
    except ValueError:
        return False
    if y < 1900 or y > 2999 or m < 1 or m > 12:
        return False
    return True


def _coerce_period_key(key: str | None) -> str | None:
    """Convierte 'YYYY-MM-DD...' o 'YYYY-MM-DDTHH:MM' → 'YYYY-MM'."""
    if not is_valid_period_key(key):
        # Si parece fecha completa, intentar recortar
        if isinstance(key, str) and len(key) >= 7 and key[4:5] == "-":
            cand = key[0:7]
            if is_valid_period_key(cand):
                return cand
        return None
    return key


def validate_period_keys(
    keys: Iterable[str], *, drop_invalid: bool = True
) -> list[str]:
    """Filtra y ordena keys. Si drop_invalid=True (default) elimina las que
    no son 'YYYY-MM' válidas (incluido el sentinel '0000-00').

    Devuelve SIEMPRE una lista sin keys vacías/null/undefined/0.
    """
    out: list[str] = []
    seen = set()
    for k in keys:
        if not k or not isinstance(k, str):
            continue
        if k in seen:
            continue
        if drop_invalid and not is_valid_period_key(k):
            continue
        out.append(k)
        seen.add(k)
    out.sort()
    return out


# ── display_label ─────────────────────────────────────────

def display_label_from_key(
    key: str | None,
    *,
    locale: str = "es",
    fallback: str = "—",
) -> str:
    """'YYYY-MM' → 'MMM-YY' (ej: '2026-08' → 'ago-26' en ES).

    Garantiza NUNCA devolver '0', 'undefined', 'null' ni cadena vacía:
    en key inválida → fallback ('—' por defecto).
    """
    key = _coerce_period_key(key)
    if not is_valid_period_key(key):
        return fallback
    y, m = int(key[0:4]), int(key[5:7])
    months = _MONTHS_ES_SHORT if locale == "es" else _MONTHS_EN_SHORT
    return f"{months[m - 1]}-{str(y)[-2:]}"


def display_label_full(key: str | None, *, fallback: str = "—") -> str:
    """'YYYY-MM' → 'agosto 2026' (legible completo, ES)."""
    key = _coerce_period_key(key)
    if not is_valid_period_key(key):
        return fallback
    y, m = int(key[0:4]), int(key[5:7])
    months_full = (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    )
    return f"{months_full[m - 1]} {y}"


# ── YTD y Total período ───────────────────────────────────

def ytd_dates(reference: _date | str) -> tuple[_date, _date]:
    """Devuelve (1 enero, reference) del año natural.

    Si reference = '2026-08-15' → (2026-01-01, 2026-08-15).
    """
    if isinstance(reference, str):
        s = reference.strip()[:10]
        try:
            ref = _dt.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            ref = _date.today()
    elif isinstance(reference, _dt):
        ref = reference.date()
    elif isinstance(reference, _date):
        ref = reference
    else:
        ref = _date.today()
    return _date(ref.year, 1, 1), ref


def total_period_dates(
    period_from: str, period_to: str
) -> tuple[_date, _date]:
    """Devuelve el rango seleccionado (ya validado)."""
    try:
        d_from = _dt.strptime(period_from, "%Y-%m-%d").date()
        d_to = _dt.strptime(period_to, "%Y-%m-%d").date()
    except ValueError:
        # Fechas inválidas → fallback a mes en curso
        today = _date.today()
        d_from = today.replace(day=1)
        d_to = today
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    return d_from, d_to


def is_multi_year(d_from: _date, d_to: _date) -> bool:
    """True si el rango seleccionado cruza más de un año natural."""
    return d_from.year != d_to.year


def split_ytd_and_period(
    d_from: _date, d_to: _date
) -> dict:
    """Devuelve las dos ventanas que el dashboard debe mostrar:

        {
          "ytd":     {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
          "period":  {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
          "spans_multiple_years": bool,
          "labels": {
            "ytd_label": "YTD 2026",
            "period_label": "Período seleccionado"
          }
        }
    """
    spans = is_multi_year(d_from, d_to)
    ytd_from, ytd_to = ytd_dates(d_to)
    return {
        "ytd": {
            "from": ytd_from.isoformat(),
            "to": ytd_to.isoformat(),
        },
        "period": {
            "from": d_from.isoformat(),
            "to": d_to.isoformat(),
        },
        "spans_multiple_years": spans,
        "labels": {
            "ytd_label": f"YTD {d_to.year}",
            "period_label": "Período seleccionado" if spans else "Período",
        },
    }


# ── Etiquetas de meses en series temporales ────────────────

def fill_month_gaps(
    keys: Iterable[str],
    *,
    end_reference: _date | str | None = None,
) -> list[str]:
    """Garantiza serie mensual continua.

    Si tienes ['2026-05', '2026-08'] te devuelve
    ['2026-05', '2026-06', '2026-07', '2026-08'].

    Si end_reference es None usa mes actual. El último mes devuelto es
    SIEMPRE el mes de end_reference (aunque no esté en keys).
    """
    keys = validate_period_keys(keys, drop_invalid=True)
    if not keys:
        # Devolver los últimos 6 meses hasta el reference
        ref = end_reference
        if isinstance(ref, str):
            ref = _dt.strptime(ref.strip()[:10], "%Y-%m-%d").date() if ref else _date.today()
        elif isinstance(ref, _dt):
            ref = ref.date()
        elif not isinstance(ref, _date):
            ref = _date.today()
        first = ref.replace(day=1)
        out = []
        for i in range(5, -1, -1):
            y = first.year
            m = first.month - i
            while m <= 0:
                m += 12
                y -= 1
            out.append(f"{y:04d}-{m:02d}")
        return out

    last = keys[-1]
    if end_reference is not None:
        if isinstance(end_reference, str):
            end_ref_str = period_key_from_date(end_reference)
        elif isinstance(end_reference, _dt):
            end_ref_str = period_key_from_date(end_reference.date())
        elif isinstance(end_reference, _date):
            end_ref_str = period_key_from_date(end_reference)
        else:
            end_ref_str = last
        if is_valid_period_key(end_ref_str) and end_ref_str > last:
            last = end_ref_str

    # Rellenar huecos mes a mes
    out = [keys[0]]
    cy, cm = int(keys[0][0:4]), int(keys[0][5:7])
    ey, em = int(last[0:4]), int(last[5:7])
    while (cy, cm) < (ey, em):
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1
        out.append(f"{cy:04d}-{cm:02d}")
    return out


# ── Helper para construir filas mensuales "limpias" ───────

def build_monthly_row(
    key: str,
    *,
    ingresos: float = 0.0,
    gastos: float = 0.0,
    margen: float | None = None,
    n_facturas: int = 0,
) -> dict:
    """Crea una fila mensual con SIEMPRE period_key + display_label válidos.

    margen se calcula automáticamente si es None.
    """
    key = _coerce_period_key(key) or "0000-00"
    valid = is_valid_period_key(key)
    return {
        "period_key": key if valid else "0000-00",
        "display_label": display_label_from_key(key) if valid else "—",
        "year": int(key[0:4]) if valid else 0,
        "month": int(key[5:7]) if valid else 0,
        "ingresos": round(float(ingresos), 2),
        "gastos": round(float(gastos), 2),
        "margen": round(
            float(margen if margen is not None else ingresos - gastos), 2
        ),
        "n_facturas": int(n_facturas),
    }


def build_ytd_row(
    year: int,
    *,
    ingresos: float = 0.0,
    gastos: float = 0.0,
    margen: float | None = None,
    n_facturas: int = 0,
) -> dict:
    """Fila YTD explícita (acumulado desde 1 enero hasta fin del período)."""
    return {
        "period_key": f"YTD-{year:04d}",
        "display_label": f"YTD {year}",
        "year": year,
        "month": 0,
        "ingresos": round(float(ingresos), 2),
        "gastos": round(float(gastos), 2),
        "margen": round(
            float(margen if margen is not None else ingresos - gastos), 2
        ),
        "n_facturas": int(n_facturas),
        "is_ytd": True,
    }
