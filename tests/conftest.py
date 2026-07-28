"""Conftest para tests Playwright del dashboard Liados.

Fuerza ignore_https_errors=True en TODOS los contextos para evitar
el error ERR_CERT_AUTHORITY_INVALID con el cert self-signed.
"""
import pytest


@pytest.fixture(autouse=True)
def _ignore_https_for_dashboard(request):
    """Override pytest-playwright browser_context_args para añadir ignore_https_errors.

    pytest-playwright mira el marker 'ignore_https_errors' o el fixture browser_context_args.
    El truco: usar playwright_launch_args + context.
    """
    pass


@pytest.fixture
def browser_context_args(browser_context_args):
    """Añadir ignore_https_errors al contexto por defecto."""
    return {
        **browser_context_args,
        "ignore_https_errors": True,
    }
