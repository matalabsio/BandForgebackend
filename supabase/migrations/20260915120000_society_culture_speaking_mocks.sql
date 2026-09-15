-- Society & Culture speaking mocks SC1–SC5 (catalog 6–10).
-- 55 questions; video_url null (placeholder UI); video_asset for later R2 attach.
-- P2 cue prompts are provisional until verified against examiner video.

INSERT INTO mock_tests (
  id, title, description, status, is_published, catalog_number,
  listening_parts, reading_passages, writing_tasks, is_diagnostic
)
VALUES
  (
    'a1000000-0000-4000-8000-000000000001',
    'Speaking Mock — Community (Society & Culture)',
    'Society & Culture speaking mock: Community. Parts 1–3 (11 questions). Examiner videos coming soon.',
    'published',
    true,
    6,
    0,
    0,
    0,
    false
  ),
  (
    'a1000000-0000-4000-8000-000000000002',
    'Speaking Mock — Festivals (Society & Culture)',
    'Society & Culture speaking mock: Festivals. Parts 1–3 (11 questions). Examiner videos coming soon.',
    'published',
    true,
    7,
    0,
    0,
    0,
    false
  ),
  (
    'a1000000-0000-4000-8000-000000000003',
    'Speaking Mock — Social Media (Society & Culture)',
    'Society & Culture speaking mock: Social Media. Parts 1–3 (11 questions). Examiner videos coming soon.',
    'published',
    true,
    8,
    0,
    0,
    0,
    false
  ),
  (
    'a1000000-0000-4000-8000-000000000004',
    'Speaking Mock — Media & News (Society & Culture)',
    'Society & Culture speaking mock: Media & News. Parts 1–3 (11 questions). Examiner videos coming soon.',
    'published',
    true,
    9,
    0,
    0,
    0,
    false
  ),
  (
    'a1000000-0000-4000-8000-000000000005',
    'Speaking Mock — Family (Society & Culture)',
    'Society & Culture speaking mock: Family. Parts 1–3 (11 questions). Examiner videos coming soon.',
    'published',
    true,
    10,
    0,
    0,
    0,
    false
  )
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  status = EXCLUDED.status,
  is_published = EXCLUDED.is_published,
  catalog_number = EXCLUDED.catalog_number,
  listening_parts = EXCLUDED.listening_parts,
  reading_passages = EXCLUDED.reading_passages,
  writing_tasks = EXCLUDED.writing_tasks,
  is_diagnostic = EXCLUDED.is_diagnostic;

INSERT INTO mock_test_modules (mock_test_id, module, sequence_order, duration_minutes, is_enabled)
VALUES
  ('a1000000-0000-4000-8000-000000000001', 'listening', 1, 30, false),
  ('a1000000-0000-4000-8000-000000000001', 'reading', 2, 30, false),
  ('a1000000-0000-4000-8000-000000000001', 'writing', 3, 60, false),
  ('a1000000-0000-4000-8000-000000000001', 'speaking', 4, 14, true),
  ('a1000000-0000-4000-8000-000000000002', 'listening', 1, 30, false),
  ('a1000000-0000-4000-8000-000000000002', 'reading', 2, 30, false),
  ('a1000000-0000-4000-8000-000000000002', 'writing', 3, 60, false),
  ('a1000000-0000-4000-8000-000000000002', 'speaking', 4, 14, true),
  ('a1000000-0000-4000-8000-000000000003', 'listening', 1, 30, false),
  ('a1000000-0000-4000-8000-000000000003', 'reading', 2, 30, false),
  ('a1000000-0000-4000-8000-000000000003', 'writing', 3, 60, false),
  ('a1000000-0000-4000-8000-000000000003', 'speaking', 4, 14, true),
  ('a1000000-0000-4000-8000-000000000004', 'listening', 1, 30, false),
  ('a1000000-0000-4000-8000-000000000004', 'reading', 2, 30, false),
  ('a1000000-0000-4000-8000-000000000004', 'writing', 3, 60, false),
  ('a1000000-0000-4000-8000-000000000004', 'speaking', 4, 14, true),
  ('a1000000-0000-4000-8000-000000000005', 'listening', 1, 30, false),
  ('a1000000-0000-4000-8000-000000000005', 'reading', 2, 30, false),
  ('a1000000-0000-4000-8000-000000000005', 'writing', 3, 60, false),
  ('a1000000-0000-4000-8000-000000000005', 'speaking', 4, 14, true)
ON CONFLICT (mock_test_id, module) DO UPDATE SET
  sequence_order = EXCLUDED.sequence_order,
  duration_minutes = EXCLUDED.duration_minutes,
  is_enabled = EXCLUDED.is_enabled;

INSERT INTO questions (
  id, mock_test_id, module, question_type, question_number, part, prompt, options
)
VALUES
  (
    'c3100000-0000-4000-8000-000000000001',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part1',
    1,
    1,
    'Do you live in a house or an apartment?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT1_Community_P1_01_house_or_apartment.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000002',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part1',
    2,
    1,
    'What do you like most about the area you live in?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT1_Community_P1_02_like_most_about_area.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000003',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part1',
    3,
    1,
    'Has your neighbourhood changed much since you were a child?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT1_Community_P1_03_neighbourhood_changed.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000004',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part1',
    4,
    1,
    'How well do you know your neighbours?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT1_Community_P1_04_know_neighbours.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000005',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part1',
    5,
    1,
    'Is your neighbourhood a quiet or lively place?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT1_Community_P1_05_quiet_or_lively.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000006',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part2',
    1,
    2,
    E'Describe a community event you attended.\n\nYou should say:\n• what the event was\n• where and when it took place\n• who was there with you\n\nand explain why this event was memorable for you.',
    '{"kind":"part2_intro","prep_sec":60,"record_sec":120,"duration_hint_sec":120,"part_label":"Part 2","video_url":null,"video_asset":"MT1_Community_P2_01_cue_card.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000007',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part3',
    1,
    3,
    'Why do you think community events are important for a society?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT1_Community_P3_01_community_events.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000008',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part3',
    2,
    3,
    'Do you think people are less involved in their communities today than in the past?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT1_Community_P3_02_less_involved_today.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000009',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part3',
    3,
    3,
    'How does technology affect the way communities interact with one another?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT1_Community_P3_03_technology_communities.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000010',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part3',
    4,
    3,
    'What role should local government play in organising community activities?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT1_Community_P3_04_local_government_role.mp4"}'::jsonb
  ),
  (
    'c3100000-0000-4000-8000-000000000011',
    'a1000000-0000-4000-8000-000000000001',
    'speaking',
    'speaking_part3',
    5,
    3,
    'Do you think a strong sense of community can prevent social problems? Why or why not?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT1_Community_P3_05_prevent_social_problems.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000001',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    1,
    1,
    'What is your favourite festival?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT2_Festivals_P1_01_favourite_festival.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000002',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    2,
    1,
    'How do people in your country usually celebrate festivals?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT2_Festivals_P1_02_how_celebrate.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000003',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    3,
    1,
    'Do you prefer celebrating festivals with family or friends?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT2_Festivals_P1_03_family_or_friends.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000004',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    4,
    1,
    'Did you enjoy festivals more as a child or now as an adult?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT2_Festivals_P1_04_child_or_adult.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000005',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part1',
    5,
    1,
    'Are there any traditions in your family that are passed down through generations?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT2_Festivals_P1_05_traditions_generations.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000006',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part2',
    1,
    2,
    E'Describe a festival that is important in your culture.\n\nYou should say:\n• what the festival is\n• when it is celebrated\n• how people usually celebrate it\n\nand explain why this festival is meaningful to you.',
    '{"kind":"part2_intro","prep_sec":60,"record_sec":120,"duration_hint_sec":120,"part_label":"Part 2","video_url":null,"video_asset":"MT2_Festivals_P2_01_cue_card.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000007',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part3',
    1,
    3,
    'Why do you think traditions are important to a society?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT2_Festivals_P3_01_traditions_important.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000008',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part3',
    2,
    3,
    'Do you think modernisation is causing some traditions to disappear?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT2_Festivals_P3_02_modernisation_disappear.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000009',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part3',
    3,
    3,
    'How do festivals help maintain a sense of national or cultural identity?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT2_Festivals_P3_03_cultural_identity.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000010',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part3',
    4,
    3,
    'Do you think young people today value traditions as much as older generations did?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT2_Festivals_P3_04_young_value_traditions.mp4"}'::jsonb
  ),
  (
    'c3200000-0000-4000-8000-000000000011',
    'a1000000-0000-4000-8000-000000000002',
    'speaking',
    'speaking_part3',
    5,
    3,
    'Should governments do more to preserve cultural traditions? How?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT2_Festivals_P3_05_governments_preserve.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000001',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part1',
    1,
    1,
    'Which social media platforms do you use most often?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT3_SocialMedia_P1_01_platforms_most_often.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000002',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part1',
    2,
    1,
    'How much time do you spend on social media every day?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT3_SocialMedia_P1_02_time_every_day.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000003',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part1',
    3,
    1,
    'Do you prefer talking to people in person or online?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT3_SocialMedia_P1_03_person_or_online.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000004',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part1',
    4,
    1,
    'Has social media changed the way you keep in touch with friends?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT3_SocialMedia_P1_04_changed_keep_in_touch.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000005',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part1',
    5,
    1,
    'What do you usually post about on social media?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT3_SocialMedia_P1_05_what_you_post.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000006',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part2',
    1,
    2,
    E'Describe a time when you used social media for something useful.\n\nYou should say:\n• what you used it for\n• which platform you used\n• what happened as a result\n\nand explain how social media helped in that situation.',
    '{"kind":"part2_intro","prep_sec":60,"record_sec":120,"duration_hint_sec":120,"part_label":"Part 2","video_url":null,"video_asset":"MT3_SocialMedia_P2_01_cue_card.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000007',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part3',
    1,
    3,
    'How has social media changed the way people communicate in society?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT3_SocialMedia_P3_01_changed_communication.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000008',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part3',
    2,
    3,
    'Do you think social media brings people closer together or pushes them apart?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT3_SocialMedia_P3_02_closer_or_apart.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000009',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part3',
    3,
    3,
    'What are the risks of young people spending too much time on social media?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT3_SocialMedia_P3_03_risks_young_people.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000010',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part3',
    4,
    3,
    'Do you think face-to-face communication will become less common in the future?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT3_SocialMedia_P3_04_face_to_face_future.mp4"}'::jsonb
  ),
  (
    'c3300000-0000-4000-8000-000000000011',
    'a1000000-0000-4000-8000-000000000003',
    'speaking',
    'speaking_part3',
    5,
    3,
    'Should social media companies be held responsible for the content shared on their platforms?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT3_SocialMedia_P3_05_companies_responsible.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000001',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part1',
    1,
    1,
    'How do you usually get your daily news?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT4_MediaNews_P1_01_get_daily_news.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000002',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part1',
    2,
    1,
    'What kind of news are you most interested in?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT4_MediaNews_P1_02_kind_of_news.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000003',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part1',
    3,
    1,
    'Do you prefer reading news online or watching it on TV?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT4_MediaNews_P1_03_online_or_tv.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000004',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part1',
    4,
    1,
    'Do you think it''s important to follow the news regularly?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT4_MediaNews_P1_04_follow_news_regularly.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000005',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part1',
    5,
    1,
    'Do you discuss current events with your family or friends?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT4_MediaNews_P1_05_discuss_current_events.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000006',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part2',
    1,
    2,
    E'Describe a news story that interested you recently.\n\nYou should say:\n• what the story was about\n• where you read or watched it\n• why it caught your attention\n\nand explain how this story made you feel.',
    '{"kind":"part2_intro","prep_sec":60,"record_sec":120,"duration_hint_sec":120,"part_label":"Part 2","video_url":null,"video_asset":"MT4_MediaNews_P2_01_cue_card.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000007',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part3',
    1,
    3,
    'How has the way people consume news changed in recent years?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT4_MediaNews_P3_01_consume_news_changed.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000008',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part3',
    2,
    3,
    'Do you think traditional media (TV, newspapers) will disappear eventually?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT4_MediaNews_P3_02_traditional_media_disappear.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000009',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part3',
    3,
    3,
    'How does misinformation affect public opinion and society as a whole?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT4_MediaNews_P3_03_misinformation_effect.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000010',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part3',
    4,
    3,
    'Should there be stricter regulation of news shared on the internet?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT4_MediaNews_P3_04_stricter_regulation.mp4"}'::jsonb
  ),
  (
    'c3400000-0000-4000-8000-000000000011',
    'a1000000-0000-4000-8000-000000000004',
    'speaking',
    'speaking_part3',
    5,
    3,
    'What responsibility do journalists have towards society?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT4_MediaNews_P3_05_journalist_responsibility.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000001',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part1',
    1,
    1,
    'Do you come from a large or small family?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT5_Family_P1_01_large_or_small.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000002',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part1',
    2,
    1,
    'What responsibilities do you have within your family?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT5_Family_P1_02_family_responsibilities.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000003',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part1',
    3,
    1,
    'How often do you spend time with your extended family?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT5_Family_P1_03_extended_family.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000004',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part1',
    4,
    1,
    'Has your role in the family changed as you''ve grown older?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT5_Family_P1_04_role_changed.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000005',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part1',
    5,
    1,
    'Do you think family structures in your country are changing?',
    '{"kind":"question","max_record_sec":3600,"duration_hint_sec":30,"part_label":"Part 1","video_url":null,"video_asset":"MT5_Family_P1_05_structures_changing.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000006',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part2',
    1,
    2,
    E'Describe a family member who has had a strong influence on you.\n\nYou should say:\n• who this person is\n• what your relationship is like\n• how they have influenced you\n\nand explain why this person is important in your life.',
    '{"kind":"part2_intro","prep_sec":60,"record_sec":120,"duration_hint_sec":120,"part_label":"Part 2","video_url":null,"video_asset":"MT5_Family_P2_01_cue_card.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000007',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part3',
    1,
    3,
    'How have family structures changed in your country over the past few decades?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT5_Family_P3_01_structures_decades.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000008',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part3',
    2,
    3,
    'Do you think extended families still play an important role in society today?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT5_Family_P3_02_extended_still_important.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000009',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part3',
    3,
    3,
    'Should adult children be responsible for taking care of their elderly parents?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT5_Family_P3_03_care_elderly_parents.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000010',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part3',
    4,
    3,
    'Do you think smaller family sizes affect how children are raised?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT5_Family_P3_04_smaller_sizes_raised.mp4"}'::jsonb
  ),
  (
    'c3500000-0000-4000-8000-000000000011',
    'a1000000-0000-4000-8000-000000000005',
    'speaking',
    'speaking_part3',
    5,
    3,
    'What effect does urbanisation have on traditional family systems?',
    '{"kind":"question","max_record_sec":60,"duration_hint_sec":45,"part_label":"Part 3","video_url":null,"video_asset":"MT5_Family_P3_05_urbanisation_effect.mp4"}'::jsonb
  )
ON CONFLICT (id) DO UPDATE SET
  mock_test_id = EXCLUDED.mock_test_id,
  question_type = EXCLUDED.question_type,
  question_number = EXCLUDED.question_number,
  part = EXCLUDED.part,
  prompt = EXCLUDED.prompt,
  options = EXCLUDED.options;
