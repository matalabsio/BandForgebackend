-- Admin-configurable free/paid mock access.

ALTER TABLE mock_tests
  ADD COLUMN IF NOT EXISTS is_free boolean NOT NULL DEFAULT false;

-- Diagnostic (and any is_diagnostic row) is free; catalog mocks stay paid.
UPDATE mock_tests
   SET is_free = true
 WHERE is_diagnostic = true
    OR id = 'd0000000-0000-4000-8000-000000000001';
