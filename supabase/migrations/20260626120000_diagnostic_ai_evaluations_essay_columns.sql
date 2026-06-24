-- Store original vs cleaned essay text for debugging user disputes.

ALTER TABLE diagnostic_ai_evaluations
  ADD COLUMN IF NOT EXISTS original_essay_text text,
  ADD COLUMN IF NOT EXISTS cleaned_essay_text text;

-- Backfill: existing rows used essay_text as the evaluated body.
UPDATE diagnostic_ai_evaluations
SET
  cleaned_essay_text = COALESCE(cleaned_essay_text, essay_text),
  original_essay_text = COALESCE(original_essay_text, essay_text)
WHERE cleaned_essay_text IS NULL OR original_essay_text IS NULL;

COMMENT ON COLUMN diagnostic_ai_evaluations.original_essay_text IS
  'Raw textarea submission before instruction stripping.';
COMMENT ON COLUMN diagnostic_ai_evaluations.cleaned_essay_text IS
  'Essay body sent to Groq after sanitization.';
