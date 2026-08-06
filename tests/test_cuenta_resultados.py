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
 assert out["totals"]["ventas_netas"]==1500.0
 assert out["totals"]["food_cost"]==165.0
 assert out["totals"]["personal"]==200.0
 assert out["totals"]["otros_explotacion"]==121.0
 assert out["totals"]["ebitda"]==1014.0
 food=next(r for r in out["rows"] if r["code"]=="food_cost")
 assert len(food["children"])==1
 assert len({r["provider_key"] for r in food["children"]})==1
 assert food["values"]["2026-01"]==-165.0
 assert food["values"]["YTD"]==-165.0
def test_iva_is_separated_from_net_sales():
 out=build_cuenta_resultados(ROWS,SALES,"2026-01-01","2026-02-28")
 assert out["totals"]["ventas_sin_iva"]==1363.64
 assert out["totals"]["iva_ventas"]==136.36
 assert out["totals"]["iva_gastos"]==36.0
