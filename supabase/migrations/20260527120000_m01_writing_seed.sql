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
    $prompt$You should spend about 20 minutes on this task.

The bar chart below shows the proportion of workers who used four different modes of transport — car, public transport, cycling, and walking — to travel to work in Tokyo, Berlin, São Paulo, and Toronto in 2022.

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
    $opts${
      "min_words": 150,
      "image_url": null,
      "title": "WRITING TASK 1 — BAR CHART — COMMUTER TRANSPORT MODES",
      "difficulty": "Band 6–7",
      "chart": {
        "type": "grouped_bar",
        "title": "Percentage of commuters using different modes of transport in four cities, 2022",
        "source": "Global Urban Mobility Survey, 2022",
        "cities": ["Tokyo", "Berlin", "São Paulo", "Toronto"],
        "series": [
          {"mode": "Car", "values": [14, 28, 47, 52]},
          {"mode": "Public Transport", "values": [62, 41, 38, 31]},
          {"mode": "Cycling", "values": [16, 22, 5, 7]},
          {"mode": "Walking", "values": [8, 9, 10, 10]}
        ]
      }
    }$opts$::jsonb
  ),
  (
    'a0000000-0000-4000-8000-000000000001',
    'writing',
    'task2',
    1,
    2,
    $prompt$You should spend about 40 minutes on this task.

In many countries, school examinations remain the primary method used to evaluate how much students have learned. Some people believe that examinations accurately reflect a student's true ability, while others argue that they are an unreliable and narrow form of assessment.

To what extent do you agree or disagree?

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    '{"min_words": 250, "title": "WRITING TASK 2 — OPINION — EDUCATION", "difficulty": "Band 6–7"}'::jsonb
  );

UPDATE mock_test_modules
SET is_enabled = true
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'writing';
