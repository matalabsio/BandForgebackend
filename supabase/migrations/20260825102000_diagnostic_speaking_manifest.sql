-- Diagnostic free mock: seed Part 1 Speaking question matching pack.json S1.
-- Does not modify M01 speaking questions or the questions table schema.
-- Frontend diagnostic Speaking continues to use static pack.json; this seed
-- makes POST /api/speaking/{DIAGNOSTIC_MOCK_TEST_ID}/start return 200 for full accounts.

INSERT INTO questions (
  id,
  mock_test_id,
  module,
  question_type,
  question_number,
  part,
  prompt,
  options
)
VALUES
  (
    'd1000000-0000-4000-8000-000000000001',
    'd0000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part1',
    1,
    1,
    'Tell me about your place.',
    jsonb_build_object(
      'kind', 'question',
      'max_record_sec', 120,
      'duration_hint_sec', 90,
      'part_label', 'Part 1',
      'video_url', '/diagnostic/video/tell-me-about-your-place.mp4'
    )
  )
ON CONFLICT (id) DO UPDATE SET
  mock_test_id = EXCLUDED.mock_test_id,
  module = EXCLUDED.module,
  question_type = EXCLUDED.question_type,
  question_number = EXCLUDED.question_number,
  part = EXCLUDED.part,
  prompt = EXCLUDED.prompt,
  options = EXCLUDED.options;

-- Speaking module enablement for this mock is already covered by
-- 20260730120000_enable_speaking_all_mocks.sql — no is_enabled change here.
