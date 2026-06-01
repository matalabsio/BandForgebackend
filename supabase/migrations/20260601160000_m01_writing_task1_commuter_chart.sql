-- M01 Writing Task 1: commuter transport bar chart (from test/writing/WRITING TASK 1.pdf)

UPDATE questions
SET
  question_type = 'task1_academic',
  prompt = $prompt$You should spend about 20 minutes on this task.

The bar chart below shows the proportion of workers who used four different modes of transport — car, public transport, cycling, and walking — to travel to work in Tokyo, Berlin, São Paulo, and Toronto in 2022.

Summarise the information by selecting and reporting the main features, and make comparisons where relevant.

Write at least 150 words.$prompt$,
  options = $opts${
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
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'writing'
  AND part = 1;
