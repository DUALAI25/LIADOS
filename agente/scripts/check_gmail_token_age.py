#!/usr/bin/env python3
"""Watchdog de edad de tokens OAuth Gmail.

Modos via OAUTH_APP_MODE (env):
  - testing    (default): WARN 5d, CRITICAL 6d
  - production          : WARN 90d, CRITICAL 180d

Exit codes: 0 OK, 1 WARN, 2 CRITICAL/MISSING.
"""
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone

CREDS = Path(__file__).resolve().parents[2] / "agente" / "credentials"
UMBRALES = {
    "testing":    (5*24*3600,   6*24*3600),
    "production": (90*24*3600, 180*24*3600),
}
ACCOUNTS = ("principal", "secundaria")


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
    mode = os.getenv("OAUTH_APP_MODE", "testing").lower()
    if mode not in UMBRALES:
        print(f"[ERROR] OAUTH_APP_MODE={mode!r} no soportado (testing|production)", file=sys.stderr)
        return 2
    warn_s, crit_s = UMBRALES[mode]
    rc = 0
    print(f"== Watchdog Gmail OAuth - modo {mode.upper()} - {datetime.now(timezone.utc).isoformat()} ==")
    for acc in ACCOUNTS:
        tp = CREDS / f"gmail_token_{acc}.json"
        age = age_seconds(tp)
        if age is None:
            print(f"[{acc:11s}] MISSING     - reautorizar urgentemente")
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
    return rc


if __name__ == "__main__":
    sys.exit(main())
