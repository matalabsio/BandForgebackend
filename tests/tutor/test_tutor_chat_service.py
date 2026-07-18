"""Service-level tests for tutor chat (mocked context; sync via asyncio.run)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.tutor.schemas import TutorChatRequest
from app.tutor.service import chat


def test_chat_rejects_missing_essay():
    attempt_id = uuid4()
    user_id = uuid4()
    pack = {
        "current": {
            "attempt_id": str(attempt_id),
            "essay": "",
            "band": 6.0,
            "grammar_mistakes": [],
            "vocabulary_weak": [],
        },
        "prior_attempts": [],
        "learning_profile": {},
    }
    with patch("app.tutor.service.build_context_pack", return_value=pack):
        with patch("app.tutor.service._use_stub", return_value=True):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(
                    chat(
                        user_id,
                        TutorChatRequest(attempt_id=attempt_id, message="Why this band?"),
                    )
                )
            assert exc.value.status_code == 400


def test_chat_stub_returns_contextual_reply():
    attempt_id = uuid4()
    user_id = uuid4()
    pack = {
        "current": {
            "attempt_id": str(attempt_id),
            "essay": "Some essay text about education.",
            "band": 6.5,
            "criteria": {"coherence": 6.0},
            "improvements": ["Link paragraphs more clearly."],
            "grammar_mistakes": [],
            "vocabulary_weak": [],
        },
        "prior_attempts": [],
        "learning_profile": {"target_band": 7.5},
    }
    with patch("app.tutor.service.build_context_pack", return_value=pack):
        with patch("app.tutor.service._use_stub", return_value=True):
            res = asyncio.run(
                chat(
                    user_id,
                    TutorChatRequest(
                        attempt_id=attempt_id, message="Why did I get this band?"
                    ),
                )
            )
    assert res.stub is True
    assert "6.5" in res.reply
    assert res.used_context.has_essay is True
    assert res.provider == "stub"
