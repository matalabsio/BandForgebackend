from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TestAttempt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    mock_test_id: UUID | None = None
    module: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "in_progress"
