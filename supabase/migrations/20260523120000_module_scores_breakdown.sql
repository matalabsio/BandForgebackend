-- BandForge Listening — extend module_scores with breakdown columns
-- Idempotent: safe to re-run.
-- Source spec: Listening Module v1 (raw_score + correct_count + total_count + skill_breakdown jsonb).

ALTER TABLE module_scores
  ADD COLUMN IF NOT EXISTS correct_count integer,
  ADD COLUMN IF NOT EXISTS total_count integer,
  ADD COLUMN IF NOT EXISTS skill_breakdown jsonb;

COMMENT ON COLUMN module_scores.correct_count IS 'Number of correctly-answered MCQ items.';
COMMENT ON COLUMN module_scores.total_count IS 'Total number of scored items for this module.';
COMMENT ON COLUMN module_scores.skill_breakdown IS
  'Per-skill aggregation: { skill_tag: { correct, total, pct } } produced by ListeningEvaluator.';
