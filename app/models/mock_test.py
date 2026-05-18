from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MockTest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None = None
    is_published: bool = False
    created_at: datetime
