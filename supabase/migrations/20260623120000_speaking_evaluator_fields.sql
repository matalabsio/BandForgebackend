-- Evaluator portal: per-criterion human scores and submission metadata.

ALTER TABLE speaking_reviews
  ADD COLUMN IF NOT EXISTS human_criteria_scores jsonb;

ALTER TABLE speaking_reviews
  ADD COLUMN IF NOT EXISTS submission_meta jsonb;
