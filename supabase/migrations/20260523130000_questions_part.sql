-- BandForge Listening — add IELTS Part (1..4) to questions
-- Idempotent: safe to re-run.
-- Part values mirror IELTS Listening structure:
--   1 = Social Dialogue (form/table completion)
--   2 = Social Monologue (map labels / MCQ)
--   3 = Academic Seminar (MCQ / matching)
--   4 = Academic Lecture (note / summary completion)

ALTER TABLE questions
  ADD COLUMN IF NOT EXISTS part smallint;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'questions_part_check'
  ) THEN
    ALTER TABLE questions
      ADD CONSTRAINT questions_part_check
      CHECK (part IS NULL OR (part BETWEEN 1 AND 4));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_questions_mock_module_part
  ON questions (mock_test_id, module, part, question_number);

COMMENT ON COLUMN questions.part IS
  'IELTS Listening section (1-4). NULL for non-listening modules.';
