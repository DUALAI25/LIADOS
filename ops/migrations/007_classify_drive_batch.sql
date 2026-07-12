-- Clasificacion facturas Drive (15 facturas nuevas) - script corregido v2
-- Esquema real: before_json / after_json (jsonb), user_id NOT NULL, no hay before/after_category

BEGIN;

-- 1) PORTIER EATS x8 -> Marketing y Publicidad
WITH portier_ids AS (
    SELECT id FROM invoices
    WHERE source='drive' AND vendor_name LIKE 'PORTIER EATS%'
)
INSERT INTO invoice_corrections (invoice_id, user_id, reason, before_json, after_json)
SELECT p.id,
       'jarvis',
       'PORTIER EATS comision delivery Glovo/UberEats (drive batch 2026-07-12)',
       jsonb_build_object('category_id', i.category_id, 'is_invoice', i.is_invoice, 'status', i.status),
       jsonb_build_object('category_id', (SELECT id FROM categories WHERE name='Marketing y Publicidad'), 'is_invoice', true, 'status', 'classified')
FROM portier_ids p JOIN invoices i ON i.id=p.id;

UPDATE invoices SET category_id=(SELECT id FROM categories WHERE name='Marketing y Publicidad'),
                    status='classified', updated_at=NOW()
WHERE source='drive' AND vendor_name LIKE 'PORTIER EATS%';

-- 2) Proveedores equipamiento -> Suministros
WITH prov_ids AS (
    SELECT id FROM invoices
    WHERE source='drive'
      AND vendor_name IN ('PVC RUBÍ, S.L.', 'Ibergastro',
                          'MAQUINARIA Y EQUIPAMIENTOS GALICIA, SL',
                          'Rocket Tools GmbH', 'VAMOS AL LIO SL', 'VALENVEN S.L.U.')
)
INSERT INTO invoice_corrections (invoice_id, user_id, reason, before_json, after_json)
SELECT p.id,
       'jarvis',
       'Equipamiento hosteleria (inversion restaurante, drive batch 2026-07-12)',
       jsonb_build_object('category_id', i.category_id, 'is_invoice', i.is_invoice, 'status', i.status),
       jsonb_build_object('category_id', (SELECT id FROM categories WHERE name='Suministros'), 'is_invoice', true, 'status', 'classified')
FROM prov_ids p JOIN invoices i ON i.id=p.id;

UPDATE invoices SET category_id=(SELECT id FROM categories WHERE name='Suministros'),
                    status='classified', updated_at=NOW()
WHERE source='drive'
  AND vendor_name IN ('PVC RUBÍ, S.L.', 'Ibergastro',
                      'MAQUINARIA Y EQUIPAMIENTOS GALICIA, SL',
                      'Rocket Tools GmbH', 'VAMOS AL LIO SL', 'VALENVEN S.L.U.');

-- 3) Vendor vacio + conf 0.5 -> is_invoice=false (auto-reject)
WITH vacias AS (
    SELECT id FROM invoices
    WHERE source='drive' AND (vendor_name IS NULL OR vendor_name='')
      AND confidence_score <= 0.6 AND is_invoice=true
)
INSERT INTO invoice_corrections (invoice_id, user_id, reason, before_json, after_json)
SELECT v.id,
       'jarvis',
       'Auto-reject: vendor vacio + confidence 0.5 (drive batch 2026-07-12)',
       jsonb_build_object('category_id', i.category_id, 'is_invoice', i.is_invoice, 'status', i.status),
       jsonb_build_object('category_id', i.category_id, 'is_invoice', false, 'status', 'rejected')
FROM vacias v JOIN invoices i ON i.id=v.id;

UPDATE invoices SET is_invoice=false, status='rejected', updated_at=NOW()
WHERE source='drive' AND (vendor_name IS NULL OR vendor_name='')
  AND confidence_score <= 0.6 AND is_invoice=true;

COMMIT;