"""Reading global question numbering (IELTS-style 1–40 across passages)."""

from unittest.mock import patch
from uuid import UUID

from app.reading import repository as repo

M01 = UUID("a0000000-0000-4000-8000-000000000001")


def test_display_offset_passage_two_starts_at_14():
    with patch.object(
        repo,
        "count_questions_by_part",
        return_value={1: 13, 2: 13},
    ):
        assert repo.display_offset_before_part(mock_test_id=M01, part=1) == 0
        assert repo.display_offset_before_part(mock_test_id=M01, part=2) == 13


def test_display_offset_single_passage():
    with patch.object(repo, "count_questions_by_part", return_value={1: 13}):
        assert repo.display_offset_before_part(mock_test_id=M01, part=1) == 0
