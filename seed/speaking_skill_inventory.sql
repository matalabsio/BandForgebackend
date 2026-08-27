-- Speaking Skill production inventory: attach 12 part hubs + 1 mock to speaking_skill,
-- then activate the plan for checkout.
--
-- Prerequisites (run first if hubs are missing):
--   seed/speaking_skill_dummy_inventory.sql  → MT1 P1/P2/P3 + SS_P*_02..04 (12 hubs)
--
-- Resolves plan_id by slug (no hardcoded UUID). Idempotent PCI delete+insert.
-- exam_module = 'both' so course listing accepts academic/GT/both filters.

-- ---------------------------------------------------------------------------
-- program_content_items: 12 hubs (4×P1, 4×P2, 4×P3) + 1 Speaking mock (M01)
-- ---------------------------------------------------------------------------
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
  VALUES
    -- Part 1 (4 hubs)
    ('d2000000-0000-4000-8000-000000000001', v_plan_id, 'practice_hub', 'c1100000-0000-4000-8000-000000000031', 'both', 1, true),
    ('d2000000-0000-4000-8000-000000000002', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000102', 'both', 2, true),
    ('d2000000-0000-4000-8000-000000000003', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000103', 'both', 3, true),
    ('d2000000-0000-4000-8000-000000000004', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000104', 'both', 4, true),
    -- Part 2 (4 hubs)
    ('d2000000-0000-4000-8000-000000000005', v_plan_id, 'practice_hub', 'c1100000-0000-4000-8000-000000000032', 'both', 5, true),
    ('d2000000-0000-4000-8000-000000000006', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000202', 'both', 6, true),
    ('d2000000-0000-4000-8000-000000000007', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000203', 'both', 7, true),
    ('d2000000-0000-4000-8000-000000000008', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000204', 'both', 8, true),
    -- Part 3 (4 hubs)
    ('d2000000-0000-4000-8000-000000000009', v_plan_id, 'practice_hub', 'c1100000-0000-4000-8000-000000000033', 'both', 9, true),
    ('d2000000-0000-4000-8000-00000000000a', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000302', 'both', 10, true),
    ('d2000000-0000-4000-8000-00000000000b', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000303', 'both', 11, true),
    ('d2000000-0000-4000-8000-00000000000c', v_plan_id, 'practice_hub', 'c1510000-0000-4000-8000-000000000304', 'both', 12, true),
    -- Allotted Speaking mock (M01)
    ('d2000000-0000-4000-8000-00000000000d', v_plan_id, 'mock_test', 'a0000000-0000-4000-8000-000000000001', 'both', 100, true);
END $$;

-- Activate after inventory is attached (12 hubs + 1 mock).
UPDATE plans
SET is_active = true
WHERE slug = 'speaking_skill';
