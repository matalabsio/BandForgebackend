"""Practice bank speaking AI helpers."""

from __future__ import annotations

from app.practice.speaking_ai import (
    SCORE_KIND,
    build_pending_speaking_score,
    resolve_speaking_part,
)


def test_resolve_speaking_part_from_question_type():
    assert resolve_speaking_part(question_type="speaking_part3") == 3
    assert resolve_speaking_part(question_type="Part 2") == 2
    assert resolve_speaking_part(question_type="p1") == 1


def test_resolve_speaking_part_from_hub_title():
    assert resolve_speaking_part(question_type="", title="SS_P3_02") == 3
    assert resolve_speaking_part(question_type="", title="MT1_ST_P2") == 2
    assert resolve_speaking_part(question_type="", title="speaking-mt1-p1") == 1


def test_resolve_speaking_part_section_fallback():
    assert resolve_speaking_part(question_type="", section_part=2) == 2
    assert resolve_speaking_part(question_type="essay", section_part=9) == 1


def test_build_pending_speaking_score():
    score = build_pending_speaking_score(
        speaking_attempt_id="att-1",
        speaking_manifest_hash="hash-1",
        hub_title="Hub A",
        speaking_review_id="rev-1",
    )
    assert score["kind"] == SCORE_KIND
    assert score["status"] == "pending"
    assert score["speaking_attempt_id"] == "att-1"
    assert score["speaking_manifest_hash"] == "hash-1"
    assert score["speaking_review_id"] == "rev-1"
    assert score["hub_title"] == "Hub A"
