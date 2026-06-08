-- M02 Writing: Task 1 (line graph) + Task 2 (problem/solution essay)
-- mock_test_id = a0000000-0000-4000-8000-000000000002

DELETE FROM questions
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000002'
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
    'a0000000-0000-4000-8000-000000000002',
    'writing',
    'task1_academic',
    1,
    1,
    $prompt$You should spend about 20 minutes on this task.

The line graph below shows the number of internet users worldwide, measured in billions, across six regions between 2000 and 2025.

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
    $opts${
      "min_words": 150,
      "image_url": null,
      "title": "WRITING TASK 1 — LINE GRAPH — GLOBAL INTERNET USERS BY REGION (2000–2025)",
      "difficulty": "Band 7–8",
      "figure_label": "Figure 1",
      "figure_note": "Global Internet Users by Region, 2000–2025 (billions)",
      "chart": {
        "type": "line_graph",
        "title": "Global Internet Users by Region, 2000–2025",
        "source": "International Telecommunication Union (ITU) / DataReportal, 2025 (illustrative)",
        "y_max": 3.0,
        "y_unit": "billions",
        "labels": ["2000", "2005", "2010", "2015", "2020", "2025"],
        "series": [
          {"label": "Asia-Pacific", "values": [0.11, 0.33, 0.73, 1.41, 2.10, 2.72]},
          {"label": "Europe", "values": [0.11, 0.27, 0.46, 0.60, 0.73, 0.80]},
          {"label": "North America", "values": [0.17, 0.22, 0.27, 0.33, 0.38, 0.41]},
          {"label": "Latin America", "values": [0.02, 0.07, 0.18, 0.33, 0.48, 0.58]},
          {"label": "Middle East & Africa", "values": [0.01, 0.04, 0.12, 0.28, 0.52, 0.71]},
          {"label": "Rest of World", "values": [0.02, 0.03, 0.06, 0.09, 0.11, 0.12]}
        ]
      }
    }$opts$::jsonb
  ),
  (
    'a0000000-0000-4000-8000-000000000002',
    'writing',
    'task2',
    1,
    2,
    $prompt$You should spend about 40 minutes on this task.

The rate of mental health disorders among young people is rising sharply in many countries. What are the reasons for this trend and what can be done to tackle it?

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    '{"min_words": 250, "title": "WRITING TASK 2 — Problem & Solution — Health & Lifestyle", "difficulty": "Band 7–8"}'::jsonb
  );
