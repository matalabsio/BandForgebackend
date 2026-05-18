from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ModuleScore(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_id: UUID
    module: str
    raw_score: int | None = None
    band: Decimal | None = None
    scored_at: datetime | None = None
