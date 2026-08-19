import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))
from cuenta_resultados import build_cuenta_resultados, normalize_provider
ROWS = [
 {"invoice_date":"2026-01-05","vendor_name":"Makro Málaga","category_raw":"Alimentación","total_amount":110.0,"base_amount":100.0,"tax_amount":10.0},
 {"invoice_date":"2026-01-15","vendor_name":"MAKRO DISTRIBUCION MAYORISTA, S.A","category_raw":"Alimentación","total_amount":55.0,"base_amount":50.0,"tax_amount":5.0},
 {"invoice_date":"2026-02-05","vendor_name":"Nómina Ana","category_raw":"Nóminas","total_amount":200.0,"base_amount":200.0,"tax_amount":0.0},
 {"invoice_date":"2026-02-07","vendor_name":"Iberdrola Clientes S.A.U.","category_raw":"Luz","total_amount":121.0,"base_amount":100.0,"tax_amount":21.0},
]
SALES = [
 {"invoice_date":"2026-01-10","vendor_name":"Last.app","category_raw":"Ventas","total_amount":1000.0,"base_amount":909.09,"tax_amount":90.91},
 {"invoice_date":"2026-02-10","vendor_name":"Last.app","category_raw":"Ventas","total_amount":500.0,"base_amount":454.55,"tax_amount":45.45},
]
def test_provider_normalization_deduplicates_company_suffixes():
 assert normalize_provider("VAMOS AL LÍO, S.L.") == "vamos al lio"

def test_monthly_ytd_and_provider_breakdown():
 out=build_cuenta_resultados(ROWS,SALES,"2026-01-01","2026-02-28")
 assert out["columns"]==["2026-01","2026-02","YTD"]
 assert out["totals"]["ventas_brutas"]==1500.0
 assert out["totals"]["ventas_netas"]==1363.64
 assert out["totals"]["food_cost"]==165.0
 assert out["totals"]["personal"]==200.0
 assert out["totals"]["otros_explotacion"]==121.0
 assert out["totals"]["marketing"]==0.0
 # Sin sub-clasificación de personal (las reglas no reconocen "Nóminas" → va a personal pero vendor "Nómina Ana" no contiene keywords)
 # Por tanto nóminas/SS/otros no se muestran como sub-filas reales
 # EBIT = EBITDA (amortización=0)
 assert out["totals"]["ebitda"] == out["totals"]["ebit"]
 # Impuesto sociedades sin datos = 0
 assert out["totals"]["impuesto_sociedades"] == 0.0
 # Resultado ejercicio = Resultado antes de impuestos (sin impuesto ni financiero)
 assert out["totals"]["resultado_ejercicio"] == out["totals"]["resultado_antes_impuestos"]
 food=next(r for r in out["rows"] if r["code"]=="food_cost")
 provider_group=next(r for r in food["children"] if r.get("kind")=="provider_group")
 providers=provider_group["children"]
 assert len(providers)==1
 assert len({r["provider_key"] for r in providers})==1
 assert food["values"]["2026-01"]==-165.0
 assert food["values"]["YTD"]==-165.0

def test_iva_is_separated_from_net_sales():
 out=build_cuenta_resultados(ROWS,SALES,"2026-01-01","2026-02-28")
 assert out["totals"]["ventas_netas"]==1363.64
 assert out["totals"]["iva_ventas"]==136.36
 assert out["totals"]["iva_gastos"]==36.0

def test_marketplace_legal_names_are_grouped_as_commissions():
    invoices = [
        {"invoice_date":"2026-01-05", "vendor_name":"Glovoapp Spain Platform S.L.", "category_raw":"Restauración y Hostelería", "total_amount":10.0, "base_amount":10.0, "tax_amount":0.0},
        {"invoice_date":"2026-01-06", "vendor_name":"Uber Eats España S.L.", "category_raw":"Otros", "total_amount":20.0, "base_amount":20.0, "tax_amount":0.0},
        {"invoice_date":"2026-01-07", "vendor_name":"LastShop, S.L.", "category_raw":"Otros", "total_amount":30.0, "base_amount":30.0, "tax_amount":0.0},
    ]
    out = build_cuenta_resultados(invoices, SALES, "2026-01-01", "2026-02-28")
    assert out["totals"]["comisiones"] == 60.0
    assert out["totals"]["otros_explotacion"] == 0.0
    # Con estos vendors reales, las sub-filas de comisiones SÍ existen
    comis=next(r for r in out["rows"] if r["code"]=="comisiones")
    sub_codes={c["code"] for c in comis["children"]}
    assert "comisiones.glovo" in sub_codes
    assert "comisiones.uber" in sub_codes
    assert "comisiones.lastshop" in sub_codes

def test_reference_sales_rows_channels_and_ytd_exclude_previous_december():
    sales = [
        {"invoice_date":"2025-12-10","total_amount":55.0,"base_amount":50.0,"tax_amount":5.0,"discount_amount":0.0},
        {"invoice_date":"2026-01-10","total_amount":110.0,"base_amount":100.0,"tax_amount":10.0,"discount_amount":11.0},
    ]
    channels = [
        {"invoice_date":"2026-01-10","channel":"card","amount_gross":55.0,"amount_net":50.0},
        {"invoice_date":"2026-01-10","channel":"cash","amount_gross":22.0,"amount_net":20.0},
        {"invoice_date":"2026-01-10","channel":"uber","amount_gross":33.0,"amount_net":30.0},
    ]
    out=build_cuenta_resultados([],sales,"2025-12-01","2026-12-31",channel_rows=channels)
    rows={r["code"]:r for r in out["rows"]}
    assert rows["ventas"]["values"]["2026-01"] == 110.0
    assert rows["ventas"]["values"]["YTD"] == 110.0
    children={r["code"]:r for r in rows["ventas"]["children"]}
    assert children["venta_bruta_descuentos"]["values"]["2026-01"] == 121.0
    assert children["venta_neta"]["values"]["2026-01"] == 100.0
    assert children["venta_bruta"]["values"]["2026-01"] == 110.0
    assert children["descuentos"]["values"]["2026-01"] == 11.0
    assert children["ventas.channel.restaurant"]["values"]["2026-01"] == 70.0
    assert children["ventas.channel.restaurant_gross"]["values"]["2026-01"] == 77.0
    assert children["ventas.channel.delivery"]["values"]["2026-01"] == 30.0

def test_accounting_rows_only_real_values_no_fabrication():
    """Solo se incluyen sub-filas con datos reales. No se inventan cifras."""
    out=build_cuenta_resultados(ROWS,SALES,"2026-01-01","2026-02-28")
    rows={r["code"]:r for r in out["rows"]}
    # Estructura principal siempre presente
    for code in ("ventas","food_cost","margen_bruto","comisiones","margen_contribucion","personal","ebitda","ebit","resultado_antes_impuestos","resultado_ejercicio"):
        assert code in rows, f"{code} debería estar"
    # Amortización, financiero e impuesto: 0 hasta que haya datos
    assert rows["amortizacion"]["values"]["YTD"] == 0.0
    assert rows["resultado_financiero"]["values"]["YTD"] == 0.0
    assert rows["impuesto_sociedades"]["values"]["YTD"] == 0.0
    # Sub-filas solo si hay datos reales: en este test no hay facturas Glovo/Uber/LastShop,
    # así que comisiones no debe tener sub-filas (children=[])
    comis=rows["comisiones"]
    assert all(c["kind"]!="subcategory" for c in comis["children"]), "comisiones no debe tener sub-filas inventadas sin datos"
    assert rows["resultado_ejercicio"]["kind"] == "subtotal"
    codes = [r["code"] for r in out["rows"]]
    assert codes[-1] == "resultado_ejercicio_pct"