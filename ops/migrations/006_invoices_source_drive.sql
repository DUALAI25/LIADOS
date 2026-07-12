-- Migración 006: añadir 'drive' a invoices_source_check
ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_source_check;
ALTER TABLE invoices ADD CONSTRAINT invoices_source_check
    CHECK (source = ANY (ARRAY['erp'::text, 'gmail'::text, 'manual'::text, 'drive'::text]));