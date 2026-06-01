-- M01 Writing Task 2: examinations opinion essay (from test/writing/WRITING TASK 2.pdf)

UPDATE questions
SET
  question_type = 'task2',
  prompt = $prompt$You should spend about 40 minutes on this task.

In many countries, school examinations remain the primary method used to evaluate how much students have learned. Some people believe that examinations accurately reflect a student's true ability, while others argue that they are an unreliable and narrow form of assessment.

To what extent do you agree or disagree?

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
  options = '{"min_words": 250, "title": "WRITING TASK 2 — OPINION — EDUCATION", "difficulty": "Band 6–7"}'::jsonb
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'writing'
  AND part = 2;
