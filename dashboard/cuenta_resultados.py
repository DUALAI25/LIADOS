"""Cuenta de resultados mensual fiel a la estructura Excel de Liados."""
from __future__ import annotations
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
try:
    from .desglose_pyg_rules import classify_factura, load_rules
except ImportError:
    from desglose_pyg_rules import classify_factura, load_rules

_PROVIDER_ALIASES = (
    ("makro", "Makro"), ("envases para profesionales", "Envases para profesionales"),
    ("mercadona", "Mercadona"), ("vamos al lio", "Vamos al Lío"),
    ("iberdrola", "Iberdrola"), ("trello", "Trello"), ("hp printing", "HP Printing"),
    ("met energia", "MET Energía"), ("creaciones danimobel", "Creaciones Danimobel"),
    ("leroy merlin", "Leroy Merlin"), ("ikea", "IKEA"), ("repsol", "Repsol"),
    ("atlanta frutas", "Atlanta Frutas"), ("glovo", "Glovo"),
    ("uber eats", "Uber Eats"), ("last shop", "Last Shop"),
)

def _strip_text(value):
    text=unicodedata.normalize("NFKD",str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower().strip()

def normalize_provider(value):
    text=re.sub(r"[,.()]+"," ",_strip_text(value))
    text=re.sub(r"\b(?:s\s*l(?:\s*u)?|s\s*a(?:\s*u)?|cb|gmbh|ltd|inc)\b"," ",text)
    return re.sub(r"\s+"," ",text).strip()

def provider_label(value):
    key=normalize_provider(value)
    for alias,label in _PROVIDER_ALIASES:
        if alias in key: return label
    return str(value or "Proveedor sin nombre").strip() or "Proveedor sin nombre"

def _date_value(value):
    if isinstance(value,datetime): return value.date()
    if isinstance(value,date): return value
    if not value: return None
    try: return datetime.fromisoformat(str(value).replace("Z","+00:00")).date()
    except ValueError: return datetime.strptime(str(value)[:10],"%Y-%m-%d").date()

def _eur(value):
    try: return round(float(value or 0),2)
    except (TypeError,ValueError): return 0.0

def _month_keys(start,end):
    out=[]; year,month=start.year,start.month
    while (year,month)<=(end.year,end.month):
        out.append(f"{year:04d}-{month:02d}"); month+=1
        if month==13: year,month=year+1,1
    return out

def _ytd_months(months):
    year=months[-1][:4]
    return [m for m in months if m.startswith(year+"-")]

def _values(months,data):
    result={m:round(data.get(m,0.0),2) for m in months}
    result["YTD"]=round(sum(result[m] for m in _ytd_months(months)),2)
    return result

def _unavailable_values(months):
    return {m:None for m in months+["YTD"]}

def _ratio_values(months,numerator,denominator,sign=1.0):
    values={m:round(sign*numerator.get(m,0.0)/denominator.get(m,0.0),4) if denominator.get(m,0.0) else 0.0 for m in months}
    ytd=_ytd_months(months); num=sum(numerator.get(m,0.0) for m in ytd); den=sum(denominator.get(m,0.0) for m in ytd)
    values["YTD"]=round(sign*num/den,4) if den else 0.0
    return values

def _row(code,label,months,data=None,*,kind="line",level=0,children=None,availability="real",section=False,precomputed=False):
    if availability=="unavailable": values=_unavailable_values(months)
    elif precomputed: values=data
    else: values=_values(months,data or {})
    return {"code":code,"label":label,"values":values,"kind":kind,"level":level,"children":children or [],"availability":availability,"section":section}

def _provider_children(rows,months,bucket,rules):
    totals=defaultdict(lambda:defaultdict(float)); labels={}
    for row in rows:
        category=str(row.get("category_raw") or row.get("category") or "")
        vendor=row.get("vendor_name") or row.get("vendor") or "Proveedor sin nombre"
        if classify_factura(category,vendor,rules=rules)!=bucket: continue
        d=_date_value(row.get("invoice_date"))
        if not d: continue
        label=provider_label(vendor); key=normalize_provider(label) or "proveedor sin nombre"
        labels.setdefault(key,label); totals[key][f"{d.year:04d}-{d.month:02d}"]-=abs(_eur(row.get("total_amount")))
    return [{"code":f"{bucket}.provider.{key}","label":labels[key],"provider_key":key,"values":_values(months,totals[key]),"kind":"provider","level":1,"children":[],"availability":"real"} for key in sorted(totals,key=lambda k:(sum(totals[k].values()),labels[k].lower()))]

def _provider_group(code,months,providers):
    if not providers: return []
    children=[]
    for provider in providers:
        item={**provider,"level":2}; children.append(item)
    totals={m:sum((p["values"].get(m) or 0) for p in children) for m in months}
    return [_row(f"{code}.providers","Proveedores",months,totals,kind="provider_group",level=1,children=children,availability="real")]

def _merge_provider_children(groups,months):
    merged={}
    for group in groups:
        for child in group:
            key=child["provider_key"]
            if key not in merged: merged[key]={**child,"values":dict(child["values"])}
            else:
                for month in months+["YTD"]: merged[key]["values"][month]=round(merged[key]["values"].get(month,0)+child["values"].get(month,0),2)
    return sorted(merged.values(),key=lambda c:(c["values"].get("YTD",0),c["label"].lower()))

def _channel_series(rows,months):
    net=defaultdict(lambda:defaultdict(float)); gross=defaultdict(lambda:defaultdict(float))
    for row in rows or []:
        d=_date_value(row.get("invoice_date"))
        if not d: continue
        month=f"{d.year:04d}-{d.month:02d}"; channel=str(row.get("channel") or "other").lower()
        gross[channel][month]+=_eur(row.get("amount_gross",row.get("amount")))
        net[channel][month]+=_eur(row.get("amount_net",row.get("amount")))
    def combine(source,names): return {m:sum(source[name].get(m,0.0) for name in names) for m in months}
    result={}
    mapping={"restaurant":("card","cash"),"takeaway":("shop",),"delivery":("uber","glovo","justeat"),"uber":("uber",),"glovo":("glovo",),"justeat":("justeat",)}
    for key,names in mapping.items():
        result[key+"_net"]=combine(net,names); result[key+"_gross"]=combine(gross,names)
    return result

def _channel_rows(months,series,*,gross=False,include_unavailable=True):
    suffix="_gross" if gross else "_net"; code_suffix="_gross" if gross else ""
    labels=[("restaurant","Restaurant"),("takeaway","Take away"),("delivery","Delivery")]
    rows=[_row(f"ventas.channel.{key}{code_suffix}",label+(" C/IVA" if gross else ""),months,series[key+suffix],kind="channel",level=1) for key,label in labels]
    if include_unavailable: rows.append(_row(f"ventas.channel.delivery_own{code_suffix}","Delivery propio"+(" C/IVA" if gross else ""),months,availability="unavailable",kind="channel",level=2))
    rows.extend(_row(f"ventas.channel.{key}{code_suffix}",label+(" C/IVA" if gross else ""),months,series[key+suffix],kind="channel",level=2) for key,label in (("uber","Uber"),("glovo","Glovo"),("justeat","Just Eat")))
    return rows

def _allocate_cost(months,costs,series):
    allocated={key:{m:0.0 for m in months} for key in ("restaurant","takeaway","delivery","uber","glovo","justeat")}
    for m in months:
        denominator=sum(series[key+"_net"].get(m,0.0) for key in ("restaurant","takeaway","delivery"))
        if not denominator: continue
        for key in allocated: allocated[key][m]=-costs.get(m,0.0)*series[key+"_net"].get(m,0.0)/denominator
    return allocated

def _allocated_channel_rows(months,allocated,prefix,label_prefix=""):
    rows=[]
    for key,label,level in (("restaurant","Restaurant",1),("takeaway","Take away",1),("delivery","Delivery",1),("uber","Uber",2),("glovo","Glovo",2),("justeat","Just Eat",2)):
        rows.append(_row(f"{prefix}.channel.{key}",label_prefix+label,months,allocated[key],kind="channel_allocated",level=level,availability="allocated"))
    rows.insert(3,_row(f"{prefix}.channel.delivery_own",label_prefix+"Delivery propio",months,availability="unavailable",kind="channel_allocated",level=2))
    return rows

def build_cuenta_resultados(invoice_rows,sales_rows,period_from,period_to,cuenta=None,rules=None,channel_rows=None):
    start=_date_value(period_from); end=_date_value(period_to)
    if not start or not end or start>end: raise ValueError("Periodo inválido")
    months=_month_keys(start,end); rules=rules or load_rules()
    gross_after=defaultdict(float); net_after=defaultdict(float); tax=defaultdict(float); discount_gross=defaultdict(float); discount_net=defaultdict(float)
    for row in sales_rows or []:
        d=_date_value(row.get("invoice_date"))
        if not d or d<start or d>end: continue
        m=f"{d.year:04d}-{d.month:02d}"; gross=_eur(row.get("total_amount")); net=_eur(row.get("base_amount")); disc=_eur(row.get("discount_amount"))
        gross_after[m]+=gross; net_after[m]+=net; tax[m]+=_eur(row.get("tax_amount")); discount_gross[m]+=disc
        discount_net[m]+=disc*(net/gross) if gross else 0.0
    gross_after={m:gross_after.get(m,0.0) for m in months}; net_after={m:net_after.get(m,0.0) for m in months}; tax={m:tax.get(m,0.0) for m in months}; discount_gross={m:discount_gross.get(m,0.0) for m in months}; discount_net={m:discount_net.get(m,0.0) for m in months}
    gross_before={m:gross_after[m]+discount_gross[m] for m in months}; net_before={m:net_after[m]+discount_net[m] for m in months}
    buckets={b:defaultdict(float) for b in ("food_cost","comisiones","personal","otros_explotacion")}; expense_tax=defaultdict(float); expense_rows=[]
    for row in invoice_rows or []:
        d=_date_value(row.get("invoice_date"))
        if not d or d<start or d>end: continue
        if cuenta and str(row.get("source_account") or "").lower()!=cuenta.lower(): continue
        m=f"{d.year:04d}-{d.month:02d}"; amount=abs(_eur(row.get("total_amount"))); category=str(row.get("category_raw") or row.get("category") or ""); vendor=row.get("vendor_name") or ""; bucket=classify_factura(category,vendor,rules=rules)
        target="food_cost" if bucket=="aprovisionamientos" else "comisiones" if bucket=="comisiones" else "personal" if bucket=="personal" else "otros_explotacion"
        buckets[target][m]+=amount; expense_tax[m]+=_eur(row.get("tax_amount")); expense_rows.append(row)
    food={m:buckets["food_cost"].get(m,0) for m in months}; commissions={m:buckets["comisiones"].get(m,0) for m in months}; personal={m:buckets["personal"].get(m,0) for m in months}; other={m:buckets["otros_explotacion"].get(m,0) for m in months}
    margin_gross={m:net_before[m]-food[m] for m in months}; margin_contrib={m:margin_gross[m]-commissions[m] for m in months}; ebitda={m:margin_contrib[m]-personal[m]-other[m] for m in months}
    channel_series=_channel_series(channel_rows,months); food_alloc=_allocate_cost(months,food,channel_series)
    margin_alloc={key:{m:channel_series[key+"_net"].get(m,0)+food_alloc[key].get(m,0) for m in months} for key in food_alloc}
    sales_children=[
        _row("venta_bruta_descuentos","Venta bruta + descuentos",months,gross_before,kind="sales_primary",level=1),
        _row("venta_neta","Venta neta",months,net_after,kind="sales_detail",level=1),
        _row("venta_bruta","Venta bruta",months,gross_after,kind="sales_detail",level=1),
        _row("descuentos","Descuentos",months,discount_gross,kind="sales_detail",level=1),
    ]+_channel_rows(months,channel_series,gross=False)+_channel_rows(months,channel_series,gross=True)
    food_providers=_provider_children(expense_rows,months,"aprovisionamientos",rules)
    food_children=_allocated_channel_rows(months,food_alloc,"food_cost")+_provider_group("food_cost",months,food_providers)
    margin_children=_allocated_channel_rows(months,margin_alloc,"margen_bruto")
    rows=[
        _row("ventas","1  Venta neta + descuentos",months,net_before,kind="section",section=True,children=sales_children),
        _row("food_cost","2  Food cost",months,{m:-food[m] for m in months},kind="section",section=True,children=food_children),
        _row("food_cost_pct","%",months,_ratio_values(months,food,net_before,sign=-1),kind="percentage",precomputed=True),
        _row("margen_bruto","3  Margen Bruto",months,margin_gross,kind="subtotal",section=True,children=margin_children),
        _row("margen_bruto_pct","%",months,_ratio_values(months,margin_gross,net_before),kind="percentage",precomputed=True),
        _row("margen_contribucion","4  Margen de Contribución",months,margin_contrib,kind="subtotal",section=True,children=_provider_group("margen_contribucion",months,_provider_children(expense_rows,months,"comisiones",rules))),
        _row("margen_contribucion_pct","%",months,_ratio_values(months,margin_contrib,net_before),kind="percentage",precomputed=True),
        _row("personal","5  Gastos de personal",months,{m:-personal[m] for m in months},kind="section",section=True,children=_provider_group("personal",months,_provider_children(expense_rows,months,"personal",rules))),
        _row("personal_pct","%",months,_ratio_values(months,personal,net_before,sign=-1),kind="percentage",precomputed=True),
    ]
    other_children=_merge_provider_children([_provider_children(expense_rows,months,"otros_gastos",rules),_provider_children(expense_rows,months,"servicios",rules),_provider_children(expense_rows,months,"otros_gastos_produccion",rules)],months)
    rows.extend([
        _row("otros_explotacion","6  Otros gastos de explotación",months,{m:-other[m] for m in months},kind="section",section=True,children=_provider_group("otros_explotacion",months,other_children)),
        _row("otros_explotacion_pct","%",months,_ratio_values(months,other,net_before,sign=-1),kind="percentage",precomputed=True),
        _row("ebitda","7  EBITDA",months,ebitda,kind="subtotal",section=True),
        _row("ebitda_pct","%",months,_ratio_values(months,ebitda,net_before),kind="percentage",precomputed=True),
        _row("amortizacion","Amortización y depreciación",months,availability="unavailable"),
        _row("ebit","EBIT",months,availability="unavailable",kind="accounting_pending"),
        _row("resultado_financiero","Resultado financiero",months,availability="unavailable"),
        _row("resultado_antes_impuestos","Resultado antes de impuestos",months,availability="unavailable",kind="accounting_pending"),
        _row("impuesto_sociedades","Impuesto de sociedades",months,availability="unavailable"),
        _row("resultado_antes_impuestos_pct","% s/resultado antes de impuestos",months,availability="unavailable",kind="percentage"),
        _row("resultado_ejercicio","8  Resultado del ejercicio",months,availability="unavailable",kind="subtotal",section=True),
    ])
    ytd=_ytd_months(months); total=lambda series:round(sum(series.get(m,0) for m in ytd),2)
    totals={"ventas_netas_descuentos":total(net_before),"ventas_netas":total(net_after),"ventas_brutas":total(gross_after),"descuentos":total(discount_gross),"iva_ventas":total(tax),"iva_gastos":total(expense_tax),"food_cost":total(food),"comisiones":total(commissions),"personal":total(personal),"otros_explotacion":total(other),"margen_bruto":total(margin_gross),"margen_contribucion":total(margin_contrib),"ebitda":total(ebitda),"resultado_ejercicio":None}
    totals["margen_bruto_pct"]=round(totals["margen_bruto"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0
    totals["margen_contribucion_pct"]=round(totals["margen_contribucion"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0
    totals["ebitda_pct"]=round(totals["ebitda"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0
    issues=[{"code":"channel_mapping","level":"info","message":"Restaurant=card+cash y Take away=shop; son tipos de pago, no el canal comercial original."},{"code":"food_cost_allocated","level":"info","message":"Food cost por canal está prorrateado según ventas netas por tipo de pago."},{"code":"accounting_missing","level":"info","message":"Amortización, resultado financiero e impuesto de sociedades no están disponibles; EBIT y resultado quedan N/D."}]
    return {"period":{"from":start.isoformat(),"to":end.isoformat()},"columns":months+["YTD"],"rows":rows,"totals":totals,"issues":issues,"rows_used":len(expense_rows)+len(sales_rows or [])}
