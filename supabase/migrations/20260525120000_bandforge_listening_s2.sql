-- BandForge Listening Section 2 (Leisure Centre) — founder mock e0000000-0000-4000-8000-000000000002
-- Audio: listening/bandforge-s2/part-1/full.mp3 (private R2; presigned at runtime)

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000002'
);
DELETE FROM module_scores WHERE attempt_id IN (
  SELECT id FROM test_attempts WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000002'
);
DELETE FROM test_attempts WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000002';
DELETE FROM questions WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000002';

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'e0000000-0000-4000-8000-000000000002',
  'IELTS Listening — Leisure Centre Orientation Talk',
  'Founder Section 2: Leisure Centre Orientation Talk. Source: ielts_listening_section_2. Audio: listening/bandforge-s2/part-1/full.mp3.',
  true
)
ON CONFLICT (id) DO UPDATE
SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  is_published = true;

INSERT INTO questions (
  mock_test_id, module, part, question_type, question_number, prompt,
  passage_text, audio_url, options, correct_answer, skill_tag
) VALUES
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'mcq', 1, 'The leisure centre opens on weekday mornings at', 'Choose the correct letter, A, B or C.', 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "six o''clock"}, {"label": "B", "text": "seven o''clock"}, {"label": "C", "text": "eight o''clock"}]'::jsonb, 'A', 'detail'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'mcq', 2, 'Before using the gym for the first time, new members must', NULL, 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "obtain a doctor''s note"}, {"label": "B", "text": "book a personal trainer"}, {"label": "C", "text": "complete a fitness assessment"}]'::jsonb, 'C', 'detail'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'mcq', 3, 'The main swimming pool will be closed', NULL, 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "for one week in July"}, {"label": "B", "text": "for two weeks in August"}, {"label": "C", "text": "for the whole summer"}]'::jsonb, 'B', 'detail'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'mcq', 4, 'What is now located just inside the entrance?', NULL, 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "a sports shop"}, {"label": "B", "text": "a café"}, {"label": "C", "text": "a crèche"}]'::jsonb, 'C', 'detail'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'mcq', 5, 'Members are allowed to park free of charge', NULL, 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "at any time of day"}, {"label": "B", "text": "for the first two hours"}, {"label": "C", "text": "only in the evenings"}]'::jsonb, 'B', 'detail'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'matching', 6, 'Aqua fitness', 'What does the guide say about each of the following classes? Choose your answers from the box and write the correct letter, A-G, next to Questions 6-10.', 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "It must be booked in advance."}, {"label": "B", "text": "It currently has no available places."}, {"label": "C", "text": "It is free of charge this month."}, {"label": "D", "text": "It is intended for beginners."}, {"label": "E", "text": "It has changed location."}, {"label": "F", "text": "It is held only at weekends."}, {"label": "G", "text": "It has had extra sessions added."}]'::jsonb, 'B', 'matching'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'matching', 7, 'Spin', NULL, 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "It must be booked in advance."}, {"label": "B", "text": "It currently has no available places."}, {"label": "C", "text": "It is free of charge this month."}, {"label": "D", "text": "It is intended for beginners."}, {"label": "E", "text": "It has changed location."}, {"label": "F", "text": "It is held only at weekends."}, {"label": "G", "text": "It has had extra sessions added."}]'::jsonb, 'C', 'matching'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'matching', 8, 'Yoga', NULL, 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "It must be booked in advance."}, {"label": "B", "text": "It currently has no available places."}, {"label": "C", "text": "It is free of charge this month."}, {"label": "D", "text": "It is intended for beginners."}, {"label": "E", "text": "It has changed location."}, {"label": "F", "text": "It is held only at weekends."}, {"label": "G", "text": "It has had extra sessions added."}]'::jsonb, 'E', 'matching'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'matching', 9, 'Climbing', NULL, 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "It must be booked in advance."}, {"label": "B", "text": "It currently has no available places."}, {"label": "C", "text": "It is free of charge this month."}, {"label": "D", "text": "It is intended for beginners."}, {"label": "E", "text": "It has changed location."}, {"label": "F", "text": "It is held only at weekends."}, {"label": "G", "text": "It has had extra sessions added."}]'::jsonb, 'A', 'matching'),
('e0000000-0000-4000-8000-000000000002', 'listening', 1, 'matching', 10, 'Pilates', NULL, 'listening/bandforge-s2/part-1/full.mp3', '[{"label": "A", "text": "It must be booked in advance."}, {"label": "B", "text": "It currently has no available places."}, {"label": "C", "text": "It is free of charge this month."}, {"label": "D", "text": "It is intended for beginners."}, {"label": "E", "text": "It has changed location."}, {"label": "F", "text": "It is held only at weekends."}, {"label": "G", "text": "It has had extra sessions added."}]'::jsonb, 'D', 'matching');
