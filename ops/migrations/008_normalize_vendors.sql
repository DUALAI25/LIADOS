-- Normalizacion vendors VAMOS AL LIO y S V IMPASTO
-- Estrategia: actualizar invoices.vendor_id para apuntar al vendor canonico
-- vendor_name se mantiene como esta (auditoria)

BEGIN;

-- Vendor canonico: VAMOS AL LIO S.L. (el mas comun)
WITH canon AS (
    SELECT id FROM vendors WHERE name='VAMOS AL LIO S.L.' LIMIT 1
)
UPDATE invoices i SET vendor_id=(SELECT id FROM canon),
                      updated_at=NOW()
WHERE vendor_name IN (
    'VAMOS AL LIO SL',
    'VAMOS AL LIO, S.L.',
    'VAMOS AL LIO S.L',
    'VAMOS AL LÍO S.L.',
    'Vamos al Lio SL'
) AND vendor_id IS DISTINCT FROM (SELECT id FROM canon);

-- S V IMPASTO SL / S&V IMPASTO SLU -> vendor canonico si existe
WITH canon AS (
    SELECT id FROM vendors WHERE name ILIKE 'S V IMPASTO%' OR name ILIKE 'S&V IMPASTO%' LIMIT 1
)
UPDATE invoices i SET vendor_id=(SELECT id FROM canon),
                      updated_at=NOW()
WHERE vendor_name IN ('S V IMPASTO SL', 'S&V IMPASTO SLU')
  AND (SELECT id FROM canon) IS NOT NULL
  AND vendor_id IS DISTINCT FROM (SELECT id FROM canon);

COMMIT;