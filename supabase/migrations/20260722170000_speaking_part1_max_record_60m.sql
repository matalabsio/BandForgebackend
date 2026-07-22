-- Part 1 speaking: allow up to 60 minutes per answer (testing window).
UPDATE public.questions
SET options = jsonb_set(
  COALESCE(options, '{}'::jsonb),
  '{max_record_sec}',
  '3600'::jsonb,
  true
)
WHERE module = 'speaking'
  AND part = 1
  AND (
    options IS NULL
    OR COALESCE((options->>'max_record_sec')::int, 0) < 3600
  );
