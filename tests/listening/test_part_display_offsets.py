"""Listening display offsets — single metadata query per session build."""

from unittest.mock import patch
from uuid import UUID

from app.listening import repository as repo

M01 = UUID("a0000000-0000-4000-8000-000000000001")


def test_part_display_offsets_m01_four_parts():
    counts = {1: 10, 2: 10, 3: 10, 4: 10}
    with patch.object(repo, "count_questions_by_part", return_value=counts) as counter:
        offsets = repo.part_display_offsets(mock_test_id=M01)
    counter.assert_called_once()
    assert offsets == {1: 0, 2: 10, 3: 20, 4: 30}


def test_display_offset_before_part_uses_single_count_query():
    counts = {1: 13, 2: 13}
    with patch.object(repo, "count_questions_by_part", return_value=counts) as counter:
        assert repo.display_offset_before_part(mock_test_id=M01, part=1) == 0
        assert repo.display_offset_before_part(mock_test_id=M01, part=2) == 13
    assert counter.call_count == 2
