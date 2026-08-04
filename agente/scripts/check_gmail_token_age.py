#!/usr/bin/env python3
"""Watchdog de edad de tokens OAuth Gmail.

Modos via OAUTH_APP_MODE (env):
  - testing    (default): WARN 5d, CRITICAL 6d
  - production          : WARN 90d, CRITICAL 180d

Exit codes: 0 OK, 1 WARN, 2 CRITICAL/MISSING.

capa 2 hardening 2026-07-17: cablea send_telegram() para avisar al jefe
cuando un token entra en WARN/CRITICAL/MISSING. Antes solo escribia al log.
"""
import json, os, sys
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

CREDS = Path(__file__).resolve().parents[2] / "agente" / "credentials"
UMBRALES = {
    "testing":    (5*24*3600,   6*24*3600),
    "production": (90*24*3600, 180*24*3600),
}
ACCOUNTS = ("principal", "secundaria")
WORKSPACE = Path("/root/liados")
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def load_env():
    env = {}
    env_file = WORKSPACE / ".env"
    if not env_file.exists():
        return env
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def send_telegram(env, message):
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    url = TELEGRAM_API.format(token=token, method="sendMessage")
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
    }).encode()
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return bool(body.get("ok"))
    except Exception as e:
        print(f"[WARN] telegram notify falló (no crítico): {e}", file=sys.stderr)
        return False


def age_seconds(token_path: Path):
    if not token_path.exists():
        return None
    try:
        tok = json.loads(token_path.read_text())
        raw = tok.get("issued_at") or tok.get("created_at")
        if not raw:
            return None
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def main():
    mode = os.getenv("OAUTH_APP_MODE", "production").lower()
    if mode not in UMBRALES:
        print(f"[ERROR] OAUTH_APP_MODE={mode!r} no soportado (testing|production)", file=sys.stderr)
        return 2
    warn_s, crit_s = UMBRALES[mode]
    rc = 0
    print(f"== Watchdog Gmail OAuth - modo {mode.upper()} - {datetime.now(timezone.utc).isoformat()} ==")
    alerts = []
    for acc in ACCOUNTS:
        tp = CREDS / f"gmail_token_{acc}.json"
        age = age_seconds(tp)
        if age is None:
            print(f"[{acc:11s}] MISSING     - reautorizar urgentemente")
            alerts.append(f"• {acc}: MISSING — reautorizar urgentemente")
            rc = max(rc, 2)
            continue
        days = age / 86400
        if age >= crit_s:
            tag = "CRITICAL"
            rc = max(rc, 2)
        elif age >= warn_s:
            tag = "WARN"
            rc = max(rc, 1)
        else:
            tag = "OK"
        print(f"[{acc:11s}] {tag:8s}  {days:5.1f}d   ({tp})")
        if tag == "WARN":
            alerts.append(f"• {acc}: WARN ({days:.1f}d) — expira pronto, reautoriza esta semana")
        elif tag == "CRITICAL":
            alerts.append(f"• {acc}: CRITICAL ({days:.1f}d) — reautorizar HOY")

    # Notificar SOLO si hay WARN/CRITICAL/MISSING (rc > 0)
    if alerts:
        env = load_env()
        msg = f"⚠️ Liados Gmail token age (modo {mode}):\n" + "\n".join(alerts) + \
              "\n\nReautorizar: python3 -m agente.scripts.gmail_auth --account <cuenta> --force"
        send_telegram(env, msg)

    return rc


if __name__ == "__main__":
    sys.exit(main())
