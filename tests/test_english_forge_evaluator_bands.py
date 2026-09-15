"""Stub regression for English Forge all-band coach evaluation (rubric-v1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# English Forge package lives under repo-root English/backend/ (same as app.main).
_REPO = Path(__file__).resolve().parents[2]  # MATA-lab/
_ENGLISH_BACKEND = _REPO / "English" / "backend"
_FIXTURES = _REPO / "English" / "calibration" / "fixtures"

if _ENGLISH_BACKEND.is_dir() and str(_ENGLISH_BACKEND) not in sys.path:
    sys.path.insert(0, str(_ENGLISH_BACKEND))

from english_forge.evaluator_stub import evaluate_stub  # noqa: E402
from english_forge.rubric import (  # noqa: E402
    RUBRIC_VERSION,
    STUB_EVALUATOR_VERSION,
    get_rubric,
)
from english_forge.schemas import CoachCard, EvaluateRequest  # noqa: E402

IELTS_BANNED = (
    "ielts",
    "fluency & coherence",
    "lexical resource",
    "grammatical range",
    "band 6",
    "band 7",
    "examiner",
)

WRONG_BAND_1_3 = (
    "subject–verb agreement",
    "subject-verb agreement",
    "preposition",
    "however",
    "therefore",
)

FIXTURE_FILES = [
    "fixtures-1-3-v1.json",
    "fixtures-4-5-v1.json",
    "fixtures-6-8-v1.json",
    "fixtures-9-10-v1.json",
]


def _load_all_fixtures() -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for name in FIXTURE_FILES:
        path = _FIXTURES / name
        data = json.loads(path.read_text(encoding="utf-8"))
        for fx in data["fixtures"]:
            rows.append((name, fx))
    return rows


def _card_text_blob(card: CoachCard) -> str:
    parts = [
        card.strength or "",
        card.filler_note or "",
        card.retry_prompt or "",
        " ".join(card.new_words or []),
    ]
    if card.primary_fix:
        parts.extend(
            [
                card.primary_fix.before,
                card.primary_fix.after,
                card.primary_fix.why_kid_friendly,
            ]
        )
    return " ".join(parts).lower()


@pytest.fixture(scope="module")
def all_fixtures() -> list[tuple[str, dict]]:
    return _load_all_fixtures()


def test_fixture_sets_exist_and_cover_all_bands():
    bands = set()
    for name in FIXTURE_FILES:
        path = _FIXTURES / name
        assert path.is_file(), f"missing {name}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("rubric_version") == RUBRIC_VERSION
        assert len(data["fixtures"]) >= 10
        for fx in data["fixtures"]:
            bands.add(fx["grade_band"])
    assert bands == {"1-3", "4-5", "6-8", "9-10"}


@pytest.mark.parametrize(
    "fixture_file,fixture",
    _load_all_fixtures(),
    ids=lambda x: x["id"] if isinstance(x, dict) else str(x),
)
def test_stub_fixture_regression(fixture_file: str, fixture: dict):
    req = EvaluateRequest(
        grade_band=fixture["grade_band"],
        prompt=fixture["prompt"],
        transcript=fixture["transcript"],
        duration_sec=float(fixture["duration_sec"]),
    )
    card = evaluate_stub(req)

    # Schema
    assert card.understandable in ("yes", "mostly", "difficult")
    assert card.strength
    assert len(card.new_words) <= 3
    assert card.retry_prompt
    assert card.internal_signals is not None
    assert card.internal_signals.rubric_version == RUBRIC_VERSION
    assert card.internal_signals.evaluator_version == STUB_EVALUATOR_VERSION
    assert card.internal_signals.schema_version == "coach-card-v0"

    # Understandability
    assert card.understandable == fixture["expected_understandable"], (
        f"{fixture['id']}: expected {fixture['expected_understandable']}, "
        f"got {card.understandable}"
    )

    blob = _card_text_blob(card)

    # Safety: no IELTS jargon
    for banned in IELTS_BANNED:
        assert banned not in blob, f"{fixture['id']}: banned term {banned!r}"

    for unacc in fixture.get("unacceptable_corrections") or []:
        assert unacc.lower() not in blob, (
            f"{fixture['id']}: unacceptable {unacc!r} appeared in feedback"
        )

    # Age fit: 1–3 must not get pedantic / advanced coaching language
    if fixture["grade_band"] == "1-3":
        for phrase in WRONG_BAND_1_3:
            assert phrase not in blob, (
                f"{fixture['id']}: wrong-band language {phrase!r}"
            )
        for w in card.new_words:
            assert w.lower() not in ("however", "therefore", "independent"), (
                f"{fixture['id']}: vocab too advanced for 1–3: {w}"
            )

    # Primary fix rules
    if fixture.get("expect_primary_null"):
        assert card.primary_fix is None, (
            f"{fixture['id']}: expected null primary_fix"
        )
    elif fixture.get("acceptable_corrections"):
        assert card.primary_fix is not None, (
            f"{fixture['id']}: expected a primary_fix"
        )
        assert card.primary_fix.before.lower() in req.transcript.lower(), (
            f"{fixture['id']}: before={card.primary_fix.before!r} "
            "not found in transcript (hallucination)"
        )
        matched = False
        for acc in fixture["acceptable_corrections"]:
            before_ok = acc.get("before_contains", "").lower() in (
                card.primary_fix.before.lower()
            )
            after_ok = acc.get("after_contains", "").lower() in (
                card.primary_fix.after.lower()
            )
            if before_ok and after_ok:
                matched = True
                break
        assert matched, (
            f"{fixture['id']}: fix {card.primary_fix.before!r} → "
            f"{card.primary_fix.after!r} not in acceptable_corrections"
        )

    if fixture.get("expect_filler_note"):
        assert card.filler_note, f"{fixture['id']}: expected filler_note"


def test_cross_band_same_transcript_differs():
    """Same school error must coach differently at 1–3 vs 9–10."""
    prompt = "Tell me about your school."
    transcript = (
        "My school is near my house. I go school every day. "
        "I like the playground and my friends."
    )
    duration = 30.0

    cards = {}
    for band in ("1-3", "4-5", "6-8", "9-10"):
        cards[band] = evaluate_stub(
            EvaluateRequest(
                grade_band=band,  # type: ignore[arg-type]
                prompt=prompt,
                transcript=transcript,
                duration_sec=duration,
            )
        )

    for band, card in cards.items():
        assert card.primary_fix is not None, f"{band} should fix missing 'to'"
        assert "go to school" in card.primary_fix.after.lower()

    why_13 = cards["1-3"].primary_fix.why_kid_friendly.lower()  # type: ignore[union-attr]
    why_910 = cards["9-10"].primary_fix.why_kid_friendly.lower()  # type: ignore[union-attr]
    assert why_13 != why_910
    assert "add \"to\"" in why_13 or "add 'to'" in why_13 or 'add "to"' in why_13
    assert "preposition" in why_910 or "clearer" in why_910

    # Vocab ceilings differ
    assert "however" not in [w.lower() for w in cards["1-3"].new_words]
    assert any(
        w.lower() in ("however", "therefore", "independent")
        for w in cards["9-10"].new_words
    ) or cards["9-10"].new_words != cards["1-3"].new_words

    # Strength / retry differ across ends of the ladder
    assert cards["1-3"].strength != cards["9-10"].strength
    assert "60" in cards["9-10"].retry_prompt or "reason" in cards["9-10"].retry_prompt.lower()


def test_rubric_labels_match_product_sets():
    assert get_rubric("1-3").class_label == "Set 1 · Class 1–3"
    assert get_rubric("4-5").class_label == "Set 2 · Class 3–6"
    assert get_rubric("6-8").class_label == "Set 3 · Class 6–8"
    assert get_rubric("9-10").class_label == "Set 4 · Class 8–10"
    assert get_rubric("4-5").target_duration_sec == 30
    assert get_rubric("9-10").max_duration_sec == 90


def test_build_system_prompt_injects_band_block():
    from english_forge.evaluator import build_system_prompt

    sys_13 = build_system_prompt("1-3")
    sys_910 = build_system_prompt("9-10")
    assert "Set 1 · Class 1–3" in sys_13
    assert "Lean praise" in sys_13 or "meaning-blocking" in sys_13
    assert "Set 4 · Class 8–10" in sys_910
    assert "precision" in sys_910.lower()
    assert sys_13 != sys_910
