"""Cuenta de resultados mensual fiel a la estructura Excel de Liados.

Todos los valores son REALES extraídos de la BD. Las sub-filas solo aparecen cuando
hay datos concretos en facturas/categorías/proveedores. Las filas sin datos
(amortización, financiero) se muestran con valor 0 y un issue informativo."""
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
    ("met energia", "MET Energía"), ("creaciones_danimobel", "Creaciones Danimobel"),
    ("leroy_merlin", "Leroy Merlin"), ("ikea", "IKEA"), ("repsol", "Repsol"),
    ("atlanta_frutas", "Atlanta Frutas"), ("glovo", "Glovo"),
    ("uber_eats", "Uber Eats"), ("last_shop", "Last Shop"),
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

def _zero_values(months):
    return {m:0.0 for m in months+["YTD"]}

def _ratio_values(months,numerator,denominator,sign=1.0):
    values={m:round(sign*numerator.get(m,0.0)/denominator.get(m,0.0),4) if denominator.get(m,0.0) else 0.0 for m in months}
    ytd=_ytd_months(months); num=sum(numerator.get(m,0.0) for m in ytd); den=sum(denominator.get(m,0.0) for m in ytd)
    values["YTD"]=round(sign*num/den,4) if den else 0.0
    return values

def _row(code,label,months,data=None,*,kind="line",level=0,children=None,availability="real",section=False,precomputed=False):
    if availability=="unavailable": values={m:None for m in months+["YTD"]}
    elif precomputed: values=data
    elif data is None: values=_zero_values(months)
    else: values=_values(months,data)
    return {"code":code,"label":label,"values":values,"kind":kind,"level":level,"children":children or [],"availability":availability,"section":section}

def _provider_children_filtered(rows,months,vendor_filter):
    """Solo devuelve proveedores que cumplen vendor_filter) y tienen datos reales."""
    totals=defaultdict(lambda:defaultdict(float)); labels={}
    for row in rows:
        vendor=row.get("vendor_name") or row.get("vendor") or ""
        if not vendor_filter(normalize_provider(vendor)): continue
        d=_date_value(row.get("invoice_date"))
        if not d: continue
        label=provider_label(vendor); key=normalize_provider(label) or "proveedor sin nombre"
        labels.setdefault(key,label); totals[key][f"{d.year:04d}-{d.month:02d}"]-=abs(_eur(row.get("total_amount")))
    return [{"code":f"provider.{key}","label":labels[key],"provider_key":key,"values":_values(months,totals[key]),"kind":"provider","level":1,"children":[],"availability":"real"} for key in sorted(totals,key=lambda k:(sum(totals[k].values()),labels[k].lower()))]

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

def _channel_rows(months,series,*,gross=False,include_unavailable=False):
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
    return rows

def _real_vendor_split_by_name(rows,months,name_keywords):
    """Genera series mensuales por marketplace real basado en nombre del vendor. SOLO datos reales.

    Cada keyword es una lista de substrings (OR)."""
    series={key:defaultdict(float) for key in name_keywords}
    for row in rows:
        vendor=row.get("vendor_name") or ""
        norm=normalize_provider(vendor)
        d=_date_value(row.get("invoice_date"))
        if not d: continue
        m=f"{d.year:04d}-{d.month:02d}"
        amount=abs(_eur(row.get("total_amount")))
        for key,kws in name_keywords.items():
            if any(kw in norm for kw in kws):
                series[key][m]-=amount
                break
    return {key:dict(series[key]) for key in name_keywords}

def _real_category_split(rows,months,target_category):
    """Genera serie mensual real por nombre de categoría (no estimación)."""
    series=defaultdict(float)
    for row in rows:
        cat=str(row.get("category_raw") or row.get("category") or "")
        if cat.lower()!=target_category.lower(): continue
        d=_date_value(row.get("invoice_date"))
        if not d: continue
        m=f"{d.year:04d}-{d.month:02d}"
        series[m]-=abs(_eur(row.get("total_amount")))
    return dict(series)

def _real_vendor_personal_split(rows,months):
    """Sub-división real de personal por keyword en vendor_name."""
    buckets={"\u00fanica":"\u00fanica"}  # noop, replaced below
    series_nominas=defaultdict(float)
    series_ss=defaultdict(float)
    series_otros=defaultdict(float)
    for row in rows:
        cat=str(row.get("category_raw") or row.get("category") or "")
        bucket=classify_factura(cat,row.get("vendor_name") or "",rules=load_rules())
        if bucket!="personal": continue
        d=_date_value(row.get("invoice_date"))
        if not d: continue
        m=f"{d.year:04d}-{d.month:02d}"
        amount=abs(_eur(row.get("total_amount")))
        vendor_norm=normalize_provider(row.get("vendor_name") or "")
        # Solo datos reales: clasificación por nombre del proveedor
        if "tgss" in vendor_norm or "seguridad" in vendor_norm or "social" in vendor_norm:
            series_ss[m]-=amount
        elif "nomina" in vendor_norm or "payroll" in vendor_norm or "sueldo" in vendor_norm or "salario" in vendor_norm:
            series_nominas[m]-=amount
        # Si no matchea ninguno, NO se asigna a ninguna sub-fila (queda 0)
    return dict(series_nominas), dict(series_ss), dict(series_otros)

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
    buckets={b:defaultdict(float) for b in ("food_cost","comisiones","personal","otros_explotacion","marketing")}; expense_tax=defaultdict(float); expense_rows=[]
    for row in invoice_rows or []:
        d=_date_value(row.get("invoice_date"))
        if not d or d<start or d>end: continue
        if cuenta and str(row.get("source_account") or "").lower()!=cuenta.lower(): continue
        m=f"{d.year:04d}-{d.month:02d}"; amount=abs(_eur(row.get("total_amount"))); category=str(row.get("category_raw") or row.get("category") or ""); vendor=row.get("vendor_name") or ""; bucket=classify_factura(category,vendor,rules=rules)
        target="food_cost" if bucket=="aprovisionamientos" else "comisiones" if bucket=="comisiones" else "personal" if bucket=="personal" else "marketing" if bucket=="marketing" else "otros_explotacion"
        buckets[target][m]+=amount; expense_tax[m]+=_eur(row.get("tax_amount")); expense_rows.append(row)
    food={m:buckets["food_cost"].get(m,0) for m in months}; commissions={m:buckets["comisiones"].get(m,0) for m in months}; personal={m:buckets["personal"].get(m,0) for m in months}; other={m:buckets["otros_explotacion"].get(m,0) for m in months}; marketing={m:buckets["marketing"].get(m,0) for m in months}
    # SGG: estas categorías se extraen del bucket "otros_explotacion" para mostrarlas en "Otros gg. producción"
    sgg_categories=("Suministros","Servicios Profesionales","Alquiler","Gastos Bancarios","Seguros","Impuestos y Tasas","Oficina","Software y SaaS")
    sgg_series={}
    for cat_name in sgg_categories:
        series=_real_category_split(expense_rows,months,cat_name)
        if any(v!=0 for v in series.values()):
            sgg_series[cat_name]=series
    # Restar SGG de "other" para evitar doble contabilización
    sgg_total={m:sum((s.get(m,0) for s in sgg_series.values())) for m in months}
    other={m:other[m]-sgg_total[m] for m in months}
    margin_gross={m:net_before[m]-food[m] for m in months}; margin_contrib={m:margin_gross[m]-commissions[m]-marketing[m] for m in months}; ebitda={m:margin_contrib[m]-personal[m]-other[m]-sgg_total[m] for m in months}
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

    # === Comisiones SOLO por marketplace REAL (vendor_name) ===
    comisiones_real=_real_vendor_split_by_name(expense_rows,months,{"glovo":["glovo"],"uber":["uber eats","uber_eats"],"lastshop":["last shop","lastshop"],"justeat":["just eat","justeat"]})
    glovo_series=comisiones_real["glovo"]
    uber_series=comisiones_real["uber"]
    lastshop_series=comisiones_real["lastshop"]
    justeat_series=comisiones_real["justeat"]
    total_comisiones_real=sum((commissions.get(m,0) for m in months))
    # Sub-fila solo si tiene datos en el YTD Y las comisiones son >0
    has_glovo=any(v!=0 for v in glovo_series.values()) and total_comisiones_real > 0
    has_uber=any(v!=0 for v in uber_series.values()) and total_comisiones_real > 0
    has_lastshop=any(v!=0 for v in lastshop_series.values()) and total_comisiones_real > 0
    has_justeat=any(v!=0 for v in justeat_series.values()) and total_comisiones_real > 0
    comisiones_children=[]
    if has_glovo: comisiones_children.append(_row("comisiones.glovo","Glovo",months,glovo_series,kind="subcategory",level=1))
    if has_uber: comisiones_children.append(_row("comisiones.uber","Uber Eats",months,uber_series,kind="subcategory",level=1))
    if has_lastshop: comisiones_children.append(_row("comisiones.lastshop","Last Shop",months,lastshop_series,kind="subcategory",level=1))
    if has_justeat: comisiones_children.append(_row("comisiones.justeat","Just Eat",months,justeat_series,kind="subcategory",level=1))

    # Márketing: sub-categorías reales
    marketing_series=_real_category_split(expense_rows,months,"Marketing y Publicidad")

    # Personal: split real por vendor_name
    nominas_series, ss_series, otros_series=_real_vendor_personal_split(expense_rows,months)
    has_nominas=any(v!=0 for v in nominas_series.values())
    has_ss=any(v!=0 for v in ss_series.values())
    has_otros=any(v!=0 for v in otros_series.values())

    # Amortización, Financiero: 0 (sin datos reales)
    amortizacion_total={m:0.0 for m in months}
    ebit={m:ebitda[m]-amortizacion_total[m] for m in months}
    intereses={m:0.0 for m in months}; gastos_bancarios={m:0.0 for m in months}; dif_cambio={m:0.0 for m in months}
    resultado_financiero={m:intereses[m]+gastos_bancarios[m]+dif_cambio[m] for m in months}
    resultado_antes_impuestos={m:ebit[m]+resultado_financiero[m] for m in months}
    impuesto_sociedades={m:0.0 for m in months}  # 0 hasta que haya activo/pasivo real cargado
    resultado_ejercicio={m:resultado_antes_impuestos[m]-impuesto_sociedades[m] for m in months}

    rows=[
        _row("ventas","1  Venta neta + descuentos",months,net_before,kind="section",section=True,children=sales_children),
        _row("food_cost","2  Aprovisionamientos",months,{m:-food[m] for m in months},kind="section",section=True,children=food_children),
        _row("food_cost_pct","%",months,_ratio_values(months,food,net_before,sign=-1),kind="percentage",precomputed=True),
        _row("margen_bruto","3  Margen bruto (Venta N Des) Aprov.",months,margin_gross,kind="subtotal",section=True,children=margin_children),
        _row("margen_bruto_pct","%",months,_ratio_values(months,margin_gross,net_before),kind="percentage",precomputed=True),
        _row("comisiones","4  Comisiones",months,{m:-commissions[m] for m in months},kind="section",section=True,children=comisiones_children),
        _row("comisiones_pct","%",months,_ratio_values(months,commissions,net_before,sign=-1),kind="percentage",precomputed=True),
        _row("margen_contribucion","5  Margen de Contribución",months,margin_contrib,kind="subtotal",section=True),
        _row("margen_contribucion_pct","%",months,_ratio_values(months,margin_contrib,net_before),kind="percentage",precomputed=True),
    ]

    # Márketing como sección solo si hay datos
    if marketing and any(v!=0 for v in marketing.values()):
        rows.append(_row("marketing","  Márketing",months,{m:-marketing[m] for m in months},kind="section",section=False))
        rows.append(_row("marketing_pct","%",months,_ratio_values(months,marketing,net_before,sign=-1),kind="percentage",precomputed=True))

    # SGG: cada categoría real se muestra como sub-fila
    sgg_total={m:sum((s.get(m) or 0) for s in sgg_series.values()) for m in months}
    if sgg_series:
        sgg_children=[]
        for cat_name,series in sgg_series.items():
            if any(v!=0 for v in series.values()):
                sgg_children.append(_row(f"sgg.{cat_name.lower().replace(' ','_').replace('\u00ed','i').replace('\u00e1','a')}",cat_name,months,series,kind="subcategory",level=1))
        if sgg_children:
            rows.append(_row("otros_gg_produccion","  Otros gg. producción",months,{m:-sgg_total[m] for m in months},kind="section",section=False,children=sgg_children))
            rows.append(_row("otros_gg_produccion_pct","%",months,_ratio_values(months,sgg_total,net_before,sign=-1),kind="percentage",precomputed=True))

    rows.append(_row("resultado_explotacion","  Resultado bruto (Resultado Explotación)",months,margin_contrib,kind="subtotal",section=True))
    rows.append(_row("resultado_explotacion_pct","%",months,_ratio_values(months,margin_contrib,net_before),kind="percentage",precomputed=True))

    # Personal con sub-filas reales
    personal_children=[]
    if has_nominas: personal_children.append(_row("personal.nominas","Nóminas",months,nominas_series,kind="subcategory",level=1))
    if has_ss: personal_children.append(_row("personal.seguridad_social","Seguros sociales",months,ss_series,kind="subcategory",level=1))
    if has_otros: personal_children.append(_row("personal.otros","Otros",months,otros_series,kind="subcategory",level=1))
    personal_children.extend(_provider_group("personal",months,_provider_children(expense_rows,months,"personal",rules)))
    rows.append(_row("personal","6  Gastos Personal",months,{m:-personal[m] for m in months},kind="section",section=True,children=personal_children))
    rows.append(_row("personal_pct","%",months,_ratio_values(months,personal,net_before,sign=-1),kind="percentage",precomputed=True))

    rows.append(_row("ebitda","7  EBITDA",months,ebitda,kind="subtotal",section=True))
    rows.append(_row("ebitda_pct","%",months,_ratio_values(months,ebitda,net_before),kind="percentage",precomputed=True))

    # Amortización y resto: filas con 0 reales (sin datos)
    rows.append(_row("amortizacion","8  Amortización",months,{m:-amortizacion_total[m] for m in months},kind="section",section=False))
    rows.append(_row("ebit","9  EBIT",months,ebit,kind="subtotal",section=True))
    rows.append(_row("ebit_pct","%",months,_ratio_values(months,ebit,net_before),kind="percentage",precomputed=True))
    rows.append(_row("resultado_financiero","10  Resultado financiero",months,resultado_financiero,kind="section",section=False))
    rows.append(_row("resultado_antes_impuestos","11  Resultado antes de impuestos",months,resultado_antes_impuestos,kind="subtotal",section=True))
    rows.append(_row("resultado_antes_impuestos_pct","%",months,_ratio_values(months,resultado_antes_impuestos,net_before),kind="percentage",precomputed=True))
    rows.append(_row("impuesto_sociedades","12  Impuesto sociedades",months,{m:-impuesto_sociedades[m] for m in months},kind="section",section=False))
    rows.append(_row("resultado_ejercicio","13  Resultado del ejercicio",months,resultado_ejercicio,kind="subtotal",section=True))
    rows.append(_row("resultado_ejercicio_pct","%",months,_ratio_values(months,resultado_ejercicio,net_before),kind="percentage",precomputed=True))

    ytd=_ytd_months(months); total=lambda series:round(sum(series.get(m,0) for m in ytd),2)
    totals={"ventas_netas_descuentos":total(net_before),"ventas_netas":total(net_after),"ventas_brutas":total(gross_after),"descuentos":total(discount_gross),"iva_ventas":total(tax),"iva_gastos":total(expense_tax),"food_cost":total(food),"comisiones":total(commissions),"personal":total(personal),"otros_explotacion":total(other),"marketing":total(marketing),"otros_gg_produccion":total(sgg_total),"margen_bruto":total(margin_gross),"margen_contribucion":total(margin_contrib),"ebitda":total(ebitda),"ebit":total(ebit),"resultado_financiero":total(resultado_financiero),"resultado_antes_impuestos":total(resultado_antes_impuestos),"impuesto_sociedades":total(impuesto_sociedades),"resultado_ejercicio":total(resultado_ejercicio)}
    totals["margen_bruto_pct"]=round(totals["margen_bruto"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0
    totals["margen_contribucion_pct"]=round(totals["margen_contribucion"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0
    totals["ebitda_pct"]=round(totals["ebitda"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0
    totals["ebit_pct"]=round(totals["ebit"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0
    totals["resultado_antes_impuestos_pct"]=round(totals["resultado_antes_impuestos"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0
    totals["resultado_ejercicio_pct"]=round(totals["resultado_ejercicio"]/totals["ventas_netas_descuentos"],4) if totals["ventas_netas_descuentos"] else 0.0

    # Issues: solo informativo, NUNCA inventar
    issues=[{"code":"channel_mapping","level":"info","message":"Restaurant=card+cash y Take away=shop; son tipos de pago, no el canal comercial original."},{"code":"food_cost_allocated","level":"info","message":"Food cost por canal está prorrateado según ventas netas por tipo de pago."}]
    if not has_nominas and not has_ss and not has_otros and personal:
        issues.append({"code":"personal_subsin_datos","level":"info","message":"El total de Personal es real pero las sub-filas (Nóminas/Seguros sociales/Otros) no se muestran porque no hay clasificación por proveedor en facturas."})
    if not has_glovo and not has_uber and not has_lastshop and not has_justeat and commissions:
        issues.append({"code":"comisiones_subsin_datos","level":"info","message":"El total de Comisiones es real pero las sub-filas por marketplace no se muestran porque no hay clasificación por proveedor en facturas."})
    if not any(v!=0 for v in amortizacion_total.values()):
        issues.append({"code":"amortizacion_sin_datos","level":"info","message":"Amortización sin datos: requiere carga de activos fijos para mostrar valores reales."})
    if not any(v!=0 for v in resultado_financiero.values()):
        issues.append({"code":"financiero_sin_datos","level":"info","message":"Resultado financiero sin datos: requiere carga de extractos bancarios para mostrar valores reales."})
    if not any(v!=0 for v in impuesto_sociedades.values()):
        issues.append({"code":"impuesto_sin_datos","level":"info","message":"Impuesto sociedades sin datos: requiere carga de activos/pasivos fiscales para mostrar el cálculo real."})
    return {"period":{"from":start.isoformat(),"to":end.isoformat()},"columns":months+["YTD"],"rows":rows,"totals":totals,"issues":issues,"rows_used":len(expense_rows)+len(sales_rows or [])}