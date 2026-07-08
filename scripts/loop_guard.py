#!/usr/bin/env python3
"""loop_guard.py — Enforcement mecánico del límite de 3 intentos por item.

Lee `loop-ledger.json` (raíz del repo) y aplica las reglas definidas en
`loop-constraints.md`:
  - Max 3 fix attempts per item; escalate after that.

Uso (wrapper antes de cualquier L2 run):
  python3 scripts/loop_guard.py check <item_id>
    → exit 0 si el item aún tiene intentos disponibles
    → exit 1 si el item ya tiene 3+ intentos (escalación humana)

  python3 scripts/loop_guard.py log <item_id> <action> <result> [<hash>]
    action: implement | verify | fix | refactor
    result: ok | reject | retry
    → añade entrada al ledger

  python3 scripts/loop_guard.py reset <item_id>
    → borra el historial de un item (solo tras aprobación humana explícita)

  python3 scripts/loop_guard.py status
    → imprime el estado actual del ledger
"""
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

MAX_ATTEMPTS = 3
LEDGER_PATH = Path(__file__).resolve().parent.parent / "loop-ledger.json"


def _load():
    if not LEDGER_PATH.exists():
        return {"version": 1, "created_at": _now(), "attempts": {}}
    with open(LEDGER_PATH) as f:
        return json.load(f)


def _save(data):
    LEDGER_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check(item_id):
    data = _load()
    n = len(data["attempts"].get(item_id, []))
    if n >= MAX_ATTEMPTS:
        print(f"BLOCK: '{item_id}' tiene {n} intentos (máx {MAX_ATTEMPTS}). Escalar a humano.")
        print("Para resetear tras revisión: python3 scripts/loop_guard.py reset " + item_id)
        return 1
    print(f"OK: '{item_id}' tiene {n}/{MAX_ATTEMPTS} intentos. Puede continuar.")
    return 0


def log(item_id, action, result, entry_hash=""):
    if action not in {"implement", "verify", "fix", "refactor"}:
        print(f"ERROR: action inválido '{action}'", file=sys.stderr)
        return 2
    if result not in {"ok", "reject", "retry"}:
        print(f"ERROR: result inválido '{result}'", file=sys.stderr)
        return 2
    data = _load()
    data["attempts"].setdefault(item_id, []).append({
        "ts": _now(),
        "action": action,
        "result": result,
        "hash": entry_hash[:12],
    })
    _save(data)
    print(f"LOGGED: {item_id} {action}={result} (total: {len(data['attempts'][item_id])})")
    return 0


def reset(item_id):
    data = _load()
    if item_id in data["attempts"]:
        n = len(data["attempts"].pop(item_id))
        _save(data)
        print(f"RESET: '{item_id}' borrado ({n} entradas eliminadas). Requiere aprobación humana.")
    else:
        print(f"NOOP: '{item_id}' no tenía entradas.")
    return 0


def status():
    data = _load()
    items = data.get("attempts", {})
    if not items:
        print("Ledger vacío. Sin intentos registrados.")
        return 0
    print(f"{'item':<40} {'intentos':<10} {'último':<10} {'estado'}")
    print("-" * 80)
    for item_id, entries in sorted(items.items()):
        n = len(entries)
        last = entries[-1] if entries else {}
        estado = "BLOCKED" if n >= MAX_ATTEMPTS else "ok"
        print(f"{item_id:<40} {n:<10} {last.get('result', '-'):<10} {estado}")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "check" and len(sys.argv) == 3:
        return check(sys.argv[2])
    if cmd == "log" and len(sys.argv) >= 5:
        return log(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "")
    if cmd == "reset" and len(sys.argv) == 3:
        return reset(sys.argv[2])
    if cmd == "status":
        return status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
