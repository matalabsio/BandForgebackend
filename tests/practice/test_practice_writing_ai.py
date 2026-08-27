"""Practice bank writing AI evaluation helpers."""

from __future__ import annotations

from app.practice.writing_ai import (
    SCORE_KIND,
    build_pending_writing_score,
    extract_writing_essay_from_answers,
    resolve_ielts_writing_part,
)
from app.writing.ai_evaluator import AI_STATUS_PENDING


def test_extract_writing_essay_from_answers():
    questions = [
        {
            "id": "q1",
            "prompt": "Describe the chart.",
            "question_type": "Task 1",
            "options": {"figure_note": "Bars show 2010–2020."},
        }
    ]
    essay, prompt, qtype, visual = extract_writing_essay_from_answers(
        {"q1": "Overall, sales rose."},
        questions,
    )
    assert essay == "Overall, sales rose."
    assert prompt == "Describe the chart."
    assert qtype == "Task 1"
    assert "Bars show" in visual


def test_build_pending_writing_score():
    score = build_pending_writing_score(
        part=2,
        question="Discuss both views.",
        essay=" ".join(["word"] * 120),
        test_title="Hub A",
    )
    assert score["kind"] == SCORE_KIND
    assert score["status"] == AI_STATUS_PENDING
    assert score["part"] == 2
    assert score["word_count"] == 120
    assert score["min_words"] == 250
    assert score["test_title"] == "Hub A"
    assert score["prompt_version"] == "v5"


def test_resolve_ielts_writing_part_task2_with_section_part_1():
    assert (
        resolve_ielts_writing_part(question_type="task2", section_part=1) == 2
    )


def test_resolve_ielts_writing_part_task1_academic():
    assert (
        resolve_ielts_writing_part(
            question_type="task1_academic", section_part=1
        )
        == 1
    )


def test_resolve_ielts_writing_part_unknown_uses_section_part():
    assert (
        resolve_ielts_writing_part(question_type="essay", section_part=2) == 2
    )
    assert (
        resolve_ielts_writing_part(question_type="essay", section_part=1) == 1
    )


def test_resolve_ielts_writing_part_title_t2_fallback():
    assert (
        resolve_ielts_writing_part(
            question_type="",
            section_part=1,
            title="MT1_WT_T2",
        )
        == 2
    )
