-- M02 Listening Part 1: Brookside Lettings form completion (Q1–10)
-- mock_test_id = a0000000-0000-4000-8000-000000000002
-- Source: test/listening/interface/BandForge_Listening_MT2_S1_Interface_Data.json
-- Audio: listening/m02/part-1/full.mp3

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions
  WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000002'
    AND module = 'listening'
    AND part = 1
);

DELETE FROM questions
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000002'
  AND module = 'listening'
  AND part = 1;

INSERT INTO questions (
  mock_test_id, module, part, question_type, question_number, prompt,
  passage_text, audio_url, options, correct_answer, skill_tag
) VALUES
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 1,
  'Surname',
  E'Questions 1–10: Form Completion\nComplete the form below. Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.\n\n╔══════════════════════════════════════════════════════════════╗\n║     BROOKSIDE LETTINGS — TENANT ENQUIRY FORM                 ║\n╠══════════════════════════════════════════════════════════════╣\n║    (1) Surname:                  ___________________________ ║\n║    (2) Mobile number:            ___________________________ ║\n║    (3) Type of property:         ___________________________ ║\n║    (4) Number of bedrooms:       ___________________________ ║\n║    (5) Preferred area:           ___________________________ ║\n║    (6) Maximum monthly rent:     ___________________________ ║\n║    (7) Earliest move-in date:    ___________________________ ║\n║    (8) Essential feature:        ___________________________ ║\n║    (9) Furnishing preference:    ___________________________ ║\n║   (10) Enquiry reference no:   ___________________________ ║\n╚══════════════════════════════════════════════════════════════╝',
  'listening/m02/part-1/full.mp3',
  NULL, 'Whitfield', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 2,
  'Mobile number',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, '07712 345886/07712345886', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 3,
  'Type of property',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, 'flat', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 4,
  'Number of bedrooms',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, 'three/3', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 5,
  'Preferred area',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, 'Kingsthorpe', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 6,
  'Maximum monthly rent',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, '850', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 7,
  'Earliest move-in date',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, '5 August/5th August/August 5', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 8,
  'Essential feature',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, 'parking', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 9,
  'Furnishing preference',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, 'unfurnished', 'detail'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 1, 'form_completion', 10,
  'Enquiry reference no',
  NULL,
  'listening/m02/part-1/full.mp3',
  NULL, '3164', 'detail'
);
