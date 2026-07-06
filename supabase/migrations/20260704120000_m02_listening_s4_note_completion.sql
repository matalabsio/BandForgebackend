-- M02 Listening Part 4: note completion layout (dendrochronology notes)
-- Source: test/MT2/LT/interface/BandForge_Listening_MT2_S4_Interface_Data.json

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000002' AND module = 'listening' AND part = 4
);
DELETE FROM questions WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000002' AND module = 'listening' AND part = 4;

INSERT INTO questions (
  mock_test_id, module, part, question_type, question_number, prompt,
  passage_text, audio_url, options, correct_answer, skill_tag
) VALUES
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 1,
  'A tree adds one ring each year — counting the rings reveals the tree''s ___',
  E'Complete the notes below. Write NO MORE THAN TWO WORDS for each answer.\n@@notes_title@@DENDROCHRONOLOGY: DATING THE PAST THROUGH TREE RINGS\n@@section@@31-33|The basic principle\n@@section@@34-36|Building a long timeline\n@@section@@37-39|Applications\n@@section@@40|Limitations',
  'listening/m02/part-4/full.mp3',
  NULL, 'age', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 2,
  'The width of a ring is controlled mainly by the amount of ___ in that year',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'rainfall', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 3,
  'A year of drought produces a ring that is unusually ___',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'narrow', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 4,
  'Trees of one species in a region share a similar ring ___',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'pattern', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 5,
  'Living and dead timber samples are linked by a process called ___',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'cross-dating/cross dating/crossdating', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 6,
  'The continuous reference record produced is called a master ___',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'chronology', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 7,
  'Used in archaeology to establish the construction date of historic ___',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'buildings/building', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 8,
  'Tree-ring data is used to ___ radiocarbon dates, improving their accuracy',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'calibrate', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 9,
  'Ring sequences allow the past ___ of a region to be reconstructed',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'climate/climates', 'completion'
),
(
  'a0000000-0000-4000-8000-000000000002', 'listening', 4, 'note_completion', 10,
  'The method cannot be used in ___ regions, where trees lack clear annual rings',
  NULL,
  'listening/m02/part-4/full.mp3',
  NULL, 'tropical', 'completion'
);
