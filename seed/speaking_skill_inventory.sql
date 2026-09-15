-- Speaking Skill production inventory (Society & Culture).
-- Prefer migration: supabase/migrations/20260915140000_speaking_bank_society_culture.sql
-- which owns Speaking Bank 4 as 15 SC part hubs + Community mock.
--
-- This seed is a lightweight PCI re-attach if hubs already exist (c161… / a100…0001).
-- exam_module = 'both' so course listing accepts academic/GT/both filters.

DO $$
DECLARE
  v_plan_id uuid;
BEGIN
  SELECT id INTO v_plan_id FROM plans WHERE slug = 'speaking_skill' LIMIT 1;
  IF v_plan_id IS NULL THEN
    RAISE EXCEPTION 'speaking_skill plan row missing — apply foundation migration first';
  END IF;

  DELETE FROM program_content_items WHERE plan_id = v_plan_id;

  INSERT INTO program_content_items (
    id, plan_id, item_type, item_id, exam_module, sort_order, is_active
  )
  SELECT
    ('d2100000-0000-4000-8000-' || lpad(v.sort_order::text, 12, '0'))::uuid,
    v_plan_id,
    'practice_hub',
    v.hub_id::uuid,
    'both',
    v.sort_order,
    true
  FROM (VALUES
    (1, 'c1610000-0000-4000-8000-000000010100'),
    (2, 'c1610000-0000-4000-8000-000000010200'),
    (3, 'c1610000-0000-4000-8000-000000010300'),
    (4, 'c1610000-0000-4000-8000-000000020100'),
    (5, 'c1610000-0000-4000-8000-000000020200'),
    (6, 'c1610000-0000-4000-8000-000000020300'),
    (7, 'c1610000-0000-4000-8000-000000030100'),
    (8, 'c1610000-0000-4000-8000-000000030200'),
    (9, 'c1610000-0000-4000-8000-000000030300'),
    (10, 'c1610000-0000-4000-8000-000000040100'),
    (11, 'c1610000-0000-4000-8000-000000040200'),
    (12, 'c1610000-0000-4000-8000-000000040300'),
    (13, 'c1610000-0000-4000-8000-000000050100'),
    (14, 'c1610000-0000-4000-8000-000000050200'),
    (15, 'c1610000-0000-4000-8000-000000050300')
  ) AS v(sort_order, hub_id);

  INSERT INTO program_content_items (
    id, plan_id, item_type, item_id, exam_module, sort_order, is_active
  )
  VALUES (
    'd2100000-0000-4000-8000-000000000100',
    v_plan_id,
    'mock_test',
    'a1000000-0000-4000-8000-000000000001',
    'both',
    100,
    true
  );

  UPDATE skill_full_mocks
  SET mock_test_id = 'a1000000-0000-4000-8000-000000000001',
      unlock_requires_sets = 15
  WHERE skill = 'speaking';

  UPDATE plans SET is_active = true WHERE id = v_plan_id;
END $$;
