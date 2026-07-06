"""Unit tests for founder listening JSON normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.normalize_listening_mock import normalize
from scripts.test_content_paths import (
    LISTENING_MT2_S1_JSON,
    LISTENING_MT2_S4_JSON,
    LISTENING_S2_JSON,
    LISTENING_S3_JSON,
    LISTENING_S4_JSON,
)

S2_JSON = LISTENING_S2_JSON
S3_JSON = LISTENING_S3_JSON
S4_JSON = LISTENING_S4_JSON

S2_MOCK_ID = "e0000000-0000-4000-8000-000000000002"
S3_MOCK_ID = "e0000000-0000-4000-8000-000000000003"
S4_MOCK_ID = "e0000000-0000-4000-8000-000000000004"
S2_AUDIO_KEY = "listening/bandforge-s2/part-1/full.mp3"
S3_AUDIO_KEY = "listening/bandforge-s3/part-1/full.mp3"
S4_AUDIO_KEY = "listening/bandforge-s4/part-1/full.mp3"


def test_normalize_s2_produces_ten_questions() -> None:
    data = json.loads(S2_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id=S2_MOCK_ID,
        audio_key=S2_AUDIO_KEY,
        allow_unsupported=False,
    )
    assert len(payload["questions"]) == 10
    numbers = [q["question_number"] for q in payload["questions"]]
    assert numbers == list(range(1, 11))


def test_normalize_s2_mcq_and_matching_types() -> None:
    data = json.loads(S2_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id=S2_MOCK_ID,
        audio_key=S2_AUDIO_KEY,
        allow_unsupported=False,
    )
    types = {q["question_type"] for q in payload["questions"]}
    assert types == {"mcq", "matching"}


def test_normalize_s2_matching_has_shared_options() -> None:
    data = json.loads(S2_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id=S2_MOCK_ID,
        audio_key=S2_AUDIO_KEY,
        allow_unsupported=False,
    )
    matching = [q for q in payload["questions"] if q["question_type"] == "matching"]
    assert len(matching) == 5
    assert all(q["options"] and len(q["options"]) == 7 for q in matching)
    assert matching[0]["passage_text"] is not None
    assert matching[1]["passage_text"] is None


def test_normalize_s3_produces_ten_questions() -> None:
    data = json.loads(S3_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id=S3_MOCK_ID,
        audio_key=S3_AUDIO_KEY,
        allow_unsupported=False,
    )
    assert len(payload["questions"]) == 10
    numbers = [q["question_number"] for q in payload["questions"]]
    assert numbers == list(range(1, 11))


def test_normalize_s3_question_types() -> None:
    data = json.loads(S3_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id=S3_MOCK_ID,
        audio_key=S3_AUDIO_KEY,
        allow_unsupported=False,
    )
    types = {q["question_type"] for q in payload["questions"]}
    assert types == {"mcq", "sentence_completion"}
    mcq = [q for q in payload["questions"] if q["question_type"] == "mcq"]
    assert len(mcq) == 5
    assert [q["correct_answer"] for q in mcq] == ["A", "E", "B", "E", "B"]
    completion = [
        q for q in payload["questions"] if q["question_type"] == "sentence_completion"
    ]
    assert len(completion) == 5
    assert completion[0]["correct_answer"] == "fifteen"


def test_normalize_s4_produces_ten_note_completion_questions() -> None:
    data = json.loads(S4_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id=S4_MOCK_ID,
        audio_key=S4_AUDIO_KEY,
        allow_unsupported=False,
    )
    assert len(payload["questions"]) == 10
    assert all(q["question_type"] == "sentence_completion" for q in payload["questions"])
    answers = [q["correct_answer"] for q in payload["questions"]]
    assert answers[0] == "quarter"
    assert answers[1] == "traveller/traveler"
    assert answers[3] == "Curitiba"
    assert answers[9] == "transit-oriented/transit oriented"


TEST3_MOCK_ID = "eb5d9416-da1f-411d-8bf9-07ae4dbc5014"
TEST3_MINI_JSON = (
    Path(__file__).resolve().parents[1] / "seed" / "admin_samples" / "listening_mini_test3.json"
)


def test_normalize_test3_mini_produces_four_questions() -> None:
    data = json.loads(TEST3_MINI_JSON.read_text(encoding="utf-8"))
    audio_key = f"listening/{TEST3_MOCK_ID}/part-1/full.mp3"
    payload = normalize(
        data,
        mock_id=TEST3_MOCK_ID,
        audio_key=audio_key,
        allow_unsupported=False,
        part=1,
    )
    assert len(payload["questions"]) == 4
    assert data["mock_test_id"] == TEST3_MOCK_ID
    assert all(q["audio_url"] == audio_key for q in payload["questions"])
    assert payload["questions"][0]["correct_answer"] == "B"
    assert payload["questions"][2]["correct_answer"] == "Patel"
    assert payload["questions"][3]["correct_answer"] == "three/3"


def test_normalize_mt2_s1_form_completion_produces_ten_questions() -> None:
    data = json.loads(LISTENING_MT2_S1_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id="a0000000-0000-4000-8000-000000000002",
        audio_key="listening/m02/part-1/full.mp3",
        allow_unsupported=False,
    )
    assert len(payload["questions"]) == 10
    assert all(q["question_type"] == "form_completion" for q in payload["questions"])
    first = payload["questions"][0]
    assert first["passage_text"] is not None
    assert "BROOKSIDE LETTINGS" in first["passage_text"]
    assert "@@form_title@@" in first["passage_text"]
    assert first["correct_answer"] == "Whitfield"
    assert payload["questions"][1]["passage_text"] is None


def test_normalize_mt2_s4_note_completion_produces_ten_questions() -> None:
    data = json.loads(LISTENING_MT2_S4_JSON.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id="a0000000-0000-4000-8000-000000000002",
        audio_key="listening/m02/part-4/full.mp3",
        allow_unsupported=False,
        part=4,
        renumber_per_part=True,
    )
    assert len(payload["questions"]) == 10
    assert all(q["question_type"] == "note_completion" for q in payload["questions"])
    first = payload["questions"][0]
    assert first["question_number"] == 1
    assert "DENDROCHRONOLOGY" in (first["passage_text"] or "")
    assert "@@notes_title@@" in (first["passage_text"] or "")
    assert "@@section@@31-33|The basic principle" in (first["passage_text"] or "")
    assert "tree's ___" in first["prompt"]
    assert first["correct_answer"] == "age"
    assert payload["questions"][9]["correct_answer"] == "tropical"
