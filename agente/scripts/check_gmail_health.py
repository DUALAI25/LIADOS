#!/usr/bin/env python3
"""
check_gmail_health.py — watchdog proactivo de tokens Gmail.

USO:
    python3 -m agente.scripts.check_gmail_health          # check actual
    python3 -m agente.scripts.check_gmail_health --quiet  # solo errores

DISENO:
    - Lee GMAIL_ACCOUNTS del .env
    - Para cada cuenta, prueba un refresh de su token
    - Si INVALID_GRANT: lo purga, deja el log agente impactado y devuelve exit 1
    - Si OK: actualiza el token en disco con el access nuevo
    - Si hay incidencias (REVOKED, MISSING_TOKEN, MISSING_CREDS, MALFORMED):
      avisa por Telegram al jefe con detalle accionable
    - Pensado para correr 1 vez al dia (cron a las 5:55 AM, antes del sync 6:00)

PATRON operativo:
    0 6 * * * /root/liados/.venv/bin/python -m agente.scripts.run_all
    55 5 * * * /root/liados/.venv/bin/python -m agente.scripts.check_gmail_health

El check 5 minutos antes del sync permite que el jefe reciba la alerta
por Telegram ANTES de que el sync falle silenciosamente.
"""

import os
import sys
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime) [%(levelname)] %(message)s',
)
logger = logging.getLogger('gmail-health')

WORKSPACE = Path('/root/liados')

# --- Telegram notify (capa 2 hardening 2026-07-17) ---
TELEGRAM_API = 'https://api.telegram.org/bot{token}/{method}'


def send_telegram(env, message, silent=False):
    """Envía alerta al Telegram del jefe. Silencioso si falla el wiring."""
    token = env.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = env.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        logger.debug('TELEGRAM_BOT_TOKEN/CHAT_ID no configurados; no se notifica')
        return False
    url = TELEGRAM_API.format(token=token, method='sendMessage')
    payload = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': message,
        'disable_notification': 'true' if silent else 'false',
    }).encode()
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            if not body.get('ok'):
                logger.warning('Telegram devolvió ok=false: %s', body)
                return False
            return True
    except Exception as e:
        logger.warning('Telegram notify falló (no crítico): %s', e)
        return False


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


def check_account(account, env, quiet=False):
    """Testea el refresh del token de una cuenta. Purgar si esta muerto."""
    state = 'OK'
    issues = []

    creds_var = f'GMAIL_CREDENTIALS_FILE_{account}'
    token_var = f'GMAIL_TOKEN_FILE_{account}'

    creds_path = resolve_path(env.get(creds_var, ''))
    token_path = resolve_path(env.get(token_var, ''))

    if not creds_path.exists():
        return 'MISSING_CREDS', [f'No existe {creds_path}']
    if not token_path.exists():
        return 'MISSING_TOKEN', [f'No existe {token_path}']

    with creds_path.open() as f:
        ccfg = json.load(f)
    with token_path.open() as f:
        tcfg = json.load(f)

    c = ccfg.get('installed') or ccfg.get('web') or {}
    client_id = c.get('client_id')
    client_secret = c.get('client_secret')
    refresh_token = tcfg.get('refresh_token')

    if not all([client_id, client_secret, refresh_token]):
        return 'MALFORMED', ['Faltan client_id, client_secret o refresh_token']

    # Probe refresh
    data = urllib.parse.urlencode({
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    }).encode()

    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            # OK: refresca y guarda
            tcfg['access_token'] = body['access_token']
            tcfg['expires_in'] = body['expires_in']
            tcfg['last_check'] = (
                __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc
                ).isoformat()
            )
            with token_path.open('w') as f:
                json.dump(tcfg, f, indent=2)
            os.chmod(token_path, 0o600)
            return 'OK', [f'Access Token nuevo expira en {body["expires_in"]}s']
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        try:
            err = json.loads(err_body)
            err_code = err.get('error', 'unknown')
            err_desc = err.get('error_description', '')
        except Exception:
            err_code = 'unknown'
            err_desc = err_body

        if 'invalid_grant' in err_code.lower() or 'revoked' in err_desc.lower():
            # Purgar token muerto
            from shutil import move
            from datetime import datetime, timezone
            revoked_dir = WORKSPACE / 'data' / 'tokens_revoked'
            revoked_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            backup = revoked_dir / f'{ts}_{token_path.name}.invalid_grant_healthcheck'
            move(str(token_path), str(backup))
            return 'REVOKED', [
                f'Token REVOCADO por Google: {err_desc}',
                f'Movido a {backup}',
                f'Reautorizar: python3 -m agente.scripts.gmail_auth --account {account} --force',
            ]
        return 'TRANSIENT', [f'HTTP {e.code}: {err_desc}']
    except Exception as e:
        return 'NETWORK_ERROR', [str(e)[:200]]


def main():
    quiet = '--quiet' in sys.argv
    log_level = logging.WARNING if quiet else logging.INFO
    logging.getLogger().setLevel(log_level)

    env = load_env()
    accounts_raw = env.get('GMAIL_ACCOUNTS', '')
    accounts = [a.strip() for a in accounts_raw.split(',') if a.strip()]

    if not accounts:
        print('⚠ GMAIL_ACCOUNTS no definido en .env')
        return 2

    print('=' * 60)
    print(f'GMAIL HEALTH CHECK ({len(accounts)} cuentas)')
    print('=' * 60)

    attention = []
    for account in accounts:
        status, issues = check_account(account, env, quiet=quiet)
        icon = {
            'OK': '✓', 'MISSING_CREDS': '✗',
            'MISSING_TOKEN': '✗', 'MALFORMED': '✗',
            'REVOKED': '🔴', 'TRANSIENT': '⚠',
            'NETWORK_ERROR': '⚠',
        }.get(status, '?')
        print(f'  [{icon} {status:15}] {account}')
        for msg in issues:
            print(f'        {msg}')
        if status in ('REVOKED', 'MISSING_TOKEN', 'MISSING_CREDS', 'MALFORMED'):
            attention.append((account, status, issues))

    print('=' * 60)
    if attention:
        print(f'🔴 ATENCIÓN: {len(attention)} cuenta(s) requieren ACCIÓN:')
        for acc, st, _ in attention:
            print(f'     - {acc}: {st}')
        print()
        print('   Ejecutar para cada cuenta:')
        print('     python3 -m agente.scripts.gmail_auth --account <cuenta> --force')

        # --- Telegram notify (capa 2 hardening 2026-07-17) ---
        lines = [f'🔴 Liados Gmail health — {len(attention)} cuenta(s) con token muerto:']
        for acc, st, msgs in attention:
            lines.append(f'• {acc}: {st}')
            for m in msgs[:2]:
                lines.append(f'  → {m}')
        lines.append('')
        lines.append('Reautorizar: python3 -m agente.scripts.gmail_auth --account <cuenta> --force')
        send_telegram(env, '\n'.join(lines))

        return 1
    print('Estado OK. Tokens pueden hacer refresh.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
