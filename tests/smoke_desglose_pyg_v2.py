"""
smoke_desglose_pyg_v2.py — Smoke test del motor v2 con datos sintéticos
representativos del cliente Liados.

Verifica end-to-end que el esquema JSON v2.0 (Guía §30) se construye
correctamente con casos reales observados en el VPS.
"""
import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dashboard.desglose_pyg import build_pyg_v2_doc, build_pyg
from dashboard.desglose_pyg_rules import load_rules, classify_factura_v2


# Datos sintéticos que reflejan casos reales del VPS
SAMPLE = [
    # Aprovisionamientos
    {"vendor_name": "Makro", "category_raw": "Alimentación",
     "invoice_date": "2026-07-05", "total_amount": 850.50,
     "concept": "pechuga pollo fresca", "invoice_number": "F-001"},
    {"vendor_name": "Coca-Cola", "category_raw": "Bebida",
     "invoice_date": "2026-07-08", "total_amount": 320.00,
     "concept": "refrescos para venta", "invoice_number": "F-002"},
    {"vendor_name": "Envapro", "category_raw": "Packaging",
     "invoice_date": "2026-07-12", "total_amount": 145.30,
     "concept": "cajas takeaway", "invoice_number": "F-003"},
    # Comisiones
    {"vendor_name": "Glovo", "category_raw": "Comisiones",
     "invoice_date": "2026-07-15", "total_amount": 245.80,
     "concept": "comisión por pedido", "invoice_number": "G-101"},
    {"vendor_name": "Uber Eats", "category_raw": "Comisiones",
     "invoice_date": "2026-07-18", "total_amount": 178.20,
     "concept": "comisión marketplace", "invoice_number": "U-101"},
    # Personal
    {"vendor_name": "TGSS", "category_raw": "Seguridad Social",
     "invoice_date": "2026-07-30", "total_amount": 1200.00,
     "concept": "cuota SS julio", "invoice_number": "TGSS-2026-07"},
    {"vendor_name": "Nomina", "category_raw": "Nóminas",
     "invoice_date": "2026-07-30", "total_amount": 4500.00,
     "concept": "nómina julio Ana", "invoice_number": "N-2026-07"},
    # Servicios
    {"vendor_name": "Iberdrola", "category_raw": "Suministros",
     "invoice_date": "2026-07-05", "total_amount": 580.00,
     "concept": "factura electricidad", "invoice_number": "IB-2026-07"},
    {"vendor_name": "Hermanos Tonda", "category_raw": "Suministros",
     "invoice_date": "2026-07-01", "total_amount": 2200.00,
     "concept": "renta local julio", "invoice_number": "HT-2026-07"},
    {"vendor_name": "La Cochera Studio", "category_raw": "Servicios profesionales",
     "invoice_date": "2026-07-10", "total_amount": 320.00,
     "concept": "asesoría laboral julio", "invoice_number": "LC-2026-07"},
    # Marketing
    {"vendor_name": "Meta", "category_raw": "Marketing",
     "invoice_date": "2026-07-20", "total_amount": 450.00,
     "concept": "Meta Ads campaña julio", "invoice_number": "M-2026-07"},
    {"vendor_name": "Rotapel", "category_raw": "Packaging",
     "invoice_date": "2026-07-22", "total_amount": 89.50,
     "concept": "cartelería promocional", "invoice_number": "R-101"},
    # Casos especiales
    {"vendor_name": "Proveedor X", "category_raw": "Otro",
     "invoice_date": "2026-07-25", "total_amount": 3200.00,
     "concept": "horno industrial nuevo", "invoice_number": "PX-2026-07"},
    {"vendor_name": "Banco Y", "category_raw": "Gastos Bancarios",
     "invoice_date": "2026-07-31", "total_amount": 45.00,
     "concept": "intereses préstamo", "invoice_number": "BY-2026-07"},
    # Intercompany (NON_PYG)
    {"vendor_name": "VAMOS AL LIO S.L.", "category_raw": "Suministros",
     "invoice_date": "2026-07-15", "total_amount": 500.00,
     "concept": "movimiento grupo", "invoice_number": "VL-2026-07"},
]


def main():
    rules = load_rules()
    doc = build_pyg_v2_doc(
        SAMPLE, "2026-07-01", "2026-07-31",
        cuenta=None, rules=rules,
    )

    # ── Validaciones del esquema §30 ──
    assert doc["schema_version"] == "liados-improvement-v2.0"
    assert doc["mode"] == "IMPROVE_EXISTING_SYSTEM"
    assert doc["period"]["from"] == "2026-07-01"
    assert doc["period"]["to"] == "2026-07-31"
    assert "documents" in doc
    assert "totals" in doc
    assert "audit_summary" in doc
    assert "issues" in doc

    print("=" * 70)
    print(f"SMOKE V2: {len(SAMPLE)} facturas sintéticas → julio 2026")
    print("=" * 70)
    print()
    print(f"  Totals: {json.dumps(doc['totals'], indent=2)}")
    print(f"  Audit:  {json.dumps(doc['audit_summary'], indent=2)}")
    print()

    # Verificar que cada doc tiene los campos obligatorios §30
    required = {
        "schema_version", "mode", "document_id", "status",
        "supplier", "document", "amounts", "classifications",
        "confidence", "flags", "audit", "system_improvement",
    }
    for d in doc["documents"]:
        missing = required - set(d.keys())
        assert not missing, f"doc {d.get('document_id')} missing: {missing}"

    # Verificar que el motor build_pyg (legacy) sigue funcionando
    pyg = build_pyg(SAMPLE, "2026-07-01", "2026-07-31", rules=rules)
    assert pyg["totals"]["ingresos"] == 0  # no hay ventas en la muestra

    # ── Resumen de decisiones por factura ──
    print("─" * 70)
    print(f"  {'DOC':35s} {'STATUS':18s} FLAGS")
    print("─" * 70)
    for d in doc["documents"]:
        flags = ",".join(d["flags"][:3]) or "-"
        if len(d["flags"]) > 3:
            flags += f" (+{len(d['flags'])-3})"
        print(f"  {d['document_id'][:35]:35s} {d['status']:18s} {flags}")

    print()
    print("=" * 70)
    print("✓ SMOKE V2 OK — Esquema §30 completo,")
    print(f"  {doc['totals']['classified']} auto-clasificados, "
          f"{doc['totals']['manual_review']} a revisión, "
          f"{doc['totals']['non_pyg']} NON_PYG, "
          f"{doc['totals']['duplicates_blocked']} duplicados bloqueados")
    return 0


if __name__ == "__main__":
    sys.exit(main())