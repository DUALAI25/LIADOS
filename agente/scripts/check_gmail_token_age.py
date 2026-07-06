#!/usr/bin/env python3
"""
check_gmail_token_age.py — monitor proactivo de edad de tokens Gmail.

USO:
    python3 -m agente.scripts.check_gmail_token_age          # check actual
    python3 -m agente.scripts.check_gmail_token_age --quiet  # solo warnings

DIFERENCIA vs check_gmail_health.py:
    - check_gmail_health.py: prueba el REFRESH (¿funciona el token AHORA?)
    - check_gmail_token_age.py: lee la FECHA del token en disco y avisa
      ANTES de que muera (umbral por defecto: 5 días desde emitido)

RAZON:
    Google en "Testing mode" mata refresh_tokens a los 7 días SILENCIOSAMENTE.
    Necesitamos un margen de 2 días para reautorizar manualmente.

CRON RECOMENDADO:
    0 8 * * *  /root/liados/.venv/bin/python -m agente.scripts.check_gmail_token_age
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('gmail-token-age')

WORKSPACE = Path('/root/liados')
WARN_DAYS = int(os.getenv('GMAIL_TOKEN_WARN_DAYS', '5'))  # 5 días = 2 días de margen
CRITICAL_DAYS = int(os.getenv('GMAIL_TOKEN_CRITICAL_DAYS', '6'))  # 6 días = 1 día de margen


def load_env():
    env = {}
    env_file = WORKSPACE / '.env'
    if not env_file.exists():
        return env
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def resolve_path(p):
    pp = Path(p).expanduser()
    if not pp.is_absolute():
        pp = WORKSPACE / pp
    return pp


def parse_token_date(token_path):
    """
    Extrae la fecha de emisión del token desde uno de estos campos (en orden):
      1. 'issued_at' (ISO 8601) — preferido, lo escribimos nosotros
      2. 'last_check' (ISO 8601) — fallback
      3. fecha de modificación del archivo
    """
    try:
        with token_path.open() as f:
            tcfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, "no_se_pudo_leer_json"

    for field in ('issued_at', 'last_check'):
        val = tcfg.get(field)
        if not val:
            continue
        try:
            dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
            return dt, field
        except (ValueError, AttributeError):
            continue

    # Fallback: mtime del archivo
    try:
        mtime = token_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc), 'file_mtime'
    except OSError:
        return None, "no_se_pudo_leer_mtime"


def check_account(account, env, quiet=False):
    token_var = f'GMAIL_TOKEN_FILE_{account}'
    token_path = resolve_path(env.get(token_var, ''))

    if not token_path.exists():
        return 'MISSING', [f'No existe {token_path}']

    issued_at, source = parse_token_date(token_path)
    if issued_at is None:
        return 'UNKNOWN_AGE', [f'No se pudo determinar fecha de {token_path}']

    now = datetime.now(timezone.utc)
    age = now - issued_at
    days = age.days

    icon = '✓'
    level = 'OK'
    msgs = [f'Edad: {days} días (fuente: {source})']

    if days >= CRITICAL_DAYS:
        icon = '🔴'
        level = 'CRITICAL'
        msgs.append(f'CRÍTICO: token expira en ~{7 - days} día(s). Reautorizar YA.')
    elif days >= WARN_DAYS:
        icon = '⚠'
        level = 'WARN'
        msgs.append(f'WARN: token cerca de expirar (en ~{7 - days} días). Reautorizar pronto.')

    msgs.append(f'Reautorizar: python3 -m agente.scripts.gmail_auth --account {account} --force')
    return level, msgs, icon


def main():
    quiet = '--quiet' in sys.argv
    if quiet:
        logging.getLogger().setLevel(logging.WARNING)

    env = load_env()
    accounts_raw = env.get('GMAIL_ACCOUNTS', '')
    accounts = [a.strip() for a in accounts_raw.split(',') if a.strip()]

    if not accounts:
        print('⚠ GMAIL_ACCOUNTS no definido en .env')
        return 2

    print('=' * 60)
    print(f'GMAIL TOKEN AGE MONITOR ({len(accounts)} cuentas)')
    print(f'Umbrales: WARN >= {WARN_DAYS}d, CRITICAL >= {CRITICAL_DAYS}d')
    print('=' * 60)

    attention = []
    for account in accounts:
        result = check_account(account, env, quiet=quiet)
        if result[0] in ('MISSING', 'UNKNOWN_AGE'):
            level, msgs = result
            icon = '✗'
        else:
            level, msgs, icon = result
        print(f'  [{icon} {level:10}] {account}')
        for msg in msgs:
            print(f'        {msg}')
        if level in ('WARN', 'CRITICAL', 'MISSING', 'UNKNOWN_AGE'):
            attention.append((account, level))

    print('=' * 60)
    if attention:
        print(f'🔴 ATENCIÓN: {len(attention)} cuenta(s) requieren ACCIÓN:')
        for acc, st in attention:
            print(f'     - {acc}: {st}')
        print()
        print('ACCIÓN:')
        print('  1. Ir a https://console.cloud.google.com/apis/credentials/consent')
        print('  2. Click "PUBLISH APP" (botón azul, esquina superior derecha)')
        print('  3. Reautorizar: python3 -m agente.scripts.gmail_auth --account <cuenta> --force')
        return 1
    print('✓ Todos los tokens dentro del rango seguro.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
