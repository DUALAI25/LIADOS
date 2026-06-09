-- =====================================================
-- Migration 002: Tabla orphan_payments para pagos huérfanos
-- Fecha: 2026-06-09
-- Motivo: pagos de Last.app sin factura emparejada (llegan
--         con invoiceNumber que no siempre está en invoices)
-- =====================================================

CREATE TABLE orphan_payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source TEXT NOT NULL,
    source_payment_id TEXT,
    invoice_number TEXT,
    payment_date DATE,
    amount DECIMAL(14,2),
    method TEXT,
    source_detail TEXT,
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source, source_payment_id)
);

CREATE INDEX idx_orphan_payments_invoice_number
    ON orphan_payments(invoice_number);

COMMENT ON TABLE orphan_payments IS 'Pagos de Last.app cuyo invoice_number no coincide con ninguna factura en invoices. Revisión manual requerida.';
