from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Question(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mock_test_id: UUID
    module: str
    question_type: str
    question_number: int
    prompt: str
    passage_text: str | None = None
    audio_url: str | None = None
    options: list[dict[str, Any]] | None = None
    correct_answer: str | None = None
    skill_tag: str | None = None
    created_at: datetime
