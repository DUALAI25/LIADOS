"""agente/scripts/reparse_pending.py - Reprocesa adjuntos pendientes en raw/."""
from __future__ import annotations
import os, sys, json, logging
from pathlib import Path
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reparse")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "invoices" / "raw"
MIME = {".pdf":"application/pdf",".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png"}
def main() -> int:
    dry = os.environ.get("PARSE_DRY_RUN","0")=="1"
    if not RAW_DIR.exists():
        logger.error("No existe %s", RAW_DIR); return 1
    sys.path.insert(0, str(PROJECT_ROOT / "agente" / "scripts"))
    try:
        from invoice_parser import parse_invoice
        from db_writer import save_invoice, log_agent
    except Exception as exc:
        logger.error("No pude importar modulos: %s", exc); return 1
    target = RAW_DIR / "2026" / "07"
    files = [f for f in sorted(target.iterdir()) if f.is_file() and f.suffix.lower() in MIME] if target.exists() else []
    logger.info("Encontrados %d archivos en %s", len(files), target)
    ok, fail = 0, 0
    for f in files:
        mime = MIME[f.suffix.lower()]
        try:
            data = parse_invoice(str(f), mime, filename=f.name)
        except Exception as exc:
            logger.error("%s -> exception: %s", f.name, exc); fail += 1; continue
        if not data:
            logger.warning("%s -> parser sin datos", f.name); fail += 1; continue
        if dry:
            logger.info("DRY %s -> %s", f.name, json.dumps(data, default=str)[:200]); ok += 1; continue
        try:
            inv = save_invoice(data, source="gmail", source_id=str(f))
            logger.info("OK %s -> invoice %s", f.name, inv.get("id") if isinstance(inv, dict) else inv)
            ok += 1
        except Exception as exc:
            logger.error("%s -> save fallo: %s", f.name, exc); fail += 1
    try:
        log_agent("reparse_pending", "ok" if fail==0 else "warning", f"ok={ok} fail={fail} total={len(files)}")
    except Exception: pass
    logger.info("RESUMEN total=%d ok=%d fail=%d", len(files), ok, fail)
    return 0 if fail==0 else 1
if __name__ == "__main__":
    sys.exit(main())
