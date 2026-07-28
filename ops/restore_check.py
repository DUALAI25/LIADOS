#!/usr/bin/env python3
"""Restore test mensual - verifica que el ultimo backup es recuperable."""
import os
import sys
import subprocess
import gzip
import logging
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from pathlib import Path

LOG = '/root/liados/data/restore_check.log'
os.makedirs(os.path.dirname(LOG), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('restore_check')


# Cargar .env
env = {}
env_path = '/root/liados/.env'
if not os.path.exists(env_path):
    logger.error(f"No se encuentra {env_path}")
    sys.exit(1)
with open(env_path) as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            env[k.strip()] = v.strip().strip("'").strip('"')

DB_USER = env.get('DB_USER', 'desliado')
DB_NAME = env.get('DB_NAME', 'desliado')
DB_PASSWORD = env.get('DB_PASSWORD', '')
TELEGRAM_BOT_TOKEN = env.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = env.get('TELEGRAM_CHAT_ID', '')

BACKUP_DIR = Path('/root/liados/backups')
SCRATCH_DB = 'desliado_restore_check'


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        logger.warning(f"Telegram fallo: {e}")
        return False


def run(cmd, **kwargs):
    logger.info(f"$ {' '.join(cmd[:5])}{'...' if len(cmd) > 5 else ''}")
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def main():
    start = datetime.now(timezone.utc)
    logger.info(f"=== Inicio restore check {start.isoformat()} ===")

    backups = sorted(BACKUP_DIR.glob('db-*.sql.gz'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        msg = "🔴 **Liados restore check FAIL**\n\nNo hay backups en /root/liados/backups/"
        logger.error(msg)
        send_telegram(msg)
        sys.exit(1)

    latest_backup = backups[0]
    logger.info(f"Backup: {latest_backup} ({latest_backup.stat().st_size} bytes)")

    logger.info(f"Creando BD scratch: {SCRATCH_DB}")
    run(['sudo', '-u', 'postgres', 'dropdb', '--if-exists', SCRATCH_DB])
    res = run(['sudo', '-u', 'postgres', 'createdb', SCRATCH_DB])
    if res.returncode != 0:
        msg = f"🔴 **Liados restore check FAIL**\n\nError creando BD: {res.stderr[:200]}"
        logger.error(msg)
        send_telegram(msg)
        sys.exit(1)

    logger.info(f"Restaurando {latest_backup}...")
    tmp_sql = '/tmp/restore-check.sql'
    with gzip.open(latest_backup, 'rb') as f_in:
        with open(tmp_sql, 'wb') as f_out:
            f_out.write(f_in.read())

    myenv = os.environ.copy()
    myenv['PGPASSWORD'] = DB_PASSWORD
    res = subprocess.run(
        ['sudo', '-u', 'postgres', 'psql', '-d', SCRATCH_DB, '-f', tmp_sql],
        capture_output=True, text=True, timeout=300, env=myenv,
    )
    os.remove(tmp_sql)

    if res.returncode != 0:
        msg = f"🔴 **Liados restore check FAIL**\n\npsql rc={res.returncode}\n{res.stderr[-300:]}"
        logger.error(msg)
        send_telegram(msg)
        sys.exit(1)

    def get_count(db, query):
        r = run(['sudo', '-u', 'postgres', 'psql', '-d', db, '-tAc', query])
        try:
            return int(r.stdout.strip())
        except ValueError:
            return 0

    prod_invoices = get_count(DB_NAME, 'SELECT COUNT(*) FROM invoices;')
    scratch_invoices = get_count(SCRATCH_DB, 'SELECT COUNT(*) FROM invoices;')
    prod_vendors = get_count(DB_NAME, 'SELECT COUNT(*) FROM vendors;')
    scratch_vendors = get_count(SCRATCH_DB, 'SELECT COUNT(*) FROM vendors;')
    prod_categories = get_count(DB_NAME, 'SELECT COUNT(*) FROM categories;')
    scratch_categories = get_count(SCRATCH_DB, 'SELECT COUNT(*) FROM categories;')

    run(['sudo', '-u', 'postgres', 'dropdb', SCRATCH_DB])

    ratio = scratch_invoices / prod_invoices if prod_invoices > 0 else 0
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    if ratio < 0.90:
        msg = (
            f"🟡 **Liados restore check WARN**\n\n"
            f"Ratio facturas: {ratio*100:.1f}% (scratch {scratch_invoices} / prod {prod_invoices})\n"
            f"Esperado: >=90%\n"
            f"Backup: `{latest_backup.name}`\n"
            f"Duracion: {elapsed:.1f}s"
        )
        logger.warning(msg)
        send_telegram(msg)
        sys.exit(0)

    msg = (
        f"✅ **Liados restore check OK**\n\n"
        f"Backup: `{latest_backup.name}`\n"
        f"Facturas: scratch={scratch_invoices} / prod={prod_invoices} ({ratio*100:.1f}%)\n"
        f"Vendors: scratch={scratch_vendors} / prod={prod_vendors}\n"
        f"Categorias: scratch={scratch_categories} / prod={prod_categories}\n"
        f"Duracion: {elapsed:.1f}s\n\n"
        f"Restore probado en BD scratch `{SCRATCH_DB}` (creada y eliminada)."
    )
    logger.info(msg)
    send_telegram(msg)
    sys.exit(0)


if __name__ == '__main__':
    main()
