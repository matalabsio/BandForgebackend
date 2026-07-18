"""JSON consistency and stub determinism for writing evaluation."""

from __future__ import annotations

import asyncio

from app.diagnostic.evaluation_schemas import (
    EvaluationResponse,
    build_stub_evaluation,
)
from app.writing.golden import load_golden_manifest
from app.writing.providers.evaluation_call import (
    coerce_parsed_evaluation,
    parse_json_content,
)
from app.writing.providers.stub_eval import StubWritingProvider


REQUIRED_KEYS = {
    "overall_band",
    "task_achievement",
    "coherence",
    "lexical_resource",
    "grammar",
    "strengths",
    "weaknesses",
    "improvement_tips",
}


def test_stub_evaluation_validates_against_schema():
    for entry in load_golden_manifest()[:3]:
        ev = build_stub_evaluation(task_part=entry.task_part, essay=entry.essay)
        assert isinstance(ev, EvaluationResponse)
        dumped = ev.model_dump()
        assert REQUIRED_KEYS.issubset(dumped.keys())


def test_stub_provider_deterministic_for_same_essay():
    entry = load_golden_manifest()[0]

    async def run_once():
        provider = StubWritingProvider(task_part=entry.task_part, essay=entry.essay)
        content, _raw = await provider.chat_json(system="s", user="u")
        parsed = coerce_parsed_evaluation(
            parse_json_content(content),
            words=50,
            task_part=entry.task_part,
        )
        return EvaluationResponse.model_validate(parsed)

    a = asyncio.run(run_once())
    b = asyncio.run(run_once())
    assert a.overall_band == b.overall_band
    assert a.task_achievement == b.task_achievement
    assert a.coherence == b.coherence
    assert a.lexical_resource == b.lexical_resource
    assert a.grammar == b.grammar


def test_coerce_roundtrip_preserves_required_keys():
    ev = build_stub_evaluation(task_part=2, essay="A sample essay about technology and society.")
    raw = ev.model_dump()
    coerced = coerce_parsed_evaluation(raw, words=40, task_part=2)
    validated = EvaluationResponse.model_validate(coerced)
    assert REQUIRED_KEYS.issubset(validated.model_dump().keys())
