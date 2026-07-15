-- Migracion 007: Tabla invoice_corrections (auditoria de reclasificacion)
-- Idempotente: seguro de ejecutar multiples veces.

BEGIN;

CREATE TABLE IF NOT EXISTS invoice_corrections (
    id BIGSERIAL PRIMARY KEY,
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    before_json JSONB NOT NULL,
    after_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoice_corrections_invoice
ON invoice_corrections (invoice_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_corrections_user
ON invoice_corrections (user_id, created_at DESC);

-- Permitir que sync_control acepte claves "drive:*" (rollback conservador por si se reintroduce)
-- Esto es idempotente: solo actua si el constraint existe.
DO $$
BEGIN
    -- Solo intentamos si la tabla existe
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sync_control') THEN
        -- Si el constraint CHECK existe y es muy restrictivo, lo extendemos.
        -- Postgres no permite ALTER CHECK directamente; lo recreamos si es necesario.
        BEGIN
            ALTER TABLE sync_control DROP CONSTRAINT IF EXISTS sync_control_source_check;
            ALTER TABLE sync_control ADD CONSTRAINT sync_control_source_check
                CHECK (source IN ('erp','gmail') OR source LIKE 'drive:%');
        EXCEPTION WHEN OTHERS THEN
            -- Si falla (p.ej. constraint no existe con ese nombre), ignorar
            RAISE NOTICE 'No se pudo actualizar constraint de sync_control: %', SQLERRM;
        END;
    END IF;
END $$;

COMMIT;

-- Verificacion:
--   \d+ invoice_corrections
--   \d+ sync_control (constraints)
