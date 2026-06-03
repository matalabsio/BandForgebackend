-- M01 Writing Task 1: examiner pack labels (Figure 1, source note, y-axis, legend modes)

UPDATE questions
SET
  options = $opts${
    "min_words": 150,
    "image_url": null,
    "title": "WRITING TASK 1 — BAR CHART — COMMUTER TRANSPORT MODES",
    "difficulty": "Band 6–7",
    "figure_label": "Figure 1",
    "figure_note": "[Grouped bar chart — four cities on x-axis; percentage on y-axis; four transport modes shown per city]",
    "chart": {
      "type": "grouped_bar",
      "title": "Percentage of commuters using different modes of transport in four cities, 2022",
      "source": "Global Urban Mobility Survey, 2022 (fabricated for assessment purposes)",
      "y_max": 70,
      "cities": ["Tokyo", "Berlin", "São Paulo", "Toronto"],
      "series": [
        {"mode": "Car / Private Vehicle", "values": [14, 28, 47, 52]},
        {"mode": "Public Transport", "values": [62, 41, 38, 31]},
        {"mode": "Cycling", "values": [16, 22, 5, 7]},
        {"mode": "Walking", "values": [8, 9, 10, 10]}
      ]
    }
  }$opts$::jsonb
WHERE mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  AND module = 'writing'
  AND part = 1;
