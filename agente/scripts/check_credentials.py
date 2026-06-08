"""
check_credentials.py — Verifica que todas las credenciales necesarias están configuradas

Soporta multi-cuenta Gmail (GMAIL_ACCOUNTS=cuenta1,cuenta2).
"""
import os
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
ENV_FILE = WORKSPACE / '.env'


def load_env():
    if not ENV_FILE.exists():
        print(f"❌ No se encuentra {ENV_FILE}")
        print("   Ejecuta: cp .env.example .env y edítalo")
        return {}
    env_vars = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    return env_vars


def check(label, var_name, env, check_file=False, optional=False):
    val = env.get(var_name, '')
    if not val or val.startswith('***'):
        marker = '⏭️ ' if optional else '❌'
        suffix = ' (OPCIONAL, no configurado)' if optional else ''
        print(f"  {marker} {label}: {var_name}{suffix}")
        return False
    if check_file and not Path(val).exists():
        print(f"  ❌ {label}: {var_name} — ARCHIVO NO ENCONTRADO ({val})")
        return False
    if check_file:
        print(f"  ✅ {label}: {val}")
    else:
        display = val[:30] + '...' if len(val) > 30 else val
        print(f"  ✅ {label}: {display}")
    return True


def main():
    print("=" * 60)
    print("VERIFICACIÓN DE CREDENCIALES — Desliado")
    print("=" * 60)
    print()

    env = load_env()
    if not env:
        sys.exit(1)

    all_ok = True

    # Gmail multi-cuenta
    print("📧 Gmail API (multi-cuenta):")
    accounts_raw = env.get('GMAIL_ACCOUNTS', '')
    if not accounts_raw:
        print(f"  ❌ GMAIL_ACCOUNTS no configurado en .env")
        print(f"     Añade: GMAIL_ACCOUNTS=cuenta1,cuenta2")
        all_ok = False
    else:
        accounts = [a.strip() for a in accounts_raw.split(',') if a.strip()]
        print(f"  ✅ GMAIL_ACCOUNTS: {', '.join(accounts)} ({len(accounts)} cuentas)")
        for acc in accounts:
            print(f"\n  ── Cuenta: {acc} ──")
            creds_ok = check("Credenciales OAuth", f'GMAIL_CREDENTIALS_FILE_{acc}', env, check_file=True)
            token_ok = check("Token OAuth", f'GMAIL_TOKEN_FILE_{acc}', env, check_file=True)
            if not (creds_ok and token_ok):
                print(f"     👉 Para autorizar: python3 agente/scripts/gmail_auth.py --account {acc}")
            all_ok &= creds_ok and token_ok

    print()
    print("🤖 OpenCode Go:")
    all_ok &= check("API Key", 'OPENCODE_API_KEY', env)
    check("Base URL", 'OPENCODE_BASE_URL', env)  # opcional, tiene default
    check("Modelo", 'OPENCODE_MODEL', env)  # opcional, tiene default

    print()
    print("🏪 Lastapp:")
    check("API URL", 'LASTAPP_API_URL', env)  # opcional, tiene default
    lastapp_ok = check("API Token", 'LASTAPP_API_TOKEN', env)
    if not lastapp_ok:
        print("     ⚠️  Sin Lastapp: la sincronización de ventas no funcionará")
    # Lastapp no es bloqueante, pero warning

    print()
    print("📱 Telegram (OPCIONAL):")
    check("Bot Token", 'TELEGRAM_BOT_TOKEN', env, optional=True)
    check("Chat ID", 'TELEGRAM_CHAT_ID', env, optional=True)

    print()
    print("🗄️  Base de datos:")
    check("DB Host", 'DB_HOST', env)  # opcional, default localhost
    pg_ok = check("DB Password", 'DB_PASSWORD', env)
    all_ok &= pg_ok

    print()
    print("📦 MinIO (OPCIONAL — si no, filesystem local):")
    check("Endpoint", 'MINIO_ENDPOINT', env, optional=True)
    check("Access Key", 'MINIO_ACCESS_KEY', env, optional=True)
    check("Secret Key", 'MINIO_SECRET_KEY', env, optional=True)

    print()
    print("🗂️  Almacenamiento:")
    check("Data dir", 'DATA_DIR', env)  # opcional, tiene default

    print()
    print("=" * 60)
    if all_ok:
        print("✅ BLOQUEANTES OK — el sistema puede arrancar")
    else:
        print("❌ Faltan credenciales BLOQUEANTES — revisa lo marcado arriba")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
