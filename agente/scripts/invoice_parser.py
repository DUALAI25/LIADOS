import os
import json
import base64
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

PROMPT_PARSE = """Eres un experto en extracción de datos de facturas.
Analiza esta factura y devuelve SOLO un JSON con esta estructura exacta, sin texto adicional:

{
    "invoice_number": "string o null",
    "invoice_date": "YYYY-MM-DD o null",
    "due_date": "YYYY-MM-DD o null",
    "vendor_name": "string o null",
    "vendor_tax_id": "string o null",
    "description": "string o null",
    "base_amount": "número o null",
    "tax_amount": "número o null",
    "total_amount": "número o null",
    "currency": "EUR por defecto",
    "category": "oficina|software|viajes|marketing|servicios|suministros|seguros|alquiler|teleco|bancario|impuestos|hosteleria|otros",
    "confidence": "0.0 a 1.0"
}"""


def parse_invoice(file_path_or_content, mime_type, filename=""):
    """
    Parsea una factura desde ruta de archivo o contenido binario
    
    Args:
        file_path_or_content: Ruta al archivo (str/Path) o contenido binario (bytes)
        mime_type: Tipo MIME del archivo
        filename: Nombre del archivo (para logging)
    """
    client = OpenAI(
        api_key=os.getenv('OPENCODE_API_KEY'),
        base_url=os.getenv('OPENCODE_BASE_URL', 'https://opencode.ai/zen/go/v1'),
    )

    # Si es una ruta, leer el contenido
    if isinstance(file_path_or_content, (str, os.PathLike)):
        with open(file_path_or_content, 'rb') as f:
            file_content = f.read()
    else:
        file_content = file_path_or_content

    if mime_type == 'application/pdf':
        text = _extract_pdf_text(file_content)
        if text and len(text.strip()) > 50:
            return _parse_with_text(client, text)
        else:
            return _parse_with_vision(client, file_content, mime_type)
    elif mime_type in ('image/jpeg', 'image/png'):
        return _parse_with_vision(client, file_content, mime_type)
    else:
        text = _extract_pdf_text(file_content)
        if text:
            return _parse_with_text(client, text)
        return _parse_with_vision(client, file_content, mime_type)


def _extract_pdf_text(pdf_content):
    # Primer intento: PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(stream=pdf_content, filetype='pdf')
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        if text.strip():
            return text
    except Exception as e:
        logger.warning(f"Error con fitz: {e}")

    # Segundo intento: pdfplumber
    try:
        import pdfplumber
        import io
        text = ""
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text
        if text.strip():
            logger.info("Extracción con pdfplumber exitosa")
            return text
    except Exception as e:
        logger.warning(f"Error con pdfplumber: {e}")

    return None


def _parse_with_text(client, text):
    try:
        resp = client.chat.completions.create(
            model=os.getenv('OPENCODE_MODEL', 'deepseek-v4-flash'),
            messages=[
                {'role': 'system', 'content': 'Eres un extractor de datos de facturas. Devuelve JSON válido.'},
                {'role': 'user', 'content': f'{PROMPT_PARSE}\n\nTexto de la factura:\n{text[:15000]}'}
            ],
            temperature=0.05,
            response_format={'type': 'json_object'}
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error(f"Text parse error: {e}")
        return None


def _parse_with_vision(client, content, mime_type):
    try:
        b64 = base64.b64encode(content).decode()
        resp = client.chat.completions.create(
            model=os.getenv('OPENCODE_MODEL', 'deepseek-v4-flash'),
            messages=[
                {'role': 'system', 'content': 'Analiza esta imagen de factura y extrae los datos en JSON.'},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': PROMPT_PARSE},
                    {'type': 'image_url', 'image_url': {
                        'url': f'data:{mime_type};base64,{b64}'
                    }}
                ]}
            ],
            temperature=0.05,
            response_format={'type': 'json_object'}
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error(f"Vision parse error: {e}")
        return None
