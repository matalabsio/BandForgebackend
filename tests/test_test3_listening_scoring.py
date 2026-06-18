"""Test 3 listening mini sample — end-to-end scoring smoke (no DB)."""

from __future__ import annotations

import json
from pathlib import Path

from app.listening.evaluation import is_answer_correct, score_answers
from scripts.normalize_listening_mock import normalize

TEST3_MOCK_ID = "eb5d9416-da1f-411d-8bf9-07ae4dbc5014"
TEST3_MINI_JSON = (
    Path(__file__).resolve().parents[1] / "seed" / "admin_samples" / "listening_mini_test3.json"
)


def test_test3_mini_all_correct_answers_score_four_of_four() -> None:
    data = json.loads(TEST3_MINI_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id=TEST3_MOCK_ID,
        audio_key=f"listening/{TEST3_MOCK_ID}/part-1/full.mp3",
        allow_unsupported=False,
        part=1,
    )
    questions = [
        {**q, "id": f"q{i}"}
        for i, q in enumerate(payload["questions"], start=1)
    ]
    student_answers = {
        "q1": "B",
        "q2": "A",
        "q3": "Patel",
        "q4": "3",
    }
    raw, total, _rows = score_answers(
        questions=questions,
        answers_by_qid=student_answers,
    )
    assert total == 4
    assert raw == 4


def test_test3_mini_case_insensitive_completion() -> None:
    assert is_answer_correct("patel", "Patel")
    assert is_answer_correct("THREE", "three")
