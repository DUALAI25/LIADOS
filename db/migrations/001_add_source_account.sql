-- =====================================================
-- Migration 001: Añadir source_account a invoices
-- Fecha: 2026-06-08
-- Motivo: soporte multi-cuenta Gmail (Liados tiene 2)
-- =====================================================

-- Añadir columna (NULL permitida para registros viejos / lastapp)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS source_account TEXT;

-- Índice para consultas por cuenta
CREATE INDEX IF NOT EXISTS idx_invoices_account ON invoices(source_account);

-- Comentario
COMMENT ON COLUMN invoices.source_account IS 'Cuenta de origen multi-cuenta (ej: principal, secundaria). NULL para lastapp o registros manuales.';
