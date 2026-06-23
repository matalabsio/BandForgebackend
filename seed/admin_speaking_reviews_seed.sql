-- Seed speaking review queue rows for admin UI testing.
-- Requires at least one user and one completed test_attempt.
-- Safe to re-run: uses fixed UUIDs.

-- Example review 1 (pending)
INSERT INTO speaking_reviews (
  id,
  attempt_id,
  status,
  transcript,
  audio_url,
  ai_scores,
  submission_meta,
  created_at
)
SELECT
  'b1000000-0000-4000-8000-000000000001',
  ta.id,
  'pending',
  'I believe technology has transformed education in many positive ways. Students can now access resources from anywhere in the world.',
  'speaking/seed/sample-1.webm',
  '{"fluency": 6.5, "grammar": 6.0, "lexical": 6.5, "pronunciation": 7.0}'::jsonb,
  '{"part": 2, "part_label": "Part 2", "prompt_title": "Describe a skill you would like to learn.", "cue_card": "Describe a skill you would like to learn.\n\nYou should say:\n- what the skill is\n- how you would learn it\n- how difficult it would be to learn\n- and explain why you would like to learn this skill."}'::jsonb,
  now() - interval '2 days'
FROM test_attempts ta
ORDER BY ta.started_at DESC
LIMIT 1
ON CONFLICT (id) DO NOTHING;

INSERT INTO speaking_reviews (
  id,
  attempt_id,
  status,
  transcript,
  audio_url,
  ai_scores,
  submission_meta,
  created_at
)
SELECT
  'b1000000-0000-4000-8000-000000000002',
  ta.id,
  'pending',
  'In my opinion, urban planning should prioritise green spaces and public transport over private car infrastructure.',
  'speaking/seed/sample-2.webm',
  '{"fluency": 7.0, "grammar": 6.5, "lexical": 7.0, "pronunciation": 6.5}'::jsonb,
  '{"part": 2, "part_label": "Part 2", "prompt_title": "Describe a place in your city you enjoy visiting.", "cue_card": "Describe a place in your city you enjoy visiting.\n\nYou should say:\n- where it is\n- how often you go there\n- what you do there\n- and explain why you enjoy visiting this place."}'::jsonb,
  now() - interval '1 day'
FROM test_attempts ta
ORDER BY ta.started_at DESC
LIMIT 1
ON CONFLICT (id) DO NOTHING;
