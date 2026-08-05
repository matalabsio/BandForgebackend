-- Phase 5: question-level difficulty for in-session easy→hard ordering
ALTER TABLE bank_questions
  ADD COLUMN IF NOT EXISTS difficulty text NOT NULL DEFAULT 'medium';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'bank_questions_difficulty_check'
  ) THEN
    ALTER TABLE bank_questions
      ADD CONSTRAINT bank_questions_difficulty_check
      CHECK (difficulty IN ('easy', 'medium', 'hard'));
  END IF;
END $$;

COMMENT ON COLUMN bank_questions.difficulty IS
  'In-session ordering band: easy → medium → hard (Phase 5)';

-- Heuristic backfill for Phase 0 / common types (idempotent-ish: only medium rows)
UPDATE bank_questions
SET difficulty = 'hard'
WHERE difficulty = 'medium'
  AND lower(coalesce(skill_tag, question_type, '')) IN (
    'tfng', 'ynng', 'matching_headings', 'matching_information',
    'matching_features', 'matching_sentence_endings', 'map_labeling',
    'map_labelling', 'matching'
  );

UPDATE bank_questions
SET difficulty = 'easy'
WHERE difficulty = 'medium'
  AND lower(coalesce(skill_tag, question_type, '')) IN (
    'form_completion', 'note_completion', 'table_completion'
  );
