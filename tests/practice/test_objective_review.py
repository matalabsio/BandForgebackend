"""Practice bank L/R objective review helpers."""

from __future__ import annotations

from app.practice.objective_review import build_objective_review_questions


def test_build_objective_review_questions_correct_and_incorrect():
    qrows = [
        {
            "id": "q1",
            "question_number": 1,
            "question_type": "form_completion",
            "prompt": "Name",
            "correct_answer": "Alice",
        },
        {
            "id": "q2",
            "question_number": 2,
            "question_type": "form_completion",
            "prompt": "City",
            "correct_answer": "London",
        },
    ]
    answers = {"q1": "Alice", "q2": "Paris"}
    items = build_objective_review_questions(qrows, answers)
    assert len(items) == 2
    assert items[0]["is_correct"] is True
    assert items[1]["is_correct"] is False
    assert items[1]["user_answer"] == "Paris"
    assert "London" in items[1]["explanation"]


def test_build_objective_review_questions_skipped():
    qrows = [
        {
            "id": "q1",
            "question_number": 1,
            "question_type": "mcq",
            "prompt": "Pick one",
            "correct_answer": "B",
        }
    ]
    items = build_objective_review_questions(qrows, {})
    assert len(items) == 1
    assert items[0]["is_correct"] is False
    assert items[0]["user_answer"] == ""
    assert "No answer given" in items[0]["explanation"]


def test_build_objective_review_questions_uses_stored_explanation():
    qrows = [
        {
            "id": "q1",
            "question_number": 1,
            "question_type": "tfng",
            "prompt": "Statement",
            "correct_answer": "True",
            "explanation": "Custom bank explanation.",
        }
    ]
    items = build_objective_review_questions(qrows, {"q1": "False"})
    assert items[0]["explanation"] == "Custom bank explanation."
