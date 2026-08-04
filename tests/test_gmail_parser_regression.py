import sys
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1] / "agente" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import gmail_collector
import invoice_parser
class FakeOpenAI:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url

def test_parser_keeps_minimax_key_endpoint_and_model_together(monkeypatch):
    monkeypatch.setattr(invoice_parser, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-Text-01")
    monkeypatch.setenv("OPENCODE_API_KEY", "opencode-test")
    monkeypatch.setenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
    monkeypatch.setenv("OPENCODE_MODEL", "deepseek-v4-flash")
    client, model, provider = invoice_parser._get_parser_config()
    assert provider == "minimax"
    assert client.api_key == "minimax-test"
    assert client.base_url == "https://api.minimax.io/v1"
    assert model == "MiniMax-Text-01"

def test_parser_fallback_keeps_opencode_key_endpoint_and_model_together(monkeypatch):
    monkeypatch.setattr(invoice_parser, "OpenAI", FakeOpenAI)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("OPENCODE_API_KEY", "opencode-test")
    monkeypatch.setenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
    monkeypatch.setenv("OPENCODE_MODEL", "deepseek-v4-flash")
    client, model, provider = invoice_parser._get_parser_config()
    assert provider == "opencode"
    assert client.api_key == "opencode-test"
    assert client.base_url == "https://opencode.ai/zen/go/v1"
    assert model == "deepseek-v4-flash"

def test_failed_sync_records_error_without_advancing_cursor(monkeypatch):
    calls = []
    monkeypatch.setattr(gmail_collector, "record_sync_error", lambda source: calls.append(("error", source)))
    monkeypatch.setattr(gmail_collector, "update_last_sync", lambda source, status="ok": calls.append(("success", source, status)))
    result = gmail_collector._finalize_sync("gmail:principal", 1)
    assert result == "error"
    assert calls == [("error", "gmail:principal")]

def test_successful_sync_advances_cursor(monkeypatch):
    calls = []
    monkeypatch.setattr(gmail_collector, "record_sync_error", lambda source: calls.append(("error", source)))
    monkeypatch.setattr(gmail_collector, "update_last_sync", lambda source, status="ok": calls.append(("success", source, status)))
    result = gmail_collector._finalize_sync("gmail:principal", 0)
    assert result == "ok"
    assert calls == [("success", "gmail:principal", "ok")]



def test_vision_uses_selected_client_even_with_openai_key_present(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("OPENAI_API_KEY", "residual-openai-key")
    captured = {}

    def fake_call(client, **kwargs):
        captured["client"] = client
        captured["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"invoice_number":"V-1"}'))]
        )

    monkeypatch.setattr(invoice_parser, "_call_with_retry", fake_call)
    client = FakeOpenAI("minimax-test", "https://api.minimax.io/v1")
    result = invoice_parser._parse_with_vision(
        client, b"image-bytes", "application/pdf", model="MiniMax-Text-01"
    )

    assert result["invoice_number"] == "V-1"
    assert captured == {"client": client, "model": "MiniMax-Text-01"}


def test_process_account_early_error_keeps_three_value_contract(monkeypatch):
    monkeypatch.setattr(gmail_collector, "get_service", lambda account: (None, "error"))

    result = gmail_collector.process_account(
        "principal", search_query="has:attachment after:2026/07/30"
    )

    assert result == (0, 1, None)


def test_scanned_pdf_vision_payload_uses_png(monkeypatch):
    import fitz
    from agente.scripts.invoice_parser import _prepare_vision_content

    doc = fitz.open()
    doc.new_page(width=100, height=100)
    pdf_bytes = doc.tobytes()
    doc.close()

    rendered, mime = _prepare_vision_content(pdf_bytes, 'application/pdf')

    assert mime == 'image/png'
    assert rendered.startswith(b'\x89PNG')
