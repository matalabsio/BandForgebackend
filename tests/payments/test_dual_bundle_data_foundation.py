"""Dual Bundle Phase 2 migration SQL contract."""

from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260827140000_dual_bundle_skill_usage.sql"
)


def _sql() -> str:
    return MIGRATION.read_text()


def test_dual_bundle_plan_seed_inactive_179900_180_days():
    sql = _sql()
    assert "'dual_bundle'" in sql
    assert "'Dual Bundle'" in sql
    assert "179900" in sql
    assert "180" in sql
    assert "is_active = false" in sql
    assert '"skills": ["writing", "speaking"]' in sql
    assert "INSERT INTO program_content_items" not in sql


def test_skill_scoped_usage_unique_constraint():
    sql = _sql()
    assert "ADD COLUMN IF NOT EXISTS skill text" in sql
    assert "UNIQUE (subscription_id, skill)" in sql
    assert "user_program_usage_subscription_skill_key" in sql
    assert "CHECK (skill IN ('writing', 'speaking'))" in sql
    assert "DROP CONSTRAINT IF EXISTS user_program_usage_subscription_id_key" in sql
