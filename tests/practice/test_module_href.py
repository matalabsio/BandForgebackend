"""Unit tests for Phase 2 module href targeting."""

from __future__ import annotations

from app.practice.module_href import (
    config_from_slug_or_defaults,
    module_submit_config,
    parse_phase0_slug,
    plan_module_href,
)


def test_parse_phase0_slug_parts():
    assert parse_phase0_slug("phase0-listening-mt1-p2") == ("listening", 1, 2)
    assert parse_phase0_slug("phase0-reading-mt2-p3") == ("reading", 2, 3)
    assert parse_phase0_slug("phase0-speaking-mt1-full") == ("speaking", 1, None)
    assert parse_phase0_slug("custom-hub") is None


def test_module_submit_config_listening_part():
    cfg = module_submit_config(
        skill="listening", catalog_number=2, part=3, hub_id="h1"
    )
    assert cfg["type"] == "module"
    assert cfg["catalog_number"] == 2
    assert cfg["part"] == 3
    assert cfg["href"] == "/test/2/listening?part=3&auto=1&skill_context=listening"


def test_module_submit_config_reading_passage():
    cfg = module_submit_config(skill="reading", catalog_number=1, part=2)
    assert "passage=2" in cfg["href"]
    assert cfg["href"].startswith("/test/1/reading")


def test_module_submit_config_writing_and_speaking():
    w = module_submit_config(skill="writing", catalog_number=2, part=2)
    assert w["href"].startswith("/test/writing/task/2")
    assert "mock=m02" in w["href"]
    s = module_submit_config(skill="speaking", catalog_number=1)
    assert s["href"] == "/test/1/speaking?auto=1&skill_context=speaking"
    assert "part" not in s


def test_plan_module_href_uses_submit_config():
    cfg = module_submit_config(skill="listening", catalog_number=2, part=4)
    href = plan_module_href(
        skill="listening",
        hub_id="hub-uuid",
        task_type="practice",
        task_id="t-1-listening-practice-s0",
        submit_config=cfg,
    )
    assert href.startswith("/test/2/listening?part=4")
    assert "from=plan" in href
    assert "hubId=hub-uuid" in href
    assert "task=practice" in href


def test_config_from_slug_or_defaults():
    cfg = config_from_slug_or_defaults(
        skill="listening",
        slug="phase0-listening-mt2-p2",
        hub_id="x",
    )
    assert cfg["catalog_number"] == 2
    assert cfg["part"] == 2
    assert "/test/2/listening?part=2" in cfg["href"]
