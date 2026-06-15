import os
import json
import time
import base64
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


def _sanitize_error(e):
    """Limpia mensajes de error para evitar filtrar API keys o tokens."""
    msg = str(e)
    for needle in ('Bearer ', 'Authorization', 'sk-', 'github_pat_', 'apiKey'):
        idx = msg.find(needle)
        if idx >= 0:
            msg = msg[:idx + len(needle)] + '[REDACTED]'
    return msg


# Categorías válidas (alineadas con el schema de DB)
VALID_CATEGORIES = {
    'software', 'oficina', 'viajes', 'marketing', 'servicios',
    'suministros', 'seguros', 'alquiler', 'teleco', 'bancario',
    'impuestos', 'hosteleria', 'otros'
}

PROMPT_PARSE = """Eres un experto en extracción de datos de facturas.
Analiza esta factura y devuelve SOLO un JSON con esta estructura exacta, sin texto adicional:

{
    "invoice_number": "string o null",
    "invoice_date": "YYYY-MM-DD o null",
    "due_date": "YYYY-MM-DD o null",
    "vendor_name": "string o null",
    "vendor_tax_id": "string o null (CIF/NIF/RFC del proveedor)",
    "description": "string o null (concepto breve)",
    "base_amount": "número o null (importe sin IVA)",
    "tax_amount": "número o null (IVA)",
    "total_amount": "número o null (total con IVA)",
    "currency": "EUR por defecto",
    "category": "una de: oficina|software|viajes|marketing|servicios|suministros|seguros|alquiler|teleco|bancario|impuestos|hosteleria|otros",
    "confidence": "0.0 a 1.0 (tu confianza en la extracción)"
}

Reglas:
- Si un campo no es legible, devuelve null
- currency: EUR por defecto en España, USD en US, etc.
- confidence: 0.0 si no estás seguro, 1.0 si todo es claro
- description: 1 línea corta, sin el número de factura
- vendor_name: nombre comercial del proveedor, no el legal si difiere
"""


def _normalize_category(cat):
    """Normaliza la categoría al set válido. Si no está, devuelve 'otros'."""
    if not cat:
        return 'otros'
    cat_lower = str(cat).lower().strip()
    if cat_lower in VALID_CATEGORIES:
        return cat_lower
    # Mapeo de sinónimos comunes
    synonyms = {
        'restaurante': 'hosteleria',
        'comida': 'hosteleria',
        'alimentacion': 'hosteleria',
        'transporte': 'viajes',
        'taxi': 'viajes',
        'gasolina': 'viajes',
        'combustible': 'viajes',
        'publicidad': 'marketing',
        'luz': 'suministros',
        'agua': 'suministros',
        'electricidad': 'suministros',
        'internet': 'teleco',
        'telefono': 'teleco',
        'banco': 'bancario',
        'comision': 'bancario',
    }
    return synonyms.get(cat_lower, 'otros')


def _coerce_number(val):
    """Convierte un valor a float, o None si no es posible."""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _coerce_date(val):
    """Valida que una fecha esté en formato YYYY-MM-DD y sea semánticamente válida.
    Si no, None.
    """
    if not val or not isinstance(val, str):
        return None
    import re
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', val.strip())
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # Validación semántica básica
    if not (1900 <= year <= 2100):
        return None
    if not (1 <= month <= 12):
        return None
    if not (1 <= day <= 31):
        return None
    return val.strip()


def _normalize_parsed_data(parsed):
    """Limpia y normaliza el JSON devuelto por la IA.

    Si el input es None, vacío o inválido, devuelve un dict con defaults.
    """
    if not parsed or not isinstance(parsed, dict):
        return {
            'invoice_number': None,
            'invoice_date': None,
            'due_date': None,
            'vendor_name': None,
            'vendor_tax_id': None,
            'description': None,
            'base_amount': None,
            'tax_amount': None,
            'total_amount': None,
            'currency': 'EUR',
            'category': 'otros',
            'confidence_score': 0.5,
        }

    return {
        'invoice_number': parsed.get('invoice_number') or None,
        'invoice_date': _coerce_date(parsed.get('invoice_date')),
        'due_date': _coerce_date(parsed.get('due_date')),
        'vendor_name': (parsed.get('vendor_name') or '').strip() or None,
        'vendor_tax_id': (parsed.get('vendor_tax_id') or '').strip() or None,
        'description': (parsed.get('description') or '').strip() or None,
        'base_amount': _coerce_number(parsed.get('base_amount')),
        'tax_amount': _coerce_number(parsed.get('tax_amount')),
        'total_amount': _coerce_number(parsed.get('total_amount')),
        'currency': (parsed.get('currency') or 'EUR').upper()[:3],
        'category': _normalize_category(parsed.get('category')),
        'confidence_score': _coerce_number(parsed.get('confidence')) or 0.5,
    }


def parse_invoice(file_path_or_content, mime_type, filename=""):
    """
    Parsea una factura desde ruta de archivo o contenido binario.

    Args:
        file_path_or_content: Ruta al archivo (str/Path) o contenido binario (bytes)
        mime_type: Tipo MIME del archivo
        filename: Nombre del archivo (para logging)

    Returns:
        dict normalizado con los datos de la factura, o None si falla
    """
    if not os.getenv('OPENCODE_API_KEY'):
        logger.error("OPENCODE_API_KEY no configurado en .env")
        return None

    client = OpenAI(
        api_key=os.getenv('OPENCODE_API_KEY'),
        base_url=os.getenv('OPENCODE_BASE_URL', 'https://opencode.ai/zen/go/v1'),
    )

    # Si es una ruta, leer el contenido
    if isinstance(file_path_or_content, (str, os.PathLike)):
        try:
            with open(file_path_or_content, 'rb') as f:
                file_content = f.read()
        except OSError as e:
            logger.error(f"No se pudo leer {file_path_or_content}: {e}")
            return None
    else:
        file_content = file_path_or_content

    if not file_content:
        logger.warning(f"Archivo vacío: {filename}")
        return None

    # Decidir estrategia: texto o visión
    parsed = None
    if mime_type == 'application/pdf':
        text = _extract_pdf_text(file_content)
        if text and len(text.strip()) > 50:
            logger.debug(f"[{filename}] PDF con texto extraíble, usando parseo texto")
            parsed = _parse_with_text(client, text)
        else:
            logger.debug(f"[{filename}] PDF sin texto, usando visión")
            parsed = _parse_with_vision(client, file_content, mime_type)
    elif mime_type in ('image/jpeg', 'image/png'):
        logger.debug(f"[{filename}] Imagen, usando visión")
        parsed = _parse_with_vision(client, file_content, mime_type)
    else:
        # Tipo desconocido, intentar texto
        text = _extract_pdf_text(file_content)
        if text:
            parsed = _parse_with_text(client, text)
        else:
            parsed = _parse_with_vision(client, file_content, mime_type)

    if not parsed:
        logger.warning(f"[{filename}] Parser IA no devolvió datos")
        return None

    return _normalize_parsed_data(parsed)


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
    except ImportError:
        logger.debug("PyMuPDF no instalado, probando pdfplumber")
    except Exception as e:
        logger.debug(f"PyMuPDF falló: {e}")

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
            return text
    except ImportError:
        logger.warning("Ni PyMuPDF ni pdfplumber instalados — el parseo de texto PDF no funcionará")
    except Exception as e:
        logger.debug(f"pdfplumber falló: {e}")

    return None


def _call_with_retry(client, **kwargs):
    """Llama a la API con reintentos en caso de error transitorio."""
    max_retries = 3
    base_delay = 2  # segundos

    for attempt in range(1, max_retries + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            err_name = e.__class__.__name__
            if 'RateLimitError' in err_name or 'APITimeoutError' in err_name or 'APIConnectionError' in err_name:
                if attempt < max_retries:
                    wait = base_delay * (2 ** (attempt - 1))  # 2, 4, 8
                    logger.warning(f"API error transitorio ({err_name}), reintento {attempt}/{max_retries} en {wait}s")
                    time.sleep(wait)
                else:
                    logger.error(f"API error tras {max_retries} reintentos: {_sanitize_error(e)}")
                    raise
            else:
                # Error no transitorio
                raise


def _parse_with_text(client, text):
    try:
        resp = _call_with_retry(
            client,
            model=os.getenv('OPENCODE_MODEL', 'deepseek-v4-flash'),
            messages=[
                {'role': 'system', 'content': 'Eres un extractor de datos de facturas. Devuelve JSON válido.'},
                {'role': 'user', 'content': f'{PROMPT_PARSE}\n\nTexto de la factura:\n{text[:15000]}'}
            ],
            temperature=0.05,
            response_format={'type': 'json_object'}
        )
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError as e:
        logger.error(f"IA no devolvió JSON válido: {e}")
        return None
    except Exception as e:
        logger.error(f"Text parse error: {e.__class__.__name__}: {_sanitize_error(e)}")
        return None


def _parse_with_vision(client, content, mime_type):
    # Si hay API key de OpenAI, usar gpt-4o-mini que soporta vision real
    openai_key = os.getenv('OPENAI_API_KEY')
    if openai_key:
        try:
            from openai import OpenAI as OpenAIClient
            vision_client = OpenAIClient(api_key=openai_key)
            b64 = base64.b64encode(content).decode()
            resp = _call_with_retry(
                vision_client,
                model='gpt-4o-mini',
                messages=[
                    {'role': 'system', 'content': 'Analiza esta imagen de factura y extrae los datos en JSON.'},
                    {'role': 'user', 'content': [
                        {'type': 'text', 'text': PROMPT_PARSE},
                        {'type': 'image_url', 'image_url': {
                            'url': f'data:{mime_type};base64,{b64}',
                            'detail': 'auto'
                        }}
                    ]}
                ],
                temperature=0.05,
                max_tokens=1000,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            logger.warning("OpenAI vision fallo (%s), probando OpenCode...", e.__class__.__name__)

    # Fallback: OpenCode / DeepSeek (solo texto, no soporta image_url real)
    try:
        b64 = base64.b64encode(content).decode()
        resp = _call_with_retry(
            client,
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
    except json.JSONDecodeError as e:
        logger.error(f"IA no devolvió JSON válido: {e}")
        return None
    except Exception as e:
        logger.error(f"Vision parse error: {e.__class__.__name__}: {_sanitize_error(e)}")
        return None
