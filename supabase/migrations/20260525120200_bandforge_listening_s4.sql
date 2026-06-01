-- BandForge Listening Section 4 (Transit lecture) — mock e0000000-0000-4000-8000-000000000004
-- Audio: listening/bandforge-s4/part-1/full.mp3 (private R2; presigned at runtime)

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000004'
);
DELETE FROM module_scores WHERE attempt_id IN (
  SELECT id FROM test_attempts WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000004'
);
DELETE FROM test_attempts WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000004';
DELETE FROM questions WHERE mock_test_id = 'e0000000-0000-4000-8000-000000000004';

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'e0000000-0000-4000-8000-000000000004',
  'IELTS Listening — Public Transit Systems and the Reduction of CO2 Emissions',
  'Founder Section 4: Public Transit Systems and the Reduction of CO2 Emissions. Source: ielts_listening_section_4. Audio: listening/bandforge-s4/part-1/full.mp3.',
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
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 1, 'Transport produces approximately a ___ of global CO2 emissions', 'Complete the notes below. Write NO MORE THAN TWO WORDS for each answer.', 'listening/bandforge-s4/part-1/full.mp3', NULL, 'quarter', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 2, 'Emissions vary by mode: a full bus is far cleaner per ___ than a car', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'traveller/traveler', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 3, 'Buses operate in dedicated ___ , kept separate from other traffic', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'lanes', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 4, 'The model was first established in ___ , Brazil', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'Curitiba', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 5, 'Main advantage = low ___ → suited to cities with limited budgets', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'construction cost', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 6, 'Light rail and metro run on ___ , so emissions at point of use are minimal', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'electricity', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 7, 'Capacity: one metro line carries as many people as a ___ full of cars', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'motorway', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 8, 'Integration: coordinated timetables + a single ___ for all modes', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'ticket', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 9, 'Driving discouraged by introducing a ___', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'congestion charge', 'completion'),
('e0000000-0000-4000-8000-000000000004', 'listening', 1, 'sentence_completion', 10, 'Higher-density housing near transit stops — known as ___ development', NULL, 'listening/bandforge-s4/part-1/full.mp3', NULL, 'transit-oriented/transit oriented', 'completion');
