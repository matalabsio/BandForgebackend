"""speaking_responses.question_id must accept bank_questions UUIDs (no FK to questions)."""

from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260827120000_speaking_responses_bank_question_fk.sql"
)


def test_speaking_responses_drops_questions_fk_for_bank_practice():
    sql = MIGRATION.read_text()
    assert "DROP CONSTRAINT IF EXISTS speaking_responses_question_id_fkey" in sql
    assert "bank_questions" in sql
    assert "speaking_manifest" in sql
