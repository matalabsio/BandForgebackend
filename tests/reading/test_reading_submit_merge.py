from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from unittest.mock import patch

from app.reading import service


def _attempt() -> dict[str, object]:
    return {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "user_id": "11111111-1111-4111-8111-111111111111",
        "mock_test_id": "a0000000-0000-4000-8000-000000000001",
        "module": "reading",
        "status": "in_progress",
        "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "mock_attempt_id": None,
        "part": 1,
    }


def test_submit_preserves_non_empty_autosave_when_payload_blank():
    attempt_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    mock_test_id = UUID("a0000000-0000-4000-8000-000000000001")
    q1 = "00000000-0000-4000-8000-000000000001"
    q2 = "00000000-0000-4000-8000-000000000002"

    questions = [
        {"id": q1, "correct_answer": "TRUE", "skill_tag": "tfng", "question_type": "tfng"},
        {"id": q2, "correct_answer": "FALSE", "skill_tag": "tfng", "question_type": "tfng"},
    ]
    existing_answers = {q1: "TRUE", q2: ""}
    captured_rows: list[dict[str, object]] = []

    def _persist_bundle(**kwargs):  # type: ignore[no-untyped-def]
        captured_rows.extend(kwargs["answer_rows"])
        return {"completed_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()}

    with patch("app.reading.service.repo.get_attempt", return_value=_attempt()), patch(
        "app.reading.service.repo.list_questions_for_scoring", return_value=questions
    ), patch(
        "app.reading.service.repo.list_answers_map_for_attempt",
        return_value=existing_answers,
    ), patch(
        "app.reading.service.repo.get_mock_test",
        return_value={"id": str(mock_test_id), "title": "M01"},
    ), patch(
        "app.reading.service.persist_module_submit_bundle",
        side_effect=_persist_bundle,
    ), patch(
        "app.reading.service.build_skill_breakdown",
        return_value={},
    ), patch(
        "app.reading.service.calculate_reading_band",
        return_value=0.0,
    ):
        service.submit_attempt(
            attempt_id=attempt_id,
            user_id=user_id,
            answers=[
                {"question_id": q1, "user_answer": ""},
                {"question_id": q2, "user_answer": ""},
            ],
        )

    by_qid = {str(row["question_id"]): str(row["user_answer"]) for row in captured_rows}
    assert by_qid[q1] == "TRUE"
    assert by_qid[q2] == ""
