#!/usr/bin/env python3
"""Backup BD wrapper. Lee .env directamente."""
import os, subprocess, gzip
from datetime import datetime

env = {}
with open('/root/liados/.env') as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            env[k.strip()] = v.strip().strip("'").strip('"')

myenv = os.environ.copy()
myenv['PGPASSWORD'] = env.get('DB_PASSWORD', '')

dst = f'/root/liados/backups/db-{datetime.now().strftime("%Y%m%d-%H%M")}.sql.gz'

res = subprocess.run([
    'pg_dump', '-h', 'localhost', '-U', 'desliado', '-d', 'desliado',
    '--exclude-table=_pre_limpieza_20260622',
    '--exclude-table=category_mapping',
], capture_output=True, timeout=120, env=myenv)

if res.returncode == 0 and len(res.stdout) > 1000:
    data = gzip.compress(res.stdout)
    with open(dst, 'wb') as out:
        out.write(data)
    print(f'BACKUP OK: {len(data)/1024/1024:.1f} MB -> {dst}')
else:
    print(f'FAIL: rc={res.returncode} out={len(res.stdout)}')
    if res.stderr:
        err_text = res.stderr.decode()
        for line in err_text.split('\n'):
            if 'permission denied' in line:
                tbl = line.split('table ')[-1].split(' ')[0] if 'table ' in line else ''
                print(f'  Problem: {tbl}')

# Rotate: keep last 5
backups = sorted([f for f in os.listdir('/root/liados/backups') if f.endswith('.sql.gz')], reverse=True)
for old in backups[5:]:
    os.remove(os.path.join('/root/liados/backups', old))
    print(f'Removed old: {old}')