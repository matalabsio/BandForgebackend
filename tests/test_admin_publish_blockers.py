"""Publish readiness checks for admin mocks (Test 3 smoke scenarios)."""

from app.admin.mocks import _publish_blockers
from app.admin.schemas import ModuleSectionStatus, SectionStatus

TEST3_ID = "eb5d9416-da1f-411d-8bf9-07ae4dbc5014"


def _section_status(
    *,
    listening_parts: int = 4,
    reading_passages: int = 3,
    listening_counts: dict[int, int] | None = None,
    listening_audio: dict[int, bool] | None = None,
    reading_counts: dict[int, int] | None = None,
) -> list[ModuleSectionStatus]:
    listening_counts = listening_counts or {}
    listening_audio = listening_audio or {}
    reading_counts = reading_counts or {}
    return [
        ModuleSectionStatus(
            module="listening",
            sections=[
                SectionStatus(
                    part=p,
                    question_count=listening_counts.get(p, 0),
                    has_audio=listening_audio.get(p, False),
                )
                for p in range(1, listening_parts + 1)
            ],
        ),
        ModuleSectionStatus(
            module="reading",
            sections=[
                SectionStatus(
                    part=p,
                    question_count=reading_counts.get(p, 0),
                    has_audio=False,
                )
                for p in range(1, reading_passages + 1)
            ],
        ),
    ]


def test_test3_reading_only_blocked_when_four_listening_parts_configured():
    """Old rule allowed nothing; new rule blocks empty listening sections."""
    status = _section_status(
        listening_parts=4,
        reading_passages=3,
        reading_counts={1: 5},
    )
    blockers = _publish_blockers(
        section_status=status,
        enabled_modules={"listening", "reading"},
    )
    assert "Listening section 1: no questions" in blockers
    assert "Listening section 4: no questions" in blockers


def test_test3_smoke_ready_with_one_listening_and_one_reading():
    """Smoke test config: listening_parts=1, reading_passages=1, S1 ingested."""
    status = _section_status(
        listening_parts=1,
        reading_passages=1,
        listening_counts={1: 4},
        listening_audio={1: True},
        reading_counts={1: 5},
    )
    blockers = _publish_blockers(
        section_status=status,
        enabled_modules={"listening", "reading"},
    )
    assert blockers == []


def test_listening_missing_audio_blocks_publish():
    status = _section_status(
        listening_parts=1,
        reading_passages=1,
        listening_counts={1: 4},
        listening_audio={1: False},
        reading_counts={1: 5},
    )
    blockers = _publish_blockers(
        section_status=status,
        enabled_modules={"listening", "reading"},
    )
    assert blockers == ["Listening section 1: missing audio (R2 key)"]
