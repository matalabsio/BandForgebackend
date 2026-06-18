-- Catalog slot + section counts for admin-created full mocks (Test 1, 2, 3…)

ALTER TABLE mock_tests
  ADD COLUMN IF NOT EXISTS catalog_number integer;

ALTER TABLE mock_tests
  ADD COLUMN IF NOT EXISTS listening_parts integer NOT NULL DEFAULT 4;

ALTER TABLE mock_tests
  ADD COLUMN IF NOT EXISTS reading_passages integer NOT NULL DEFAULT 3;

ALTER TABLE mock_tests
  ADD COLUMN IF NOT EXISTS writing_tasks integer NOT NULL DEFAULT 2;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mock_tests_catalog_number_unique
  ON mock_tests (catalog_number)
  WHERE catalog_number IS NOT NULL;

-- Backfill live mocks
UPDATE mock_tests
SET
  catalog_number = 1,
  listening_parts = 4,
  reading_passages = 2,
  writing_tasks = 2
WHERE id = 'a0000000-0000-4000-8000-000000000001'
  AND catalog_number IS NULL;

UPDATE mock_tests
SET
  catalog_number = 2,
  listening_parts = 4,
  reading_passages = 3,
  writing_tasks = 2
WHERE id = 'a0000000-0000-4000-8000-000000000002'
  AND catalog_number IS NULL;
