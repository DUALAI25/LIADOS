"""Orquestador principal: ejecuta Last.app sync + Gmail collector en orden.

Uso:
    python3 -m agente.scripts.run_all                # ejecucion normal
    python3 -m agente.scripts.run_all --skip-gmail   # saltar gmail
    python3 -m agente.scripts.run_all --days 7       # override dias iniciales gmail
    python3 -m agente.scripts.run_all --dry-run      # solo mostrar lo que haria
"""
import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent


def _build_child_env(days_override=None):
    """Construye el entorno para subprocesos: hereda + .env + PYTHONPATH."""
    child_env = os.environ.copy()

    # Cargar .env del workspace
    env_file = WORKSPACE / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    val = v.strip().strip('"').strip("'")
                    # No sobreescribir env vars del padre si el .env tiene vacio
                    if val:
                        child_env[k.strip()] = val

    # Añadir agente/scripts/ al PYTHONPATH para que los imports relativos funcionen
    existing = child_env.get("PYTHONPATH", "")
    child_env["PYTHONPATH"] = str(SCRIPTS_DIR) + (":" + existing if existing else "")

    if days_override:
        child_env["GMAIL_INITIAL_DAYS"] = str(days_override)
        logger.info("Override GMAIL_INITIAL_DAYS=%d", days_override)

    return child_env


def run_block(name, cmd, dry_run=False, child_env=None):
    """Ejecuta un subproceso y reporta resultado. Exit code 0 = OK."""
    logger.info("=" * 60)
    logger.info("Ejecutando bloque: %s", name)
    logger.info("  cmd: %s", ' '.join(cmd))
    logger.info("=" * 60)
    if dry_run:
        logger.info("[DRY-RUN] Saltando ejecucion de %s", name)
        return True
    start = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,
            cwd=str(WORKSPACE),
            env=child_env or os.environ,
        )
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        if result.returncode == 0:
            logger.info("  %s OK (%.1fs)", name, elapsed)
            if result.stdout.strip():
                last_lines = result.stdout.strip().splitlines()[-5:]
                for line in last_lines:
                    logger.info("  %s", line)
            return True
        else:
            logger.error("  %s FALLO (rc=%d, %.1fs)", name, result.returncode, elapsed)
            logger.error("  stderr (completo): %s", result.stderr)
            return False
    except subprocess.TimeoutExpired:
        logger.error("  %s TIMEOUT (>1800s = 30min)", name)
        return False
    except Exception as e:
        logger.error("  %s ERROR: %s", name, e)
        return False



def _maybe_notify_telegram(failed_blocks):
    """Notifica al jefe por Telegram si hay bloques fallando. Best-effort."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        import requests
        msg = (
            "*Liados sync FALLO*\n\n"
            "Bloques fallidos: " + ", ".join(failed_blocks) + "\n"
            "Ver /root/liados/data/run_all.log para detalles."
        )
        requests.post(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=10,
        )
        logger.info("Notificacion enviada a Telegram")
    except Exception as e:
        logger.warning("No se pudo notificar a Telegram: " + str(e))


def main():
    # C-4 fix: file lock to prevent concurrent runs
    import fcntl
    lock_file = open('/tmp/run_all.lock', 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logger.error("Otra instancia de run_all ya esta en ejecucion. Abortando.")
        return
    parser = argparse.ArgumentParser(description="Orquestador Liados")
    parser.add_argument("--skip-lastapp", action="store_true", help="Saltar Last.app sync")
    parser.add_argument("--skip-gmail", action="store_true", help="Saltar Gmail collector")
    parser.add_argument("--skip-drive", action="store_true", help="Saltar Drive collector")
    parser.add_argument("--days", type=int, help="Override GMAIL_INITIAL_DAYS para esta ejecucion")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar que haria")
    args = parser.parse_args()

    child_env = _build_child_env(days_override=args.days)

    blocks = []

    if not args.skip_lastapp:
        blocks.append(("Last.app sync", ["python3", "-m", "agente.scripts.lastapp_sync"]))

    if not args.skip_gmail:
        blocks.append(("Gmail collector", ["python3", "-m", "agente.scripts.gmail_collector"]))

    if not args.skip_drive:
        # PATCH v2: Drive collector integrado al orquestador
        blocks.append(("Drive collector", ["python3", "-m", "agente.scripts.drive_collector", "--once"]))

    if not blocks:
        logger.error("Todos los bloques saltados, nada que hacer")
        return 1

    results = []
    for name, cmd in blocks:
        ok = run_block(name, cmd, dry_run=args.dry_run, child_env=child_env)
        results.append((name, ok))

    logger.info("=" * 60)
    logger.info("RESUMEN")
    logger.info("=" * 60)
    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        status = "OK" if ok else "FAIL"
        logger.info("  [%s] %s", status, name)
    if failed:
        logger.error("Bloques fallidos: %s", failed)
        _maybe_notify_telegram(failed)
        return 1
    logger.info("Todos los bloques OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
