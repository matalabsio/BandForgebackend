-- M03 Writing: Task 1 (grouped bar + chart PNG) + Task 2 (problem/solution essay)
-- mock_test_id = a0000000-0000-4000-8000-000000000003

DELETE FROM questions
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000003'
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
    'a0000000-0000-4000-8000-000000000003',
    'writing',
    'task1_academic',
    1,
    1,
    $prompt$You should spend about 20 minutes on this task.

The chart below shows the percentage of university students enrolled in STEM and Humanities courses in five countries in 2023.

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
    $opts${
      "min_words": 150,
      "image_url": "writing/m03/task1/chart.png",
      "title": "WRITING TASK 1 — University STEM and Humanities Enrolment (2023)",
      "figure_label": "Figure 1",
      "chart": {
        "type": "grouped_bar",
        "title": "Percentage of university students enrolled in STEM and Humanities courses in five countries, 2023",
        "source": "Illustrative enrolment data, 2023",
        "cities": ["South Korea", "India", "Germany", "United Kingdom", "Brazil"],
        "y_max": 70,
        "series": [
          {"mode": "STEM", "values": [58, 52, 45, 34, 29]},
          {"mode": "Humanities", "values": [22, 28, 30, 41, 38]}
        ]
      }
    }$opts$::jsonb
  ),
  (
    'a0000000-0000-4000-8000-000000000003',
    'writing',
    'task2',
    1,
    2,
    $prompt$You should spend about 40 minutes on this task.

Rapid urbanisation is putting extreme pressure on housing and public services in many developing cities. What are the causes of this and what solutions can be proposed?

Give reasons for your answer and include any relevant examples from your own knowledge or experience.

Write at least 250 words.$prompt$,
    '{"min_words": 250, "title": "WRITING TASK 2 — Urbanisation and public services"}'::jsonb
  );
