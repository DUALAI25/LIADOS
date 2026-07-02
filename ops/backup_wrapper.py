#!/usr/bin/env python3
"""Backup BD wrapper. Lee .env directamente.

Salida:
  - STDOUT: log para el cron (visible en /var/log/syslog o /var/log/cron)
  - Exit code: 0 = OK, !=0 = fallo (cron enviara mail con el error)
"""
import os, sys, subprocess, gzip, logging
from datetime import datetime, timezone

LOG = '/root/liados/data/backup.log'
os.makedirs(os.path.dirname(LOG), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('backup')

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

myenv = os.environ.copy()
myenv['PGPASSWORD'] = env.get('DB_PASSWORD', '')

dst_dir = '/root/liados/backups'
os.makedirs(dst_dir, exist_ok=True)
dst = f'{dst_dir}/db-{datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")}.sql.gz'

try:
    res = subprocess.run([
        'pg_dump', '-h', 'localhost', '-U', 'desliado', '-d', 'desliado',
        '--exclude-table=_pre_limpieza_20260622',
        '--exclude-table=category_mapping',
    ], capture_output=True, timeout=300, env=myenv)
except subprocess.TimeoutExpired:
    logger.error("pg_dump timeout (>300s)")
    sys.exit(1)
except Exception as e:
    logger.error(f"pg_dump fallo: {e}")
    sys.exit(1)

if res.returncode != 0 or len(res.stdout) < 1000:
    logger.error(f"pg_dump rc={res.returncode} size={len(res.stdout)}")
    if res.stderr:
        for line in res.stderr.decode(errors='replace').split('\n')[:5]:
            if line.strip():
                logger.error(f"  pg: {line}")
    sys.exit(1)

data = gzip.compress(res.stdout)
with open(dst, 'wb') as out:
    out.write(data)
logger.info(f"BACKUP OK: {len(data)/1024/1024:.1f} MB -> {dst}")

# Rotate: keep last 7 (1 semana)
backups = sorted([f for f in os.listdir(dst_dir) if f.endswith('.sql.gz')], reverse=True)
for old in backups[7:]:
    p = os.path.join(dst_dir, old)
    os.remove(p)
    logger.info(f"Removed old: {old}")