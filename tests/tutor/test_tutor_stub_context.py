"""Unit tests for Phase 10 tutor context + stub replies (no DB)."""

from __future__ import annotations

from app.tutor.stub import stub_tutor_reply
from app.tutor.context import used_context_summary


def _pack(**overrides):
    base = {
        "current": {
            "attempt_id": "11111111-1111-1111-1111-111111111111",
            "essay": "Education is very important and a lot of students need good schools.",
            "band": 6.0,
            "ai_band": 6.0,
            "criteria": {
                "task_achievement": 6.0,
                "coherence": 5.5,
                "lexical_resource": 6.0,
                "grammar": 5.5,
            },
            "improvements": ["Develop a clearer position with specific examples."],
            "grammar_mistakes": [
                {
                    "original": "students need",
                    "correction": "students need to have",
                    "issue": "incomplete collocation",
                }
            ],
            "vocabulary_weak": [
                {"word": "good", "polarity": "weak", "alternatives": ["effective", "high-quality"]}
            ],
            "strengths": ["Clear overall topic"],
            "next_band_advice": "Extend ideas.",
        },
        "prior_attempts": [{"attempt_id": "prev", "band": 5.5, "criteria": {}, "improvements": []}],
        "learning_profile": {"target_band": 7.0, "top_weaknesses": [], "grammar_stats": {}, "vocab_stats": {}},
    }
    base.update(overrides)
    return base


def test_used_context_summary():
    summary = used_context_summary(_pack())
    assert summary["band"] == 6.0
    assert summary["has_essay"] is True
    assert summary["grammar_count"] == 1
    assert summary["vocab_weak_count"] == 1
    assert summary["prior_attempts"] == 1


def test_stub_why_band_quotes_score():
    reply = stub_tutor_reply(context_pack=_pack(), message="Why did I get Band 6?")
    assert "6.0" in reply["reply"]
    assert "Develop a clearer position" in reply["reply"]
    assert reply["focus"] == "why_band"


def test_stub_grammar_quotes_mistake():
    reply = stub_tutor_reply(
        context_pack=_pack(),
        message="Explain this grammar mistake",
        selection="students need",
    )
    assert "students need" in reply["reply"]
    assert "incomplete collocation" in reply["reply"]
    assert reply["focus"] == "grammar"


def test_stub_vocab_uses_highlights():
    reply = stub_tutor_reply(
        context_pack=_pack(),
        message="Suggest stronger vocabulary",
    )
    assert "good" in reply["reply"]
    assert "effective" in reply["reply"]


def test_stub_coherence_mentions_criterion():
    reply = stub_tutor_reply(
        context_pack=_pack(),
        message="Explain my coherence score",
    )
    assert "5.5" in reply["reply"]
    assert "6.0" in reply["reply"]


def test_stub_rewrite_uses_essay_text():
    reply = stub_tutor_reply(
        context_pack=_pack(),
        message="Rewrite this paragraph",
        selection="Education is very important",
    )
    assert "Education" in reply["reply"]
    assert reply["focus"] == "rewrite"
