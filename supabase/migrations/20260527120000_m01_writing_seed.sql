-- M01 Writing: Task 1 + Task 2 questions; enable writing in full mock

DELETE FROM questions
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'writing';

INSERT INTO questions (
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
    'a0000000-0000-4000-8000-000000000001',
    'writing',
    'task1_academic',
    1,
    1,
    'The chart below shows the proportion of households in owned and rented accommodation in England and Wales between 1918 and 2011. Summarise the information by selecting and reporting the main features, and make comparisons where relevant.',
    '{"min_words": 150, "image_url": null}'::jsonb
  ),
  (
    'a0000000-0000-4000-8000-000000000001',
    'writing',
    'task2',
    1,
    2,
    'Some people believe that technology has made life more complicated. To what extent do you agree or disagree? Give reasons for your answer and include relevant examples from your own knowledge or experience.',
    '{"min_words": 250}'::jsonb
  );

UPDATE mock_test_modules
SET is_enabled = true
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'writing';
