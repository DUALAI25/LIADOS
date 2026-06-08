"""
check_credentials.py — Verifica que todas las credenciales necesarias están configuradas
"""
import os
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent  # scripts/ → agente/ → workspace root
ENV_FILE = WORKSPACE / '.env'


def load_env():
    if not ENV_FILE.exists():
        print(f"❌ No se encuentra {ENV_FILE}")
        return {}
    env_vars = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    return env_vars


def check(label, var_name, env, check_file=False):
    val = env.get(var_name, '')
    if not val:
        print(f"  ❌ {label}: {var_name} — NO CONFIGURADO")
        return False
    if check_file and not Path(val).exists():
        print(f"  ❌ {label}: {var_name} — ARCHIVO NO ENCONTRADO ({val})")
        return False
    if check_file:
        print(f"  ✅ {label}: {val}")
    else:
        print(f"  ✅ {label}: {val[:20]}...") if len(val) > 20 else print(f"  ✅ {label}: {val}")
    return True


def main():
    print("=" * 60)
    print("VERIFICACIÓN DE CREDENCIALES — Desliado")
    print("=" * 60)
    print()

    env = load_env()
    all_ok = True

    print("📧 Gmail API:")
    all_ok &= check("Credenciales OAuth", 'GMAIL_CREDENTIALS_FILE', env, check_file=True)
    all_ok &= check("Token OAuth", 'GMAIL_TOKEN_FILE', env, check_file=True)

    print()
    print("🤖 OpenCode Go:")
    all_ok &= check("API Key", 'OPENCODE_API_KEY', env)
    all_ok &= check("Base URL", 'OPENCODE_BASE_URL', env)
    all_ok &= check("Modelo", 'OPENCODE_MODEL', env)

    print()
    print("🏪 Lastapp:")
    all_ok &= check("API URL", 'LASTAPP_API_URL', env)
    all_ok &= check("API Token", 'LASTAPP_API_TOKEN', env)

    print()
    print("📱 Telegram:")
    all_ok &= check("Bot Token", 'TELEGRAM_BOT_TOKEN', env)
    all_ok &= check("Chat ID", 'TELEGRAM_CHAT_ID', env)

    print()
    print("🗄️  Base de datos:")
    all_ok &= check("DB Host", 'DB_HOST', env)
    pg_ok = check("DB Password", 'DB_PASSWORD', env)
    all_ok &= pg_ok

    print()
    print("📦 MinIO:")
    all_ok &= check("Endpoint", 'MINIO_ENDPOINT', env)
    all_ok &= check("Access Key", 'MINIO_ACCESS_KEY', env)
    all_ok &= check("Secret Key", 'MINIO_SECRET_KEY', env)

    print()
    print("🗂️  Almacenamiento:")
    all_ok &= check("Data dir", 'DATA_DIR', env)

    print()
    print("=" * 60)
    total = 15  # número total de checks
    ok_count = len([k for k in env if env[k]])
    print(f"Resultado: {ok_count}/{total} configuradas")
    if all_ok:
        print("✅ TODAS LAS CREDENCIALES OK — el sistema puede funcionar")
    else:
        print("⚠️  Faltan credenciales — revisa .env")
    print("=" * 60)


if __name__ == '__main__':
    main()
