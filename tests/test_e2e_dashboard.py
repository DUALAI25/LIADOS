"""Test E2E del dashboard Liados con Playwright."""
import base64
import pytest
from playwright.sync_api import Page


BASE_URL = "https://127.0.0.1:9121"
USER = "jefe"
PASS = "jefe2026"
AUTH_HEADER = {
    "Authorization": "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()
}


@pytest.fixture
def auth_page(context, page: Page) -> Page:
    context.set_extra_http_headers(AUTH_HEADER)
    return page


@pytest.fixture
def clean_page(context, page: Page) -> Page:
    context.clear_cookies()
    return page


class TestDashboardE2E:

    def test_01_health_check_returns_200(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/api/health")
        assert response.status == 200
        assert response.json().get("status") == "ok"

    def test_02_dashboard_root_renders_with_auth(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/")
        assert response.status == 200
        # Usar page.content() en vez de response.content()
        html = auth_page.content()
        assert "factura" in html.lower() or "kpi" in html.lower() or "gasto" in html.lower()

    def test_03_root_without_auth_returns_401(self, clean_page: Page):
        response = clean_page.goto(f"{BASE_URL}/")
        assert response.status == 401

    def test_04_api_kpis_returns_kpi_data(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/api/kpis")
        assert response.status == 200
        data = response.json()
        for key in ["ventas_mes", "gastos_mes", "margen_mes"]:
            assert key in data

    def test_05_api_facturas_recientes_returns_list(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/api/facturas-recientes")
        assert response.status == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_06_api_gastos_returns_data(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/api/gastos")
        assert response.status == 200
        data = response.json()
        assert isinstance(data, (list, dict))
        if isinstance(data, list):
            assert len(data) > 0

    def test_07_api_search_responds_ok(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/api/search?q=Telef")
        assert response.status == 200

    def test_08_api_health_returns_ok(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/api/health")
        assert response.status == 200
        assert response.json().get("status") == "ok"

    def test_09_login_page_renders(self, clean_page: Page):
        response = clean_page.goto(f"{BASE_URL}/login")
        assert response.status == 200
        html = clean_page.content()
        assert "Liados" in html
        assert "input" in html.lower()

    def test_10_full_smoke_flow(self, auth_page: Page):
        r = auth_page.goto(f"{BASE_URL}/")
        assert r.status == 200
        r = auth_page.goto(f"{BASE_URL}/api/kpis")
        assert r.status == 200
        kpis = r.json()
        assert kpis.get("ventas_mes", 0) > 0 or kpis.get("gastos_mes", 0) > 0
        r = auth_page.goto(f"{BASE_URL}/api/gastos")
        assert r.status == 200
        r = auth_page.goto(f"{BASE_URL}/api/search?q=test")
        assert r.status == 200
        r = auth_page.goto(f"{BASE_URL}/")
        assert r.status == 200

    def test_11_excel_workbook_sheets_and_mobile_drawer(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/", wait_until="networkidle")
        assert response.status == 200
        auth_page.locator('.nav-item[data-view="desglose"]').click()
        auth_page.locator(".cr-workbook").wait_for(state="visible")
        filters_before = (
            auth_page.locator("#dg-from").input_value(),
            auth_page.locator("#dg-to").input_value(),
        )
        auth_page.locator(".cr-workbook").wait_for(state="visible")
        auth_page.locator("#cr-body tr:not(:has(.muted))").first.wait_for(state="visible")
        assert (
            auth_page.locator("#dg-from").input_value(),
            auth_page.locator("#dg-to").input_value(),
        ) == filters_before

        assert auth_page.locator(".cr-sheet-tab").all_text_contents() == [
            "Resumen Ejecutivo",
            "Evolución Mensual",
            "Análisis Proveedores",
            "Por Categorías",
            "Hoja5",
        ]
        assert auth_page.locator("#cr-body tr").count() >= 8
        ebitda_row = auth_page.locator('#cr-body tr[data-code="ebitda"]')
        assert ebitda_row.count() == 1
        assert ebitda_row.locator("td").first.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(18, 25, 38)"
        assert auth_page.locator("#cr-month-filter option").count() >= 9
        auth_page.locator("#cr-month-filter").select_option("2026-03")
        auth_page.locator('[data-cr-sheet="categorias"]').click()
        month_headers = auth_page.locator("#cr-head .cr-head-month th").all_text_contents()
        assert "mar-26" in month_headers and "YTD" in month_headers, month_headers
        auth_page.locator('[data-cr-sheet="evolucion"]').click()
        assert auth_page.locator("#cr-head .cr-head-month th").count() >= 10
        auth_page.locator("#cr-month-filter").select_option("")
        auth_page.locator('[data-cr-sheet="evolucion"]').click()
        assert auth_page.locator("#cr-head .cr-head-month th").count() >= 3
        auth_page.locator('[data-cr-sheet="proveedores"]').click()
        assert auth_page.locator("#cr-body tr").count() >= 1
        auth_page.locator('[data-cr-sheet="categorias"]').click()
        assert auth_page.locator("#cr-body tr").count() >= 6
        auth_page.locator('[data-cr-sheet="hoja5"]').click()
        assert auth_page.locator("#cr-body tr").count() == 32

        auth_page.set_viewport_size({"width": 390, "height": 844})
        auth_page.locator("#sidebarToggle").click()
        assert auth_page.locator("#sidebar").evaluate("el => el.classList.contains('open')")
        auth_page.locator('.nav-item[data-view="desglose"]').click()
        auth_page.wait_for_timeout(500)
        sidebar = auth_page.locator("#sidebar")
        assert not sidebar.evaluate("el => el.classList.contains('open')")
        assert sidebar.evaluate("el => el.getBoundingClientRect().right") <= 0

    def test_12_clean_dashboard_has_no_noise_surfaces(self, auth_page: Page):
        response = auth_page.goto(f"{BASE_URL}/", wait_until="networkidle")
        assert response.status == 200
        auth_page.locator(".finance-overview").wait_for(state="visible")
        assert auth_page.locator(".finance-metrics article").count() == 3
        assert auth_page.locator("#kpis").evaluate("el => getComputedStyle(el).display") == "none"
        assert auth_page.locator("#sidebar").evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(18, 25, 38)"
        assert auth_page.locator('.nav-item[data-view="alertas"]').count() == 0
        assert auth_page.locator('#last-invoice-card').count() == 0
        assert auth_page.locator('.home-secondary-noise:visible').count() == 0
