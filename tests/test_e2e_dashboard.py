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
