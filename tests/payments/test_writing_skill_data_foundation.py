"""Phase 2 writing_skill data foundation — migration SQL contract tests."""

from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260821120000_writing_skill_data_foundation.sql"
)


def _sql() -> str:
    return MIGRATION.read_text()


def test_writing_skill_plan_seed_is_inactive_at_89900_for_180_days():
    sql = _sql()
    assert "'writing_skill'" in sql
    assert "'Writing Skill'" in sql
    assert "89900" in sql
    assert "180" in sql
    assert "is_active = false" in sql
    assert "false," in sql  # INSERT is_active value
    # Must not flip FSP or activate pack on conflict.
    assert "ON CONFLICT (slug) DO UPDATE SET" in sql
    assert "is_active = false" in sql.split("ON CONFLICT (slug) DO UPDATE SET", 1)[1]


def test_writing_skill_entitlement_metadata_shape():
    sql = _sql()
    assert '"skills": ["writing"]' in sql
    assert '"mock_quota": 1' in sql
    assert '"personalized_plan": false' in sql
    assert '"task1": 6' in sql
    assert '"task2": 6' in sql
    assert '"sequential": true' in sql
    assert "ADD COLUMN IF NOT EXISTS entitlement jsonb" in sql


def test_users_exam_module_nullable_with_check():
    sql = _sql()
    assert "ADD COLUMN IF NOT EXISTS exam_module text" in sql
    assert "users_exam_module_check" in sql
    assert "'academic'" in sql
    assert "'general_training'" in sql
    assert "exam_module IS NULL" in sql


def test_practice_sets_exam_module_allows_both_and_backfills_writing_only():
    sql = _sql()
    assert "practice_sets_exam_module_check" in sql
    assert "'both'" in sql
    assert "pb.skill = 'writing'" in sql
    assert "SET exam_module = 'academic'" in sql
    assert "idx_practice_sets_exam_module_status" in sql
    # Must not blanket-tag all practice sets.
    assert "pb.skill = 'listening'" not in sql
    assert "pb.skill = 'reading'" not in sql
    assert "pb.skill = 'speaking'" not in sql


def test_program_content_items_supports_academic_and_gt_hubs():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS program_content_items" in sql
    assert "item_type text NOT NULL" in sql
    assert "'practice_hub'" in sql
    assert "'mock_test'" in sql
    assert "UNIQUE (plan_id, item_type, item_id, exam_module)" in sql
    assert "idx_program_content_items_plan_module_sort" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE program_content_items TO service_role" in sql


def test_user_program_usage_unique_purchase_and_mock_quota_constraints():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS user_program_usage" in sql
    assert "UNIQUE (subscription_id)" in sql
    assert "mocks_granted integer NOT NULL DEFAULT 1" in sql
    assert "mocks_used integer NOT NULL DEFAULT 0" in sql
    assert "user_program_usage_mocks_within_grant" in sql
    assert "mocks_used <= mocks_granted" in sql
    assert "idx_user_program_usage_user" in sql
    assert "REFERENCES subscriptions(id) ON DELETE CASCADE" in sql
    assert "REFERENCES plans(id) ON DELETE RESTRICT" in sql


def test_phase2_migration_is_additive_and_inert():
    sql = _sql()
    lower = sql.lower()
    assert "drop table" not in lower
    assert "truncate" not in lower
    # No content attachment / publish side effects.
    assert "INSERT INTO program_content_items" not in sql
    assert "UPDATE practice_sets" in sql  # writing backfill only
    assert "status = 'published'" not in sql
    # Pack plan stays inactive on insert and on conflict.
    assert "is_active = false" in sql
    assert "'writing_skill'" in sql
