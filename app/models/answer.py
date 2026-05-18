from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Answer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_id: UUID
    question_id: UUID
    user_answer: str | None = None
    is_correct: bool | None = None
    answered_at: datetime
