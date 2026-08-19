import base64, json, os, subprocess, sys, time, urllib.request

def main():
    env=os.environ.copy()
    for line in open("/root/liados/.env"):
        line=line.strip()
        if line and not line.startswith("#") and "=" in line:
            k,v=line.split("=",1); env[k]=v
    proc=subprocess.Popen([".venv/bin/python3","-m","uvicorn","dashboard.app:app","--host","127.0.0.1","--port","9130"],cwd="/root/liados",env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        time.sleep(5)
        auth=base64.b64encode(f"{env['DASHBOARD_USER']}:{env['DASHBOARD_PASSWORD']}".encode()).decode()
        req=urllib.request.Request("http://127.0.0.1:9130/api/gastos/cuenta-resultados?date_from=2026-01-01&date_to=2026-08-06",headers={"Authorization":f"Basic {auth}"})
        with urllib.request.urlopen(req,timeout=60) as r: data=json.loads(r.read())
        assert r.status==200
        assert data["columns"]==["2026-01","2026-02","2026-03","2026-04","2026-05","2026-06","2026-07","2026-08","YTD"]
        codes={x["code"] for x in data["rows"]}
        sales=next(x for x in data["rows"] if x["code"] == "ventas")
        channels={x["label"] for x in sales.get("children",[]) if x.get("kind") == "channel"}
        assert {"Uber", "Glovo", "Just Eat"}.issubset(channels), channels
        parent_net = {"Restaurant", "Take away", "Delivery"}
        net_sum = sum(float(x["values"].get("YTD") or 0) for x in sales["children"] if x.get("label") in parent_net)
        gross_sum = sum(float(x["values"].get("YTD") or 0) for x in sales["children"] if x.get("label") in {f"{label} C/IVA" for label in parent_net})
        assert abs(net_sum - float(data["totals"]["ventas_netas"])) < 0.02, (net_sum, data["totals"]["ventas_netas"])
        assert abs(gross_sum - float(data["totals"]["ventas_brutas"])) < 0.02, (gross_sum, data["totals"]["ventas_brutas"])
        for code in ("comisiones","ebit","amortizacion","resultado_financiero","resultado_antes_impuestos","impuesto_sociedades","resultado_ejercicio"): assert code in codes, code
        def provider_keys(row):
            keys=[]
            if row.get("provider_key"): keys.append(row["provider_key"])
            for child in row.get("children",[]): keys.extend(provider_keys(child))
            return keys
        for row in data["rows"]:
            keys=provider_keys(row)
            assert len(keys)==len(set(keys)), row["code"]
        print(f"HTTP {r.status}; columnas={len(data['columns'])}; filas={len(data['rows'])}; ventas={data['totals']['ventas_netas']}; EBITDA={data['totals']['ebitda']}; EBIT={data['totals']['ebit']}; Resultado_ejercicio={data['totals']['resultado_ejercicio']}; canales conciliados=OK; proveedores sin repetición=OK")
        return 0
    finally:
        proc.terminate(); proc.wait(timeout=10)
if __name__=="__main__": sys.exit(main())
