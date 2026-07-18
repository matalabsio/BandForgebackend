-- Allow stub evaluations in shared AI evaluation cache.
ALTER TABLE diagnostic_ai_evaluations
  DROP CONSTRAINT IF EXISTS diagnostic_ai_evaluations_source_check;

ALTER TABLE diagnostic_ai_evaluations
  ADD CONSTRAINT diagnostic_ai_evaluations_source_check
  CHECK (evaluation_source IN ('ai', 'fallback', 'ai_stub'));
