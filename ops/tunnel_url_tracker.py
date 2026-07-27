#!/usr/bin/env python3
"""
tunnel_url_tracker.py — Persiste la URL actual del tunnel quick-tunnel y notifica
si cambia.

Uso:
    python -m ops.tunnel_url_tracker          # actualiza y notifica
    python -m ops.tunnel_url_tracker --quiet  # solo log
"""
import os
import re
import sys
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tunnel_url_tracker")

LOG = Path("/var/log/liados/cloudflared.log")
STATE = Path("/root/liados/data/.current_tunnel_url")
HEALTH_TIMEOUT = 10


def extract_url() -> str | None:
    if not LOG.exists():
        return None
    text = LOG.read_text(errors="ignore")
    matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
    return matches[-1] if matches else None


def load_state() -> dict | None:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            return None
    return None


def save_state(url: str, healthy: bool):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "url": url,
        "healthy": healthy,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }, indent=2))


def notify(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.debug("Telegram no configurado, skip notify")
        return
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode(),
        )
        urllib.request.urlopen(req, timeout=10).read()
        logger.info("Telegram notificado")
    except Exception as e:
        logger.warning(f"Telegram fallo (no critico): {e}")


def main():
    quiet = "--quiet" in sys.argv
    url = extract_url()
    if not url:
        logger.warning("No se encontro URL en cloudflared.log")
        return 1

    prev = load_state()
    prev_url = prev.get("url") if prev else None

    if url != prev_url:
        msg = f"🔗 Liados tunnel URL NUEVA\n{url}\n(anterior: {prev_url or 'ninguna'})"
        logger.info(f"URL cambio: {prev_url} -> {url}")
        if not quiet:
            notify(msg)
        save_state(url, healthy=False)
    else:
        logger.info(f"URL estable: {url}")

    print(f"URL={url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())