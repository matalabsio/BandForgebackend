-- Phase 4A: mock_tests.exam_module taxonomy (nullable, no backfill).
--
-- NULL semantics: unclassified / not yet tagged. Runtime mock selection
-- (FSP + Writing Skill) must NOT consume this column until a later phase.
-- Full IELTS mocks include L/R/W/S; this field classifies the Writing track
-- of the mock for future selection, not Listening/Reading/Speaking content.
--
-- Do NOT bulk-retag existing mocks. Explicit admin tagging only.

ALTER TABLE mock_tests
  ADD COLUMN IF NOT EXISTS exam_module text;

ALTER TABLE mock_tests
  DROP CONSTRAINT IF EXISTS mock_tests_exam_module_check;

ALTER TABLE mock_tests
  ADD CONSTRAINT mock_tests_exam_module_check
  CHECK (
    exam_module IS NULL
    OR exam_module IN ('academic', 'general_training', 'both')
  );

COMMENT ON COLUMN mock_tests.exam_module IS
  'Writing-track taxonomy for the mock: academic | general_training | both. '
  'NULL = unclassified (backward compatible). both = valid for either Writing module. '
  'Inert for runtime selection until a later phase wires consumers.';

CREATE INDEX IF NOT EXISTS idx_mock_tests_exam_module_status
  ON mock_tests (exam_module, status)
  WHERE exam_module IS NOT NULL;
