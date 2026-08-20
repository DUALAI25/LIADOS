"""
test_desglose_pyg_v2.py — Tests de la integración con la Guía v2.0.

Cubre:
  - Taxonomía oficial (11 categorías, sinónimos)
  - Clasificación v2 con esquema completo (Guía §30)
  - Hard flags (Guía §26)
  - Auditoría posterior (Guía §27)
  - Detección de CAPEX / financiero / multicategoría
  - Esquema JSON v2.0 con build_pyg_v2_doc
  - Casos de la sección 32 (Pruebas de comprensión)
"""
import sys
import os
import pytest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dashboard'))

from desglose_pyg import (
    build_pyg,
    build_pyg_v2_doc,
    audit_classification,
    cross_check_subcat,
    PygError,
)
from desglose_pyg_rules import (
    classify_factura,
    classify_factura_v2,
    DEFAULT_RULES,
    BUCKETS,
    detect_duplicate,
)
from taxonomy import (
    CATEGORIES,
    SYNONYMS,
    HARD_FLAGS,
    normalize_concept,
    is_valid_category,
    needs_multicategory_check,
    is_capex_suspect,
    is_financial_expense,
)

OFFICIAL_CATEGORIES = CATEGORIES


# ── Tests de la taxonomía oficial ──────────────────────────────

class TestTaxonomy:
    """Verifica que la taxonomía oficial respeta la guía §3 (11 categorías)."""

    def test_eleven_categorias_oficiales(self):
        assert len(CATEGORIES) == 11

    def test_categorias_esperadas(self):
        esperadas = {
            "Suministros", "Restauración y Hostelería", "Servicios Profesionales",
            "Alquiler", "Impuestos y Tasas", "Marketing y Publicidad",
            "Gastos Bancarios", "Software y SaaS", "Oficina", "Otros",
            "Seguros",
        }
        assert set(CATEGORIES) == esperadas

    def test_hard_flags_canonicos(self):
        """Los 13 hard flags del esquema §26."""
        esperados = {
            "UNKNOWN_DOCUMENT_TYPE", "POSSIBLE_DUPLICATE",
            "INSUFFICIENT_CONCEPT", "AMBIGUOUS_VENDOR",
            "TOTAL_MISMATCH", "MIXED_LINES_UNRESOLVED",
            "POTENTIAL_CAPEX", "FINANCIAL_EXPENSE",
            "UNKNOWN_TAX", "UNMATCHED_CREDIT_NOTE",
            "CROSS_PERIOD_MATERIAL", "UNKNOWN_CATEGORY_MAPPING",
            "TAX_EXTRACTION_UNCERTAIN",
        }
        assert set(HARD_FLAGS) == esperados

    def test_sinonimos_canonicos(self):
        """Sinónimos clave de la guía §24."""
        assert normalize_concept("luz") == "Electricidad"
        assert normalize_concept("fibra") == "Internet"
        assert normalize_concept("comida") == "Alimentación"
        assert normalize_concept("cajas takeaway") == "Packaging"
        assert normalize_concept("comision") == "Comisiones"
        assert normalize_concept("ads") == "Marketing y Publicidad"
        assert normalize_concept("renta local") == "Alquiler"

    def test_sinonimo_desconocido_devuelve_original(self):
        """Si no hay match, conserva el texto (no rompe el original)."""
        assert normalize_concept("xyz inventado") == "xyz inventado"

    def test_is_valid_category(self):
        assert is_valid_category("Marketing y Publicidad") is True
        assert is_valid_category("Restauración y Hostelería") is True
        assert is_valid_category("Inventada") is False
        assert is_valid_category(None) is False

    def test_multicategory_vendors(self):
        assert needs_multicategory_check("Glovo Spain") is True
        assert needs_multicategory_check("Uber Eats España") is True
        assert needs_multicategory_check("Rotapel SA") is True
        assert needs_multicategory_check("Envapro SL") is True
        assert needs_multicategory_check("Makro") is False
        assert needs_multicategory_check(None) is False

    def test_capex_detection(self):
        assert is_capex_suspect("horno industrial") is True
        assert is_capex_suspect("nevera industrial") is True
        assert is_capex_suspect("reforma local") is True
        assert is_capex_suspect("compra pechuga de pollo") is False

    def test_financial_detection(self):
        assert is_financial_expense("intereses préstamo") is True
        assert is_financial_expense("descubierto cuenta") is True
        assert is_financial_expense("coste financiero leasing") is True
        assert is_financial_expense("compra alimentos") is False


# ── Tests de clasificación v2 (esquema §30) ───────────────────

class TestClassifyFacturaV2:
    """Verifica que classify_factura_v2 devuelve el esquema completo."""

    def test_esquema_completo(self):
        cls = classify_factura_v2(
            category_raw="Alimentación",
            vendor_name="Makro",
            concept="pechuga de pollo",
        )
        # Campos obligatorios del esquema §30
        assert "expense_category" in cls
        assert "semantic_subcategory" in cls
        assert "pyg_block" in cls
        assert "pyg_category" in cls
        assert "pyg_subcategory" in cls
        assert "original_description" in cls
        assert "normalized_concept" in cls
        assert "reason" in cls
        assert "evidence" in cls
        assert "confidence" in cls
        assert "flags" in cls
        assert cls["bucket"] == "aprovisionamientos"

    def test_confianza_estructura(self):
        cls = classify_factura_v2("Luz", "Iberdrola")
        c = cls["confidence"]
        assert "extraction" in c
        assert "classification" in c
        assert "audit" in c
        assert 0.0 <= c["classification"] <= 1.0
        assert 0.0 <= c["audit"] <= 1.0

    def test_pyg_block_alimentacion(self):
        cls = classify_factura_v2("Alimentación", "Makro", "pollo")
        assert cls["pyg_block"] == "GASTOS"
        assert "Aprovisionamientos" in cls["pyg_category"]

    def test_personal_no_es_categoria_oficial(self):
        """Personal es un bloque PYG, NO una categoría operativa.
        El clasificador lo emite pero conserva la estructura."""
        cls = classify_factura_v2("Nóminas", "TGSS")
        assert cls["bucket"] == "personal"
        assert cls["pyg_category"] == "3) Personal"

    def test_glovo_visibilidad_revisa(self):
        """Glovo con concepto 'visibilidad' debe levantar MIXED_LINES_UNRESOLVED."""
        cls = classify_factura_v2("Otro", "Glovo", "visibilidad campañas")
        assert "MIXED_LINES_UNRESOLVED" in cls["flags"]

    def test_rotapel_publicidad_revisa(self):
        """Rotapel con cartelería no debe ir a packaging."""
        cls = classify_factura_v2("Otro", "Rotapel",
                                   "cartelería material promocional")
        assert "MIXED_LINES_UNRESOLVED" in cls["flags"]

    def test_capex_flag(self):
        cls = classify_factura_v2("Otro", "Proveedor X",
                                   "horno industrial nuevo")
        assert "POTENTIAL_CAPEX" in cls["flags"]

    def test_financial_flag(self):
        cls = classify_factura_v2("Gastos Bancarios", "Banco",
                                   "intereses préstamo")
        assert "FINANCIAL_EXPENSE" in cls["flags"]


# ── Tests de la sección 32 (Pruebas de comprensión) ──────────

class TestComprensionGuia:
    """Casos literales de la sección §32."""

    def test_pollo_fresco(self):
        cls = classify_factura_v2("Alimentación", "Makro", "pollo fresco")
        assert cls["expense_category"] in ("Restauración y Hostelería", "Suministros")
        assert cls["pyg_category"] == "1) Aprovisionamientos"

    def test_refrescos_para_venta(self):
        cls = classify_factura_v2("Bebida", "Coca-Cola", "refresco venta")
        assert cls["bucket"] == "aprovisionamientos"
        assert cls["semantic_subcategory"] == "Bebida"

    def test_cajas_takeaway(self):
        cls = classify_factura_v2("Packaging", "Envapro", "cajas takeaway")
        assert cls["bucket"] == "aprovisionamientos"
        assert cls["semantic_subcategory"] == "Packaging"

    def test_factura_electrica(self):
        cls = classify_factura_v2("Suministros", "Iberdrola",
                                   "factura eléctrica")
        assert cls["bucket"] == "servicios"
        assert cls["semantic_subcategory"] == "Luz"

    def test_internet(self):
        cls = classify_factura_v2("Suministros", "Movistar", "internet")
        assert cls["bucket"] == "servicios"
        assert cls["semantic_subcategory"] == "Internet"

    def test_asesoria_laboral(self):
        cls = classify_factura_v2("Servicios profesionales", "La Cochera",
                                   "asesoría laboral")
        assert cls["bucket"] == "servicios"
        assert cls["semantic_subcategory"] == "Asesoría"

    def test_renta_local(self):
        cls = classify_factura_v2("Alquiler", "Hermanos Tonda",
                                   "renta local")
        assert cls["bucket"] == "servicios"
        assert cls["semantic_subcategory"] == "Alquiler"
        assert cls["expense_category"] == "Alquiler"

    def test_meta_ads(self):
        cls = classify_factura_v2("Marketing", "Meta", "Meta Ads")
        assert cls["pyg_category"] == "6) Otros gastos de explotación"
        assert cls["expense_category"] == "Marketing y Publicidad"

    def test_glovo_comision(self):
        cls = classify_factura_v2("Comisiones", "Glovo",
                                   "comisión pedido")
        assert cls["bucket"] == "comisiones"
        assert cls["semantic_subcategory"] == "Glovo"

    def test_rotapel_bolsas(self):
        cls = classify_factura_v2("Packaging", "Rotapel", "bolsas")
        assert cls["bucket"] == "aprovisionamientos"
        assert cls["semantic_subcategory"] == "Packaging"

    def test_suscripcion_tp(self):
        cls = classify_factura_v2("Software", "Proveedor", "suscripción TPV")
        # "Suscripción TPV" sin categoría explícita → servicios por defecto
        assert cls["bucket"] in ("servicios", "otros_gastos")

    def test_papel_impresora(self):
        cls = classify_factura_v2("Oficina", "Amazon", "papel impresora")
        # Oficina → otros_gastos
        assert cls["bucket"] == "otros_gastos"

    def test_seguro_responsabilidad(self):
        cls = classify_factura_v2("Seguros", "Aseguradora X",
                                   "seguro responsabilidad civil")
        assert cls["expense_category"] == "Seguros"

    def test_intereses_fuera_ebitda(self):
        cls = classify_factura_v2("Gastos Bancarios", "Banco Y",
                                   "intereses préstamo")
        assert "FINANCIAL_EXPENSE" in cls["flags"]

    def test_sin_concepto_a_revision(self):
        cls = classify_factura_v2("Otro", "Desconocido", None)
        # Sin concepto, baja confianza o flag
        assert (
            "INSUFFICIENT_CONCEPT" in cls["flags"]
            or cls["confidence"]["classification"] < 0.95
        )


# ── Tests de duplicados (Guía §16) ────────────────────────────

class TestDuplicates:
    def test_primera_factura_no_es_duplicado(self):
        seen = set()
        d = detect_duplicate(
            invoice_id=None, nif_cif="B123", invoice_number="F-001",
            serie=None, issue_date="2026-01-01",
            base=100, vat=21, total=121, seen=seen,
        )
        assert d["is_duplicate"] is False

    def test_segunda_factura_mismo_numero_es_duplicado(self):
        seen = set()
        detect_duplicate(
            invoice_id=None, nif_cif="B123", invoice_number="F-001",
            serie=None, issue_date="2026-01-01",
            base=100, vat=21, total=121, seen=seen,
        )
        d2 = detect_duplicate(
            invoice_id=None, nif_cif="B123", invoice_number="F-001",
            serie=None, issue_date="2026-01-02",
            base=200, vat=42, total=242, seen=seen,
        )
        assert d2["is_duplicate"] is True

    def test_numero_distinto_no_es_duplicado(self):
        seen = set()
        detect_duplicate(
            invoice_id=None, nif_cif="B123", invoice_number="F-001",
            serie=None, issue_date="2026-01-01",
            base=100, vat=21, total=121, seen=seen,
        )
        d2 = detect_duplicate(
            invoice_id=None, nif_cif="B123", invoice_number="F-002",
            serie=None, issue_date="2026-01-02",
            base=200, vat=42, total=242, seen=seen,
        )
        assert d2["is_duplicate"] is False


# ── Tests de la auditoría posterior (Guía §27) ────────────────

class TestAuditClassification:
    """Verifica los 13 chequeos de auditoría."""

    def test_total_mismatch(self):
        cls = classify_factura_v2("Alimentación", "Makro", "pollo")
        row = {
            "base_amount": 100.0, "vat_amount": 21.0,
            "invoice_number": "F1",
        }
        a = audit_classification(cls, row, "Makro", "Alimentación",
                                  "pollo", 200.0)
        # total=200, base+iva=121 → diff > 0.05
        assert "TOTAL_MISMATCH" in a["flags"]

    def test_tax_extraction_uncertain(self):
        cls = classify_factura_v2("Alimentación", "Makro", "pollo")
        row = {}  # sin base_amount ni vat
        a = audit_classification(cls, row, "Makro", "Alimentación",
                                  "pollo", 121.0)
        assert "TAX_EXTRACTION_UNCERTAIN" in a["flags"]

    def test_unmatched_credit_note(self):
        cls = classify_factura_v2("Abonos", "Proveedor", "abono")
        row = {"invoice_number": "AB-001"}  # sin original_invoice_id
        a = audit_classification(cls, row, "Proveedor", "Abonos",
                                  "abono", -50.0)
        assert "UNMATCHED_CREDIT_NOTE" in a["flags"]

    def test_cross_period_material(self):
        cls = classify_factura_v2("Seguros", "Aseguradora",
                                   "seguro anual")
        row = {"cross_period": True, "invoice_number": "S-001"}
        a = audit_classification(cls, row, "Aseguradora", "Seguros",
                                  "seguro anual", 1200.0)
        assert "CROSS_PERIOD_MATERIAL" in a["flags"]

    def test_audit_confidence_degraded(self):
        cls = classify_factura_v2("Otro", "Desconocido", None)
        row = {}
        a = audit_classification(cls, row, "Desconocido", "Otro",
                                  None, 100.0)
        # Con múltiples flags la confianza baja de 0.95
        assert a["confidence"]["audit"] < 0.95


# ── Tests de build_pyg_v2_doc (esquema completo §30) ──────────

class TestBuildPygV2Doc:
    """Verifica el esquema JSON v2.0 end-to-end."""

    def test_esquema_root(self):
        rows = [
            {"vendor_name": "Makro", "category_raw": "Alimentación",
             "invoice_date": "2026-01-10", "total_amount": 100,
             "concept": "pollo fresco"},
            {"vendor_name": "Iberdrola", "category_raw": "Luz",
             "invoice_date": "2026-01-15", "total_amount": 60,
             "concept": "factura luz"},
        ]
        doc = build_pyg_v2_doc(rows, "2026-01-01", "2026-01-31")
        assert doc["schema_version"] == "liados-improvement-v2.0"
        assert doc["mode"] == "IMPROVE_EXISTING_SYSTEM"
        assert doc["period"]["from"] == "2026-01-01"
        assert len(doc["documents"]) == 2
        assert "totals" in doc
        assert "audit_summary" in doc
        assert "issues" in doc

    def test_status_classified(self):
        rows = [
            {"vendor_name": "Makro", "category_raw": "Alimentación",
             "invoice_date": "2026-01-10", "total_amount": 100,
             "concept": "pollo"},
        ]
        doc = build_pyg_v2_doc(rows, "2026-01-01", "2026-01-31")
        d = doc["documents"][0]
        # Caso claro: Makro + Alimentación + "pollo" → alta confianza
        assert d["status"] == "CLASSIFIED"

    def test_status_manual_review(self):
        """Caso con AMBIGUOUS_VENDOR → MANUAL_REVIEW."""
        rows = [
            {"vendor_name": "Glovo", "category_raw": "Otro",
             "invoice_date": "2026-01-10", "total_amount": 100},
            # Glovo sin concepto → AMBIGUOUS_VENDOR
        ]
        doc = build_pyg_v2_doc(rows, "2026-01-01", "2026-01-31")
        d = doc["documents"][0]
        assert d["status"] == "MANUAL_REVIEW"
        assert "AMBIGUOUS_VENDOR" in d["flags"]

    def test_status_non_pyg_intercompany(self):
        rows = [
            {"vendor_name": "VAMOS AL LIO S.L.", "category_raw": "Suministros",
             "invoice_date": "2026-01-10", "total_amount": 100},
        ]
        doc = build_pyg_v2_doc(rows, "2026-01-01", "2026-01-31")
        d = doc["documents"][0]
        assert d["status"] == "NON_PYG"

    def test_status_duplicate_blocked(self):
        rows = [
            {"vendor_name": "Proveedor A", "category_raw": "Luz",
             "invoice_date": "2026-01-10", "total_amount": 100,
             "invoice_number": "F-001", "vendor_tax_id": "B123"},
            {"vendor_name": "Proveedor A", "category_raw": "Luz",
             "invoice_date": "2026-01-15", "total_amount": 100,
             "invoice_number": "F-001", "vendor_tax_id": "B123"},
        ]
        doc = build_pyg_v2_doc(rows, "2026-01-01", "2026-01-31")
        statuses = [d["status"] for d in doc["documents"]]
        assert "DUPLICATE_BLOCKED" in statuses

    def test_totals_y_audit_summary(self):
        rows = [
            {"vendor_name": "Makro", "category_raw": "Alimentación",
             "invoice_date": "2026-01-10", "total_amount": 100,
             "concept": "pollo"},
            {"vendor_name": "Glovo", "category_raw": "Otro",
             "invoice_date": "2026-01-15", "total_amount": 50},
        ]
        doc = build_pyg_v2_doc(rows, "2026-01-01", "2026-01-31")
        t = doc["totals"]
        assert t["documents_total"] == 2
        assert t["classified"] >= 1
        assert t["manual_review"] >= 1

    def test_system_improvement_en_documento(self):
        """Detección de CAPEX debe levantar improvement_proposal."""
        rows = [
            {"vendor_name": "Proveedor X", "category_raw": "Suministros",
             "invoice_date": "2026-01-10", "total_amount": 5000,
             "concept": "horno industrial nuevo"},
        ]
        doc = build_pyg_v2_doc(rows, "2026-01-01", "2026-01-31")
        d = doc["documents"][0]
        si = d["system_improvement"]
        assert si["issue_detected"] is True
        assert si["requires_human_approval"] is True
        assert "POTENTIAL_CAPEX" in d["flags"]

    def test_documento_tiene_campos_guia_30(self):
        rows = [
            {"vendor_name": "Makro", "category_raw": "Alimentación",
             "invoice_date": "2026-01-10", "total_amount": 100,
             "concept": "pollo", "invoice_number": "F-001",
             "vendor_tax_id": "B123"},
        ]
        doc = build_pyg_v2_doc(rows, "2026-01-01", "2026-01-31")
        d = doc["documents"][0]
        # Campos obligatorios del esquema §30
        assert "schema_version" in d
        assert "mode" in d
        assert "document_id" in d
        assert "status" in d
        assert "supplier" in d
        assert "document" in d
        assert "amounts" in d
        assert "classifications" in d
        assert "confidence" in d
        assert "flags" in d
        assert "audit" in d
        assert "system_improvement" in d
        # classifications[0] debe tener todos los campos §30
        c = d["classifications"][0]
        for k in ("line_id", "original_description", "normalized_concept",
                  "expense_category", "semantic_subcategory", "pyg_block",
                  "pyg_category", "pyg_subcategory", "net_amount",
                  "reason", "evidence"):
            assert k in c, f"falta {k} en classifications[0]"


# ── Tests de integración con build_pyg (compatibilidad) ───────

class TestCompatibilidad:
    """Los tests previos del motor build_pyg siguen pasando."""

    def test_build_pyg_basico(self):
        rows = [
            {"vendor_name": "Cliente", "category_raw": "Ventas",
             "source_account": "principal", "invoice_date": "2026-01-05",
             "total_amount": 100},
            {"vendor_name": "Makro", "category_raw": "Alimentación",
             "source_account": "principal", "invoice_date": "2026-01-08",
             "total_amount": 40},
        ]
        out = build_pyg(rows, "2026-01-01", "2026-01-31",
                         cuenta="principal")
        assert out["totals"]["ventas_brutas"] == 100.0
        assert out["buckets"]["aprovisionamientos"] == 40.0
        assert out["totals"]["margen_bruto"] == 60.0

    def test_periodo_invalido_lanza_excepcion(self):
        with pytest.raises(PygError, match="Fechas inválidas"):
            build_pyg_v2_doc([], "2026-13-99", "2026-01-31")


# ── Tests de escenarios reales del cliente (casos frontera) ───

class TestCasosReales:
    """Casos observados en el VPS con 549 facturas reales."""

    def test_makro_alimentos(self):
        """Makro es siempre aprovisionamientos."""
        cls = classify_factura_v2("Suministros", "Makro", "pechuga pollo")
        assert cls["bucket"] == "aprovisionamientos"
        assert cls["semantic_subcategory"] == "Alimentación"

    def test_iberdrola_luz(self):
        cls = classify_factura_v2("Suministros", "Iberdrola",
                                   "facturación electricidad")
        assert cls["bucket"] == "servicios"
        assert cls["semantic_subcategory"] == "Luz"

    def test_hermanos_tonda_alquiler(self):
        cls = classify_factura_v2("Suministros", "Hermanos Tonda",
                                   "renta local")
        assert cls["semantic_subcategory"] == "Alquiler"
        assert cls["expense_category"] == "Alquiler"

    def test_envases_para_profesionales(self):
        cls = classify_factura_v2("Suministros",
                                   "Envases para Profesionales",
                                   "envases cocina")
        # El motor lo pone en aprovisionamientos (regex matchea)
        assert cls["bucket"] in ("aprovisionamientos",
                                  "otros_gastos_produccion")

    def test_glovo_comision_vs_visibilidad(self):
        """Misma vendor, distinto concepto → distinto bucket/flag."""
        c_comision = classify_factura_v2("Otro", "Glovo",
                                          "comisión por pedido")
        c_visib = classify_factura_v2("Otro", "Glovo", "visibilidad")
        assert c_comision["bucket"] == "comisiones"
        # En visibilidad la auditoría lo marca como MIXED_LINES
        assert "MIXED_LINES_UNRESOLVED" in c_visib["flags"]


# ── Test global: el sistema respeta las 11 categorías ────────

class TestIntegridadSistema:
    """Ninguna categoría nueva puede colarse sin querer."""

    def test_no_categorias_inventadas_en_v2(self):
        """Las categorías que devuelve classify_factura_v2 están
        en las 11 oficiales o en buckets especiales."""
        buckets_especiales = {"personal", "comisiones"}
        muestras = [
            ("Suministros", "Makro", "pollo"),
            ("Marketing", "Meta", "ads"),
            ("Oficina", "Amazon", "papel"),
            ("Seguros", "Aseguradora", "RC"),
            ("Software", "Proveedor", "TPV"),
            ("Suministros", "Iberdrola", "luz"),
            ("Alquiler", "Propietario", "renta"),
            ("Servicios profesionales", "Asesor", "asesoría"),
        ]
        for cat, ven, con in muestras:
            cls = classify_factura_v2(cat, ven, con)
            oficial = cls["expense_category"]
            assert (
                oficial in OFFICIAL_CATEGORIES
                or cls["bucket"] in buckets_especiales
                or oficial == "Otros"
            ), f"Categoría inventada: {oficial}"