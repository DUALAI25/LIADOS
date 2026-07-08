-- Migracion 005: reparar facturas de Last.app sin location_id (sin-local).
--
-- Contexto (triage 2026-07-08):
--   El sync de Last.app dejo de popular `location_id` a partir del 2026-06-17.
--   Las 786 facturas afectadas pertenecen TODAS a la misma empresa
--   "Vamos al lío S.L." (company.name), unico local operativo del cliente.
--   El location_id valido historico es a8f15efa-8455-4e88-9643-7aab527a2523
--   (7971 facturas hasta el 2026-06-16).
--
-- Estrategia: asignar el location_id conocido a las facturas que cumplan:
--   1. location_id IS NULL
--   2. deleted = false
--   3. company->>'name' = 'Vamos al lío S.L.' (matches el local valido)
--
-- Es idempotente: re-ejecutar no cambia nada una vez asignado.
-- Es conservadora: solo asigna el local cuando hay coincidencia exacta de
-- company.name. Si en el futuro hay >1 local, esta migracion no los mezcla.
--
-- Verificacion pre-migracion:
--   SELECT count(*) FROM lastapp_bills
--   WHERE location_id IS NULL AND deleted = false
--     AND raw_json->'company'->>'name' = 'Vamos al lío S.L.';
--   -- esperado: 786

BEGIN;

-- 1. Backup defensivo: snapshot de los IDs afectados (para auditoria/rollback).
CREATE TABLE IF NOT EXISTS _migration_005_audit (
    bill_id UUID PRIMARY KEY,
    location_id_old UUID,
    location_id_new UUID,
    fixed_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO _migration_005_audit (bill_id, location_id_old, location_id_new)
SELECT id, NULL, 'a8f15efa-8455-4e88-9643-7aab527a2523'::uuid
FROM lastapp_bills
WHERE location_id IS NULL
  AND deleted = false
  AND raw_json->'company'->>'name' = 'Vamos al lío S.L.'
ON CONFLICT (bill_id) DO NOTHING;

-- 2. Asignar el location_id conocido a las facturas huérfanas del local conocido.
UPDATE lastapp_bills
SET location_id = 'a8f15efa-8455-4e88-9643-7aab527a2523'::uuid
WHERE location_id IS NULL
  AND deleted = false
  AND raw_json->'company'->>'name' = 'Vamos al lío S.L.';

-- 3. Indice compuesto para los endpoints nuevos de gastos (Entregable D1).
--    Acelera los filtros tipo+status+fecha+vendor usados en /api/gastos.
CREATE INDEX IF NOT EXISTS idx_invoices_expense_filters
ON invoices (invoice_date DESC, vendor_name)
WHERE type = 'expense' AND status != 'rejected' AND is_invoice = true;

CREATE INDEX IF NOT EXISTS idx_invoices_vendor_lower
ON invoices (lower(vendor_name) varchar_pattern_ops)
WHERE type = 'expense' AND is_invoice = true;

COMMIT;

-- Verificacion post-migracion:
--   SELECT count(*) FROM lastapp_bills
--   WHERE location_id IS NULL AND deleted = false;  -- esperado: 0
