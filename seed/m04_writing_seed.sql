-- M04 Writing: Task 1 (line chart) + Task 2 (essay)
-- mock_test_id = a0000000-0000-4000-8000-000000000004

DELETE FROM questions
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000004'
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
    'a0000000-0000-4000-8000-000000000004',
    'writing',
    'task1_academic',
    1,
    1,
    $prompt$You should spend about 20 minutes on this task.

The graph below shows the percentage of adults classified as obese in the UK, the USA, and Japan between 1980 and 2020.

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
    $opts${
      "min_words": 150,
      "image_url": "writing/m04/task1/chart.png",
      "title": "WRITING TASK 1 — Adult obesity rates (USA, UK, Japan)",
      "figure_label": "Figure 1",
      "chart": {
        "type": "line",
        "title": "Percentage of adults classified as obese, 1980–2020",
        "source": "Illustrative obesity trend data",
        "years": [1980, 1990, 2000, 2010, 2020],
        "y_max": 50,
        "series": [
          {"label": "USA", "values": [15, 23, 31, 36, 42]},
          {"label": "UK", "values": [7, 13, 21, 26, 28]},
          {"label": "Japan", "values": [2.0, 2.5, 3.0, 3.5, 4.3]}
        ]
      }
    }$opts$::jsonb
  ),
  (
    'a0000000-0000-4000-8000-000000000004',
    'writing',
    'task2',
    1,
    2,
    $prompt$You should spend about 40 minutes on this task.

Misinformation spreads rapidly through social media platforms. Why does this happen and how can it be effectively controlled?

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    '{"min_words": 250, "title": "WRITING TASK 2 — Misinformation on social media"}'::jsonb
  );
