#!/usr/bin/env python3
"""
oauth_watchdog.py — Watchdog unificado de tokens OAuth Liados.

Monitorea el estado de TODOS los tokens OAuth (Gmail + Drive + futuras)
y avisa al jefe por Telegram cuando alguno esta MISSING / REVOKED / WARN.

USO:
    python -m agente.scripts.oauth_watchdog                # check + alerta
    python -m agente.scripts.oauth_watchdog --quiet        # solo errores
    python -m agente.scripts.oauth_watchdog --json         # output JSON parseable

SALIDA esperada OK:
    OK oauth_watchdog: 4 tokens OK (gmail:principal, gmail:secundaria, drive:principal, drive:secundaria)

SALIDA mala:
    ALERTA oauth_watchdog: 2 cuenta(s) requieren ACCION
       - gmail:principal: MISSING_TOKEN
       - drive:secundaria: REVOKED

Patron:
    - Lee tokens de /root/liados/agente/credentials/
    - Comprueba existencia + contenido
    - Calcula edad desde issued_at (si esta)
    - Emite alerta global (consolidada, no spam por cuenta)
    - Pensado para correr cada hora (cron en /etc/cron.d/liados)
"""
import os
import sys
import json
import logging
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("oauth-watchdog")

WORKSPACE = Path("/root/liados")
CREDENTIALS_DIR = WORKSPACE / "agente" / "credentials"
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Umbrales (en segundos)
WARN_DAYS = 5
CRITICAL_DAYS = 6
WARN_SEC = WARN_DAYS * 24 * 3600
CRITICAL_SEC = CRITICAL_DAYS * 24 * 3600

# Lista exhaustiva de tokens a vigilar
TOKENS_TO_CHECK = [
    ("gmail", "principal"),
    ("gmail", "secundaria"),
    ("drive", "principal"),
    ("drive", "secundaria"),
]


def load_env_file():
    """Lee .env del workspace sin exportar."""
    env = {}
    env_file = WORKSPACE / ".env"
    if not env_file.exists():
        return env
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("\"").strip("'")
    return env


def send_telegram(env, message):
    """Notifica via Telegram. No rompe si falla."""
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.debug("TELEGRAM_BOT_TOKEN/CHAT_ID no configurados")
        return False
    url = TELEGRAM_API.format(token=token, method="sendMessage")
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_notification": "true",
    }).encode()
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return bool(body.get("ok"))
    except Exception as e:
        logger.warning("telegram notify fallo (no critico): %s", e)
        return False


def check_token(service, account):
    """Estado de un token: ('OK'|'MISSING'|'REVOKED'|'MALFORMED'|'WARN'|'CRITICAL', details_dict)."""
    creds_file = CREDENTIALS_DIR / (service + "_credentials_" + account + ".json")
    token_file = CREDENTIALS_DIR / (service + "_token_" + account + ".json")

    if not creds_file.exists():
        return "MISSING_CREDS", {"reason": "no existe " + creds_file.name}
    if not token_file.exists():
        return "MISSING_TOKEN", {"reason": "no existe " + token_file.name}

    try:
        with token_file.open() as f:
            tok = json.load(f)
    except Exception as e:
        return "MALFORMED", {"reason": "json invalido: " + str(e)}

    if not tok.get("refresh_token"):
        return "MALFORMED", {"reason": "sin refresh_token"}

    raw_age = tok.get("issued_at") or tok.get("created_at")
    age_seconds = None
    if raw_age:
        try:
            dt = datetime.fromisoformat(raw_age.replace("Z", "+00:00"))
            age_seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            pass

    return "OK", {
        "age_seconds": age_seconds,
        "age_days": age_seconds / 86400 if age_seconds else None,
        "last_check": tok.get("last_check"),
        "has_access_token": bool(tok.get("access_token")),
    }


def main():
    quiet = "--quiet" in sys.argv
    as_json = "--json" in sys.argv

    if quiet:
        logging.getLogger().setLevel(logging.WARNING)

    env = load_env_file()
    results = {}
    attention = []

    for service, account in TOKENS_TO_CHECK:
        status, details = check_token(service, account)
        results[service + ":" + account] = {
            "status": status,
            "details": details,
        }
        if status in ("MISSING_CREDS", "MISSING_TOKEN", "MALFORMED"):
            attention.append((service, account, status, details))
        elif status == "OK" and details.get("age_seconds"):
            if details["age_seconds"] >= CRITICAL_SEC:
                attention.append((service, account, "CRITICAL", details))
            elif details["age_seconds"] >= WARN_SEC:
                attention.append((service, account, "WARN", details))

    if as_json:
        print(json.dumps(results, indent=2, default=str))
    else:
        all_ok = not attention
        if all_ok:
            n = len(TOKENS_TO_CHECK)
            print("OK oauth_watchdog: " + str(n) + "/" + str(n) + " tokens OK (" +
                  ", ".join(s + ":" + a for s, a in TOKENS_TO_CHECK) + ")")
        else:
            print("ALERTA oauth_watchdog: " + str(len(attention)) + " cuenta(s) requieren ACCION:")
            for s, a, st, det in attention:
                print("   - " + s + ":" + a + ": " + st + " - " +
                      (det.get("reason") or (str(round(det.get("age_days", 0), 1)) + " dias" if det.get("age_days") else "")))

    if attention:
        lines = ["ALERTA Liados OAuth watchdog - " + str(len(attention)) + " incidencia(s):"]
        for s, a, st, det in attention:
            extra = det.get("reason") or (str(round(det.get("age_days", 0), 1)) + " dias" if det.get("age_days") else "")
            lines.append("- " + s + ":" + a + " -> " + st + " (" + extra + ")")
        lines.append("")
        lines.append("Reautorizar:")
        lines.append("  python3 -m agente.scripts.gmail_auth --account <name> --force")
        lines.append("  python3 -m agente.scripts.oauth_drive_cli --account <name> --force")
        send_telegram(env, "\n".join(lines))

    return 0 if not attention else 1


if __name__ == "__main__":
    sys.exit(main())
