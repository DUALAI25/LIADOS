"""Test del fix de is_duplicate_by_hash (2026-06-22)."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/root/liados/.env')

sys.path.insert(0, 'agente/scripts')
from dedup_checker import is_duplicate_by_hash
from db_connection import get_conn

# Sacar 3 hashes reales con su source_id
conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT id, content_hash, source_id FROM invoices WHERE source='gmail' AND status='classified' LIMIT 3")
rows = cur.fetchall()
conn.close()

print(f"Probando con {len(rows)} facturas reales:\n")
for inv_id, h, sid in rows:
    # Caso A: mismo source_id -> NO es duplicado (somos nosotros re-procesando)
    res_a = is_duplicate_by_hash(h, current_source_id=sid)
    # Caso B: source_id DIFERENTE -> SI es duplicado (es OTRO email con mismo adjunto)
    res_b = is_duplicate_by_hash(h, current_source_id="fake:otro")
    # Caso C: sin source_id (compatibilidad) -> SI es duplicado (comportamiento legacy)
    res_c = is_duplicate_by_hash(h)

    print(f"ID={inv_id}  hash={h[:12]}...  source_id={sid}")
    print(f"  mismo source_id   -> {res_a}  (esperado: False)  {'OK' if not res_a else 'FALLO'}")
    print(f"  source_id fake    -> {res_b}  (esperado: True)   {'OK' if res_b else 'FALLO'}")
    print(f"  sin source_id     -> {res_c}  (esperado: True)   {'OK' if res_c else 'FALLO'}")
    print()
