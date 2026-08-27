"""Speaking Skill payment / data foundation — migration + inventory SQL contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260825120000_speaking_skill_plan_foundation.sql"
)
INVENTORY = ROOT / "seed" / "speaking_skill_inventory.sql"
DUMMY = ROOT / "seed" / "speaking_skill_dummy_inventory.sql"


def _foundation() -> str:
    return FOUNDATION.read_text()


def _inventory() -> str:
    return INVENTORY.read_text()


def test_speaking_skill_plan_seed_is_inactive_at_89900_for_180_days():
    sql = _foundation()
    assert "'speaking_skill'" in sql
    assert "'Speaking Skill'" in sql
    assert "89900" in sql
    assert "180" in sql
    assert "is_active = false" in sql
    assert "false," in sql  # INSERT is_active value
    assert "ON CONFLICT (slug) DO UPDATE SET" in sql
    conflict = sql.split("ON CONFLICT (slug) DO UPDATE SET", 1)[1]
    assert "is_active = false" in conflict


def test_speaking_skill_entitlement_metadata_shape():
    sql = _foundation()
    assert '"skills": ["speaking"]' in sql
    assert '"mock_quota": 1' in sql
    assert '"personalized_plan": false' in sql
    assert '"part1": 4' in sql
    assert '"part2": 4' in sql
    assert '"part3": 4' in sql
    assert '"sequential": true' in sql


def test_speaking_skill_foundation_is_additive_and_inert():
    sql = _foundation()
    lower = sql.lower()
    assert "drop table" not in lower
    assert "truncate" not in lower
    assert "INSERT INTO program_content_items" not in sql
    assert "is_active = false" in sql
    assert "'speaking_skill'" in sql


def test_speaking_skill_inventory_attaches_12_hubs_and_mock_then_activates():
    sql = _inventory()
    assert "speaking_skill" in sql
    assert "program_content_items" in sql
    assert "practice_hub" in sql
    assert "mock_test" in sql
    # 12 hubs + 1 mock (deterministic PCI ids)
    assert "d2000000-0000-4000-8000-000000000001" in sql
    assert "d2000000-0000-4000-8000-00000000000c" in sql
    assert "d2000000-0000-4000-8000-00000000000d" in sql
    assert "a0000000-0000-4000-8000-000000000001" in sql  # M01 mock
    assert "UPDATE plans" in sql
    assert "is_active = true" in sql
    assert "WHERE slug = 'speaking_skill'" in sql


def test_speaking_skill_dummy_inventory_does_not_activate_plan():
    sql = DUMMY.read_text()
    assert "Does NOT activate speaking_skill" in sql or "does not activate" in sql.lower()
    assert "UPDATE plans" not in sql or "is_active = true" not in sql
    assert "INSERT INTO program_content_items" not in sql
