CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    icon TEXT,
    color TEXT DEFAULT '#6B7280',
    parent_id UUID REFERENCES categories(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO categories (name, icon, color) VALUES
    ('Software y SaaS', null, '#3B82F6'),
    ('Oficina', null, '#10B981'),
    ('Viajes y Transporte', null, '#F59E0B'),
    ('Marketing y Publicidad', null, '#EF4444'),
    ('Servicios Profesionales', null, '#8B5CF6'),
    ('Suministros', null, '#06B6D4'),
    ('Seguros', null, '#6366F1'),
    ('Alquiler', null, '#EC4899'),
    ('Telecomunicaciones', null, '#14B8A6'),
    ('Gastos Bancarios', null, '#F97316'),
    ('Impuestos y Tasas', null, '#78716C'),
    ('Restauración y Hostelería', null, '#EAB308'),
    ('Otros', null, '#A8A29E');

CREATE TABLE vendors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    tax_id TEXT,
    email TEXT,
    phone TEXT,
    default_category_id UUID REFERENCES categories(id),
    is_active BOOLEAN DEFAULT true,
    total_invoices INTEGER DEFAULT 0,
    total_spent DECIMAL(14,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, tax_id)
);

CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type TEXT NOT NULL DEFAULT 'expense' CHECK (type IN ('income', 'expense')),
    source TEXT NOT NULL CHECK (source IN ('erp', 'gmail', 'manual')),
    source_id TEXT,
    content_hash TEXT,
    invoice_number TEXT,
    invoice_date DATE,
    due_date DATE,
    vendor_id UUID REFERENCES vendors(id),
    vendor_name TEXT,
    vendor_tax_id TEXT,
    base_amount DECIMAL(14,2),
    tax_amount DECIMAL(14,2),
    total_amount DECIMAL(14,2),
    currency TEXT DEFAULT 'EUR',
    category_id UUID REFERENCES categories(id),
    category_raw TEXT,
    description TEXT,
    tags TEXT[],
    raw_file_url TEXT,
    parsed_json JSONB,
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'classified', 'verified', 'paid', 'rejected', 'duplicate'
    )),
    confidence_score DECIMAL(3,2) DEFAULT 0.00,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    verified_by TEXT,
    verified_at TIMESTAMPTZ,
    UNIQUE(source, source_id)
);

CREATE INDEX idx_invoices_type ON invoices(type);
CREATE INDEX idx_invoices_date ON invoices(invoice_date);
CREATE INDEX idx_invoices_vendor ON invoices(vendor_id);
CREATE INDEX idx_invoices_category ON invoices(category_id);
CREATE INDEX idx_invoices_status ON invoices(status);
CREATE INDEX idx_invoices_source ON invoices(source);
CREATE INDEX idx_invoices_hash ON invoices(content_hash);
CREATE INDEX idx_invoices_created ON invoices(created_at DESC);

CREATE INDEX idx_invoices_search ON invoices USING gin(
    to_tsvector('spanish',
        coalesce(vendor_name, '') || ' ' ||
        coalesce(description, '') || ' ' ||
        coalesce(invoice_number, '')
    )
);

CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID NOT NULL REFERENCES invoices(id),
    payment_date DATE,
    amount DECIMAL(14,2),
    source TEXT,
    source_detail TEXT,
    reference TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(invoice_id, source, amount, payment_date)
);

CREATE INDEX idx_payments_invoice ON payments(invoice_id);
CREATE INDEX idx_payments_date ON payments(payment_date);

CREATE TABLE sync_control (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source TEXT NOT NULL CHECK (source IN ('erp', 'gmail')),
    last_sync TIMESTAMPTZ DEFAULT NOW(),
    items_processed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ok' CHECK (status IN ('ok', 'warning', 'error'))
);

INSERT INTO sync_control (source) VALUES ('erp'), ('gmail');

CREATE TABLE user_overrides (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID REFERENCES invoices(id),
    original_category_id UUID REFERENCES categories(id),
    corrected_category_id UUID REFERENCES categories(id),
    vendor_id UUID REFERENCES vendors(id),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_overrides_vendor ON user_overrides(vendor_id);
CREATE INDEX idx_overrides_category ON user_overrides(corrected_category_id);

CREATE TABLE agent_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    source TEXT NOT NULL,
    level TEXT CHECK (level IN ('info', 'warning', 'error')),
    message TEXT,
    details JSONB
);

CREATE INDEX idx_logs_timestamp ON agent_logs(timestamp DESC);
CREATE INDEX idx_logs_level ON agent_logs(level);

CREATE VIEW monthly_expenses AS
SELECT
    DATE_TRUNC('month', invoice_date) AS month,
    type,
    COUNT(*) AS invoice_count,
    SUM(total_amount) AS total_amount
FROM invoices
WHERE status NOT IN ('duplicate', 'rejected')
GROUP BY DATE_TRUNC('month', invoice_date), type
ORDER BY month DESC;

CREATE VIEW expenses_by_category AS
SELECT
    c.name AS category_name,
    c.icon AS category_icon,
    c.color AS category_color,
    COUNT(i.id) AS invoice_count,
    SUM(i.total_amount) AS total_amount,
    MIN(i.invoice_date) AS first_invoice,
    MAX(i.invoice_date) AS last_invoice
FROM invoices i
JOIN categories c ON i.category_id = c.id
WHERE i.status NOT IN ('duplicate', 'rejected') AND i.type = 'expense'
GROUP BY c.id, c.name, c.icon, c.color
ORDER BY total_amount DESC;

CREATE VIEW income_by_source AS
SELECT
    source,
    COUNT(*) AS invoice_count,
    SUM(total_amount) AS total_amount,
    SUM(tax_amount) AS total_tax
FROM invoices
WHERE status NOT IN ('duplicate', 'rejected') AND type = 'income'
GROUP BY source
ORDER BY total_amount DESC;

CREATE VIEW monthly_net AS
SELECT
    month,
    SUM(CASE WHEN type = 'income' THEN total_amount ELSE 0 END) AS income,
    SUM(CASE WHEN type = 'expense' THEN total_amount ELSE 0 END) AS expense,
    SUM(CASE WHEN type = 'income' THEN total_amount ELSE -total_amount END) AS net
FROM monthly_expenses
GROUP BY month
ORDER BY month DESC;

CREATE OR REPLACE FUNCTION update_vendor_stats()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE vendors SET
        total_invoices = (
            SELECT COUNT(*) FROM invoices
            WHERE vendor_id = NEW.vendor_id
            AND status NOT IN ('duplicate', 'rejected')
        ),
        total_spent = (
            SELECT COALESCE(SUM(total_amount), 0) FROM invoices
            WHERE vendor_id = NEW.vendor_id
            AND status NOT IN ('duplicate', 'rejected')
        )
    WHERE id = NEW.vendor_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_vendor_stats
AFTER INSERT OR UPDATE OF status, vendor_id ON invoices
FOR EACH ROW
EXECUTE FUNCTION update_vendor_stats();
