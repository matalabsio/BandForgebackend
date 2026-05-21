-- BandForge — IELTS Listening seed (20 questions, 4 parts × 5)
-- mock_test_id = c0000000-0000-4000-8000-000000000001
-- Audio keys: listening/ielts-day3/part-<N>/q-<M>.mp3 (5–8 sec snippets per question)
-- Run AFTER 20260523130000_questions_part.sql.

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions WHERE mock_test_id = 'c0000000-0000-4000-8000-000000000001'
);
DELETE FROM questions WHERE mock_test_id = 'c0000000-0000-4000-8000-000000000001';
DELETE FROM test_attempts WHERE mock_test_id = 'c0000000-0000-4000-8000-000000000001';

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'c0000000-0000-4000-8000-000000000001',
  'IELTS Listening — Full Mock (20 short clips)',
  '4 IELTS Listening parts with 5 short audio clips each (5–8s). Form completion, MCQ, matching, note completion.',
  true
)
ON CONFLICT (id) DO UPDATE
SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  is_published = true;

-- =============================================================
-- PART 1 — Social Dialogue (form/table completion)
-- =============================================================
INSERT INTO questions (
  mock_test_id, module, part, question_type, question_number, prompt,
  passage_text, audio_url, options, correct_answer, skill_tag
) VALUES
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 1,
  'Caller''s first name',
  'Booking form — fill the blanks. Use NO MORE THAN TWO WORDS for each answer.',
  'listening/ielts-day3/part-1/q-1.mp3',
  NULL, 'Sophie', 'detail'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 2,
  'Postcode',
  NULL,
  'listening/ielts-day3/part-1/q-2.mp3',
  NULL, 'BS3 4PR', 'detail'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 3,
  'Number of nights',
  NULL,
  'listening/ielts-day3/part-1/q-3.mp3',
  NULL, '3', 'detail'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 1, 'mcq', 4,
  'How will the guest pay?',
  NULL,
  'listening/ielts-day3/part-1/q-4.mp3',
  '[{"label":"A","text":"Cash on arrival"},{"label":"B","text":"Credit card now"},{"label":"C","text":"Bank transfer"},{"label":"D","text":"Pay on checkout"}]'::jsonb,
  'B', 'detail'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 5,
  'Special request',
  NULL,
  'listening/ielts-day3/part-1/q-5.mp3',
  NULL, 'late checkout', 'inference'
);

-- =============================================================
-- PART 2 — Social Monologue (map labels / MCQ)
-- =============================================================
INSERT INTO questions (
  mock_test_id, module, part, question_type, question_number, prompt,
  passage_text, audio_url, options, correct_answer, skill_tag
) VALUES
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 2, 'mcq', 6,
  'Where should visitors meet for the tour?',
  'Museum tour briefing — answer the questions about the route.',
  'listening/ielts-day3/part-2/q-1.mp3',
  '[{"label":"A","text":"Main entrance"},{"label":"B","text":"Information desk"},{"label":"C","text":"Cafe terrace"},{"label":"D","text":"East wing lobby"}]'::jsonb,
  'B', 'main_idea'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 2, 'mcq', 7,
  'Which floor is the gift shop on?',
  NULL,
  'listening/ielts-day3/part-2/q-2.mp3',
  '[{"label":"A","text":"Ground floor"},{"label":"B","text":"First floor"},{"label":"C","text":"Second floor"},{"label":"D","text":"Basement"}]'::jsonb,
  'A', 'detail'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 2, 'map_labeling', 8,
  'Label the location east of the fountain.',
  NULL,
  'listening/ielts-day3/part-2/q-3.mp3',
  '[{"label":"A","text":"Sculpture garden"},{"label":"B","text":"Children''s wing"},{"label":"C","text":"Library"},{"label":"D","text":"Cinema room"}]'::jsonb,
  'A', 'spatial'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 2, 'mcq', 9,
  'What time does the next guided tour begin?',
  NULL,
  'listening/ielts-day3/part-2/q-4.mp3',
  '[{"label":"A","text":"11:00"},{"label":"B","text":"11:30"},{"label":"C","text":"12:00"},{"label":"D","text":"13:00"}]'::jsonb,
  'B', 'detail'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 2, 'sentence_completion', 10,
  'Photography is allowed only in the ______________ rooms.',
  NULL,
  'listening/ielts-day3/part-2/q-5.mp3',
  NULL, 'temporary exhibition / temporary', 'inference'
);

-- =============================================================
-- PART 3 — Academic Seminar (MCQ / matching, longer prompts)
-- =============================================================
INSERT INTO questions (
  mock_test_id, module, part, question_type, question_number, prompt,
  passage_text, audio_url, options, correct_answer, skill_tag
) VALUES
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 3, 'mcq', 11,
  'According to the students, what is the main weakness of their methodology?',
  'Seminar with two postgraduates and their supervisor reviewing an assignment.',
  'listening/ielts-day3/part-3/q-1.mp3',
  '[{"label":"A","text":"Sample size is too small"},{"label":"B","text":"Bias in question wording"},{"label":"C","text":"Outdated source material"},{"label":"D","text":"Inconsistent data collection"}]'::jsonb,
  'A', 'inference'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 3, 'mcq', 12,
  'Which point does the supervisor disagree with?',
  NULL,
  'listening/ielts-day3/part-3/q-2.mp3',
  '[{"label":"A","text":"The hypothesis is too narrow"},{"label":"B","text":"More interviews are needed"},{"label":"C","text":"The literature review is sufficient"},{"label":"D","text":"Findings are statistically significant"}]'::jsonb,
  'C', 'attitude'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 3, 'matching', 13,
  'Match speaker (A=Anna, B=Ben, C=Supervisor) to opinion about deadlines.',
  NULL,
  'listening/ielts-day3/part-3/q-3.mp3',
  '[{"label":"A","text":"Anna"},{"label":"B","text":"Ben"},{"label":"C","text":"Supervisor"}]'::jsonb,
  'C', 'speaker_id'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 3, 'mcq', 14,
  'What follow-up task is assigned to the students?',
  NULL,
  'listening/ielts-day3/part-3/q-4.mp3',
  '[{"label":"A","text":"Run an additional pilot study"},{"label":"B","text":"Write a literature summary"},{"label":"C","text":"Submit a draft by Friday"},{"label":"D","text":"Recruit new participants"}]'::jsonb,
  'C', 'detail'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 3, 'mcq', 15,
  'What is the supervisor''s overall attitude toward the proposal?',
  NULL,
  'listening/ielts-day3/part-3/q-5.mp3',
  '[{"label":"A","text":"Enthusiastic"},{"label":"B","text":"Cautiously supportive"},{"label":"C","text":"Skeptical"},{"label":"D","text":"Disappointed"}]'::jsonb,
  'B', 'attitude'
);

-- =============================================================
-- PART 4 — Academic Lecture (note completion / summary)
-- =============================================================
INSERT INTO questions (
  mock_test_id, module, part, question_type, question_number, prompt,
  passage_text, audio_url, options, correct_answer, skill_tag
) VALUES
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 4, 'note_completion', 16,
  'Lecture topic: Coastal erosion is driven primarily by ______________.',
  'Complete the lecture notes. Use NO MORE THAN TWO WORDS for each answer.',
  'listening/ielts-day3/part-4/q-1.mp3',
  NULL, 'wave action / wave', 'main_idea'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 4, 'note_completion', 17,
  'Soft cliffs retreat at roughly ______________ metres per year on average.',
  NULL,
  'listening/ielts-day3/part-4/q-2.mp3',
  NULL, '1 / one', 'detail'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 4, 'note_completion', 18,
  'Sea defences are most effective when combined with ______________.',
  NULL,
  'listening/ielts-day3/part-4/q-3.mp3',
  NULL, 'beach nourishment / nourishment', 'inference'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 4, 'summary_completion', 19,
  'The professor argues that managed retreat is preferable because it is ______________.',
  NULL,
  'listening/ielts-day3/part-4/q-4.mp3',
  NULL, 'cost-effective / cheaper', 'inference'
),
(
  'c0000000-0000-4000-8000-000000000001', 'listening', 4, 'note_completion', 20,
  'A key example mentioned is the village of ______________.',
  NULL,
  'listening/ielts-day3/part-4/q-5.mp3',
  NULL, 'Happisburgh', 'detail'
);
