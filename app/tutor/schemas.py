"""Request/response schemas for the writing AI tutor."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class TutorTurn(BaseModel):
    role: str = Field(description="user or assistant")
    content: str = Field(max_length=4000)


class TutorChatRequest(BaseModel):
    attempt_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    selection: str | None = Field(default=None, max_length=2000)
    turns: list[TutorTurn] = Field(default_factory=list, max_length=12)


class TutorUsedContext(BaseModel):
    attempt_id: str
    band: float | None = None
    has_essay: bool = False
    grammar_count: int = 0
    vocab_weak_count: int = 0
    prior_attempts: int = 0
    profile_weaknesses: int = 0


class TutorChatResponse(BaseModel):
    reply: str
    used_context: TutorUsedContext
    provider: str = "stub"
    stub: bool = False


class TutorSuggestion(BaseModel):
    id: str
    label: str
    message: str


class TutorSuggestionsResponse(BaseModel):
    suggestions: list[TutorSuggestion] = Field(default_factory=list)
