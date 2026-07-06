-- Migration: amplify sync_control.source CHECK constraint to allow per-account
-- sources for Gmail accounts.
--
-- BEFORE: source IN ('erp', 'gmail')
-- AFTER:  source IN ('erp', 'gmail:principal', 'gmail:secundaria')
--
-- Reason: B1 (Bloque 1) of the Gmail-collector per-account refactor.
--   - Each Gmail account gets its own sync_control row (gmail:<account>).
--   - A missing/revoked token on one account no longer poisons the global
--     state of the other.
--
-- Run with: psql $DB -f ops/migrations/2026_07_06_b1_sync_per_account.sql
-- (Or via the apply_sync_per_account_migration.py helper in this directory.)

BEGIN;

-- 1. Drop the old constraint. Done first (in autocommit mode) so the
--    following UPDATE does not fail the transaction when migrating the
--    legacy 'gmail' row.
ALTER TABLE sync_control DROP CONSTRAINT IF EXISTS sync_control_source_check;

-- 2. Migrate the legacy row (if any). Old 'gmail' rows correspond to the
--    principal account in practice.
UPDATE sync_control
   SET source = 'gmail:principal'
 WHERE source = 'gmail';

-- 3. Re-add the constraint with the broader enum.
ALTER TABLE sync_control ADD CONSTRAINT sync_control_source_check
  CHECK (source = ANY (ARRAY[
    'erp'::text,
    'gmail:principal'::text,
    'gmail:secundaria'::text
  ]));

-- 4. Sanity view.
SELECT source, last_sync, status FROM sync_control ORDER BY source;

COMMIT;
