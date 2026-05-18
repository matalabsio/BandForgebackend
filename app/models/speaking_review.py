from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SpeakingReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_id: UUID
    status: str = "pending"
    human_band: Decimal | None = None
    reviewer_notes: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
