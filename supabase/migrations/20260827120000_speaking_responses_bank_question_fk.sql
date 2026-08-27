-- Speaking bank practice uses bank_questions UUIDs in frozen manifests.
-- speaking_responses.question_id must accept those IDs as well as mock questions.id.
-- Identity is enforced by the attempt manifest + UNIQUE(attempt_id, question_id), not this FK.

ALTER TABLE speaking_responses
  DROP CONSTRAINT IF EXISTS speaking_responses_question_id_fkey;

COMMENT ON COLUMN speaking_responses.question_id IS
  'Question UUID from the frozen speaking_manifest (mock questions.id or bank_questions.id).';
