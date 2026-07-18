from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

TestModule = Literal["reading", "listening", "writing", "speaking"]


class TestSummary(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    listening_question_count: int | None = None
    listening_duration_minutes: int = 30
    reading_question_count: int | None = None
    reading_duration_minutes: int = 60


class QuestionPublic(BaseModel):
    id: UUID
    question_number: int
    question_type: str
    prompt: str
    options: list[dict[str, str]] | None = None
    skill_tag: str | None = None


class QuestionsResponse(BaseModel):
    test: TestSummary
    module: TestModule
    passage_text: str | None = None
    audio_urls: list[str] = Field(default_factory=list)
    questions: list[QuestionPublic]


class StartAttemptRequest(BaseModel):
    module: TestModule
    """When true, abandon any in-progress attempt and create a new one."""
    force_new: bool = False
    skill_context: TestModule | None = None


class StartAttemptResponse(BaseModel):
    attempt_id: UUID
    started_at: datetime
    status: str
    module: TestModule
    resumed: bool = False


class AnswerSubmission(BaseModel):
    question_id: UUID
    user_answer: str


class SubmitAnswersRequest(BaseModel):
    answers: list[AnswerSubmission] = Field(min_length=1)


class SubmitAnswersResponse(BaseModel):
    attempt_id: UUID
    status: str
    submitted_at: datetime
    answer_count: int
    late_submission: bool = False
