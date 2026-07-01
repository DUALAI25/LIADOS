-- 004_add_is_invoice.sql
-- Migración: añade columna is_invoice a la tabla invoices para activar el filtro P4
-- (commit f2371c5) que descarta adjuntos que NO son facturas reales.
--
-- Lógica:
--   - default true (las facturas INGESTADAS previamente se asume que SÍ son facturas;
--     sólo el gmail_collector escribe false cuando el filtro las descarta).
--   - backfill explícito: cualquier fila sin fecha + sin importe + sin vendor se marca
--     is_invoice=false (heurística conservadora; restaimplica revisión manual).
--
-- Rollback:
--   ALTER TABLE invoices DROP COLUMN is_invoice;

BEGIN;

ALTER TABLE invoices
    ADD COLUMN IF NOT EXISTS is_invoice BOOLEAN NOT NULL DEFAULT true;

-- Backfill conservador: adjuntos sin datos útiles NO son facturas válidas.
-- (33 facturas: 17 sin vendor_name + extras sin fecha+importe)
UPDATE invoices
SET is_invoice = false
WHERE vendor_name IS NULL
   OR (invoice_date IS NULL AND total_amount IS NULL);

-- Índice para queries del dashboard y del parser.
CREATE INDEX IF NOT EXISTS idx_invoices_is_invoice
    ON invoices (is_invoice) WHERE is_invoice = true;

COMMIT;
