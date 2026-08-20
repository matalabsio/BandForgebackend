-- M05 Writing: Task 1 only (dual pie charts — daily news sources 2005 vs 2023)
-- mock_test_id = a0000000-0000-4000-8000-000000000005

DELETE FROM questions
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000005'
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
    'a0000000-0000-4000-8000-000000000005',
    'writing',
    'task1_academic',
    1,
    1,
    $prompt$You should spend about 20 minutes on this task.

The two pie charts below show how adults got their daily news in 2005 and in 2023.

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
    $opts${
      "min_words": 150,
      "image_url": "writing/m05/task1/chart.png",
      "title": "WRITING TASK 1 — How adults got daily news (2005 vs 2023)",
      "figure_label": "Figure 1",
      "chart": {
        "type": "pie_dual",
        "title": "How adults got their daily news",
        "source": "Illustrative news consumption data",
        "years": [2005, 2023],
        "series": [
          {"label": "TV", "values": [55, 25]},
          {"label": "Print", "values": [30, 5]},
          {"label": "Radio", "values": [10, 8]},
          {"label": "Online news", "values": [3, 35]},
          {"label": "Social media", "values": [2, 27]}
        ]
      }
    }$opts$::jsonb
  );
