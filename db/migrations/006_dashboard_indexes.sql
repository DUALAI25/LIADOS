-- Migracion 006: indices para queries frecuentes de dashboard v7.1 PRO
-- Idempotente: seguro de ejecutar multiples veces.

BEGIN;

-- Indice parcial para /api/kpis, /api/gastos*, /api/alertas
-- Acelera: WHERE type='expense' AND status NOT IN (...) AND is_invoice=true
--          ORDER BY invoice_date DESC (todas las queries frecuentes)
CREATE INDEX IF NOT EXISTS idx_invoices_expense_recent
ON invoices (invoice_date DESC)
WHERE type = 'expense' AND status NOT IN ('rejected','duplicate') AND is_invoice = true;

-- Indice para vendor_name case-insensitive (búsquedas ILIKE)
CREATE INDEX IF NOT EXISTS idx_invoices_vendor_ilike
ON invoices (lower(vendor_name) varchar_pattern_ops)
WHERE type = 'expense' AND is_invoice = true;

-- Indice compuesto para /api/gastos (status + fecha)
CREATE INDEX IF NOT EXISTS idx_invoices_status_date
ON invoices (status, invoice_date DESC)
WHERE type = 'expense' AND is_invoice = true;

-- Indice para los JOIN de /api/gastos/desglose (LEFT JOIN categories)
-- Solo cuando category_id IS NOT NULL (la mayoria)
CREATE INDEX IF NOT EXISTS idx_invoices_category_fk
ON invoices (category_id)
WHERE category_id IS NOT NULL AND type = 'expense';

-- Indice en lastapp_bills(location_id) para /api/locales y /api/ventas-por-local
CREATE INDEX IF NOT EXISTS idx_bills_location_active
ON lastapp_bills (location_id)
WHERE deleted = false;

-- Indice para /api/canal-por-mes (bills + payments join)
CREATE INDEX IF NOT EXISTS idx_payments_bill_type
ON lastapp_payments (bill_id, type)
WHERE deleted = false;

-- NOTA: idx_invoices_search_gin ya existe como idx_invoices_search (schema.sql)
-- Duplicado eliminaría rendimiento. Si necesitas uno nuevo, dropear el viejo primero.
-- DROP INDEX IF EXISTS idx_invoices_search;

COMMIT;

-- Verificacion post-migracion:
--   SELECT indexname FROM pg_indexes WHERE tablename = 'invoices' ORDER BY indexname;
--   SELECT indexname FROM pg_indexes WHERE tablename = 'lastapp_bills' ORDER BY indexname;
