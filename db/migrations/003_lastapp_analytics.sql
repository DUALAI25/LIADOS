-- Migracion 003: tablas para analytics de Last.app
-- Idempotente: seguro de ejecutar multiples veces

BEGIN;

CREATE TABLE IF NOT EXISTS lastapp_bills (
    id UUID PRIMARY KEY,
    number TEXT,
    creation_time TIMESTAMPTZ NOT NULL,
    finalizing_time TIMESTAMPTZ,
    total_cents INTEGER NOT NULL DEFAULT 0,
    tax_cents INTEGER NOT NULL DEFAULT 0,
    taxable_base_cents INTEGER NOT NULL DEFAULT 0,
    tax_percentage INTEGER NOT NULL DEFAULT 0,
    delivery_fee_cents INTEGER NOT NULL DEFAULT 0,
    minimum_basket_surcharge_cents INTEGER NOT NULL DEFAULT 0,
    terrace_surcharge_cents INTEGER NOT NULL DEFAULT 0,
    discount_total_cents INTEGER NOT NULL DEFAULT 0,
    company_name TEXT,
    company_tax_id TEXT,
    company_address TEXT,
    customer_name TEXT,
    customer_tax_id TEXT,
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    location_id UUID,
    organization_id UUID,
    raw_json JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bills_creation_time ON lastapp_bills(creation_time);
CREATE INDEX IF NOT EXISTS idx_bills_number ON lastapp_bills(number);
CREATE INDEX IF NOT EXISTS idx_bills_total ON lastapp_bills(total_cents);
CREATE INDEX IF NOT EXISTS idx_bills_deleted ON lastapp_bills(deleted) WHERE deleted = FALSE;

CREATE TABLE IF NOT EXISTS lastapp_payments (
    id UUID PRIMARY KEY,
    bill_id UUID REFERENCES lastapp_bills(id) ON DELETE CASCADE,
    type TEXT,
    amount_cents INTEGER NOT NULL DEFAULT 0,
    tip_cents INTEGER NOT NULL DEFAULT 0,
    creation_time TIMESTAMPTZ NOT NULL,
    user_id UUID,
    till_id UUID,
    external_id TEXT,
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    raw_json JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_bill_id ON lastapp_payments(bill_id);
CREATE INDEX IF NOT EXISTS idx_payments_type ON lastapp_payments(type);
CREATE INDEX IF NOT EXISTS idx_payments_creation_time ON lastapp_payments(creation_time);

CREATE TABLE IF NOT EXISTS lastapp_customers (
    id UUID PRIMARY KEY,
    organization_id UUID,
    name TEXT,
    surname TEXT,
    phone_number TEXT,
    creation_time TIMESTAMPTZ NOT NULL,
    update_time TIMESTAMPTZ,
    source TEXT,
    external_id TEXT,
    raw_json JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_source ON lastapp_customers(source);
CREATE INDEX IF NOT EXISTS idx_customers_creation_time ON lastapp_customers(creation_time);

CREATE TABLE IF NOT EXISTS lastapp_analytics_cache (
    metric TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
