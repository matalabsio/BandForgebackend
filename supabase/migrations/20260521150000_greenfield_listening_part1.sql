-- Greenfield College — IELTS Listening Part 1 (form completion, Q1–10)
-- Single production listening test (founder test/ content)
-- mock_test_id = d0000000-0000-4000-8000-000000000001
-- Audio: listening/greenfield/part-1/full.mp3 (R2)

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001'
);
DELETE FROM questions WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001';
DELETE FROM test_attempts WHERE mock_test_id = 'd0000000-0000-4000-8000-000000000001';

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'd0000000-0000-4000-8000-000000000001',
  'IELTS Listening Test — Greenfield College Part 1',
  'Founder test (test/): Part 1 form completion, Q1–10. Audio streamed once from Cloudflare R2 object storage.',
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
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 1,
  'First name',
  E'Questions 1–10: Form Completion\nComplete the form below. Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.\n\n╔══════════════════════════════════════════════════════════════╗\n║     GREENFIELD COLLEGE – COURSE REGISTRATION FORM            ║\n╠══════════════════════════════════════════════════════════════╣\n║  PERSONAL DETAILS                                            ║\n║    (1) First name:        ___________________________        ║\n║    (2) Surname:           ___________________________        ║\n║    (3) Nationality:       ___________________________        ║\n║    (4) Current occupation: ___________________________       ║\n║  COURSE DETAILS                                              ║\n║    (5) Course level:      ___________________________        ║\n║    (6) Preferred class day: ___________________________      ║\n║    (7) Start date:        ___________________________        ║\n║  PAYMENT & ADDITIONAL INFORMATION                            ║\n║    (8) Course fee:         £ ___________________________     ║\n║    (9) Payment method:    ___________________________        ║\n║   (10) Additional note:   ___________________________        ║\n╚══════════════════════════════════════════════════════════════╝',
  'listening/greenfield/part-1/full.mp3',
  NULL, 'Priya', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 2,
  'Surname',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, 'Mehta', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 3,
  'Nationality',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, 'Indian', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 4,
  'Current occupation',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, 'nurse', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 5,
  'Course level',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, 'upper intermediate', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 6,
  'Preferred class day',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, 'Tuesday', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 7,
  'Start date',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, '14 March / fourteenth of March / 14th March', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 8,
  'Course fee',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, '685 / £685 / six hundred eighty-five', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 9,
  'Payment method',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, 'bank / bank transfer', 'detail'
),
(
  'd0000000-0000-4000-8000-000000000001', 'listening', 1, 'form_completion', 10,
  'Additional note',
  NULL,
  'listening/greenfield/part-1/full.mp3',
  NULL, 'large print handouts / large print', 'inference'
);

-- Single live listening test until admin UI exists
UPDATE mock_tests SET is_published = false
WHERE id != 'd0000000-0000-4000-8000-000000000001';
