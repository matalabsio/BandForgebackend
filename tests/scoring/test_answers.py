"""Contract tests for shared objective answer checking (Phase 3)."""

from __future__ import annotations

from app.scoring.answers import (
    is_answer_correct,
    normalize_answer,
    score_answers,
)


def test_normalize_collapses_whitespace():
    assert normalize_answer("  A  B  ") == "a b"
    assert normalize_answer(None) == ""


def test_is_answer_correct_slash_alternatives():
    assert is_answer_correct("colour", "color/colour")
    assert is_answer_correct("color", "color/colour")
    assert is_answer_correct("A", "A/B")
    assert is_answer_correct("B", "A/B")
    assert not is_answer_correct("C", "A/B")
    assert not is_answer_correct("AB", "A/B")  # concat is not an alt
    assert not is_answer_correct("A,B", "A/B")  # comma is not an alt


def test_is_answer_correct_empty_and_case():
    assert not is_answer_correct("", "A")
    assert not is_answer_correct("A", "")
    assert not is_answer_correct(None, "A")
    assert is_answer_correct("patel", "Patel")
    assert is_answer_correct("FALSE", "false")


def test_score_answers_rows():
    questions = [
        {"id": "1", "correct_answer": "A"},
        {"id": "2", "correct_answer": "colour/color"},
    ]
    raw, total, rows = score_answers(
        questions=questions,
        answers_by_qid={"1": "A", "2": "color"},
    )
    assert raw == 2
    assert total == 2
    assert all(r["is_correct"] for r in rows)
