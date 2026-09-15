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
CATALOG_BUMP = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260915150000_speaking_sc_catalog_bump.sql"
)
DEPRECATED_DUMMY = ROOT / "seed" / "speaking_skill_dummy_inventory.sql"
DEPRECATED_M01_DRAFT = ROOT / "seed" / "m01_speaking_qb_drafts.sql"


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
    """Foundation row still seeds 4+4+4; catalog bump migration raises to 5+5+5."""
    sql = _foundation()
    assert '"skills": ["speaking"]' in sql
    assert '"mock_quota": 1' in sql
    assert '"personalized_plan": false' in sql
    assert '"part1": 4' in sql
    assert '"part2": 4' in sql
    assert '"part3": 4' in sql
    assert '"sequential": true' in sql
    bump = CATALOG_BUMP.read_text()
    assert '"part1": 5' in bump
    assert '"part2": 5' in bump
    assert '"part3": 5' in bump
    assert "unlock_requires_sets = 15" in bump
    assert "a1000000-0000-4000-8000-000000000001" in bump


def test_speaking_skill_foundation_is_additive_and_inert():
    sql = _foundation()
    lower = sql.lower()
    assert "drop table" not in lower
    assert "truncate" not in lower
    assert "INSERT INTO program_content_items" not in sql
    assert "is_active = false" in sql
    assert "'speaking_skill'" in sql


def test_speaking_skill_inventory_attaches_15_sc_hubs_and_mock_then_activates():
    sql = _inventory()
    assert "speaking_skill" in sql
    assert "program_content_items" in sql
    assert "practice_hub" in sql
    assert "mock_test" in sql
    # 15 SC hubs + Community mock (deterministic PCI ids)
    assert "d2100000-0000-4000-8000-" in sql
    assert "c1610000-0000-4000-8000-000000010100" in sql
    assert "c1610000-0000-4000-8000-000000050300" in sql
    assert "a1000000-0000-4000-8000-000000000001" in sql
    assert "unlock_requires_sets = 15" in sql
    assert "UPDATE plans" in sql
    assert "is_active = true" in sql
    assert "WHERE slug = 'speaking_skill'" in sql or "WHERE id = v_plan_id" in sql


def test_deprecated_speaking_dummy_seeds_are_removed():
    """Dummy MT1_ST_/SS_ seeds must not exist (SC bank owns Speaking Bank 4)."""
    assert not DEPRECATED_DUMMY.exists()
    assert not DEPRECATED_M01_DRAFT.exists()
