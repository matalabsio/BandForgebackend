"""Unit tests for Phase 9 learning aggregate + rules (no DB)."""

from __future__ import annotations

from datetime import date

from app.learning.aggregate import build_aggregate
from app.learning.rules import apply_plan_rules, build_recommendations, monday_of


def test_aggregate_orders_skill_weaknesses_by_low_pct():
    sources = {
        "target_band": 7.0,
        "lr_scores": [
            {
                "module": "listening",
                "band": 6.0,
                "skill_breakdown": {
                    "matching": {"correct": 1, "total": 5, "pct": 20},
                    "note_completion": {"correct": 4, "total": 5, "pct": 80},
                },
            },
            {
                "module": "reading",
                "band": 6.5,
                "skill_breakdown": {
                    "inference": {"correct": 2, "total": 8, "pct": 25},
                },
            },
        ],
        "writing": [
            {
                "module": "writing",
                "band": 5.5,
                "criteria": {
                    "task_achievement": 5.5,
                    "coherence": 6.0,
                    "lexical_resource": 5.0,
                    "grammar": 5.5,
                },
                "improvements": ["Develop task response with clearer position"],
                "grammar_mistakes": [
                    {"original": "is", "correction": "are", "issue": "subject-verb agreement"},
                    {"original": "goed", "correction": "went", "issue": "verb form"},
                ],
                "vocabulary_highlights": [
                    {"word": "good", "polarity": "weak", "alternatives": ["effective"]},
                    {"word": "furthermore", "polarity": "strong", "alternatives": []},
                ],
            }
        ],
        "speaking": [],
        "diagnostic": None,
    }
    agg = build_aggregate(sources)
    assert agg["current_band"] is not None
    assert agg["module_summary"]["writing"]["latest"] == 5.5
    assert agg["skill_weaknesses"][0]["skill_tag"] == "matching"
    assert agg["vocab_stats"]["weak_count"] >= 1
    assert agg["grammar_stats"]["mistake_count"] == 2
    assert any("subject-verb" in i for i in agg["grammar_stats"]["top_issues"])
    assert len(agg["top_weaknesses"]) >= 1


def test_rules_focus_lowest_module_when_gap():
    aggregate = {
        "target_band": 7.5,
        "module_summary": {
            "listening": {"latest": 7.0, "best": 7.0, "n": 2, "gap": 0.5},
            "reading": {"latest": 5.5, "best": 5.5, "n": 1, "gap": 2.0},
            "writing": {"latest": 6.5, "best": 6.5, "n": 1, "gap": 1.0},
            "speaking": {"latest": 6.0, "best": 6.0, "n": 1, "gap": 1.5},
        },
        "top_weaknesses": [
            {
                "area": "module:reading",
                "module": "reading",
                "label": "Reading is 2.0 below target",
                "severity": 0.9,
                "evidence_count": 1,
            }
        ],
        "vocab_stats": {"weak_count": 0, "recurring_weak": [], "highlight_count": 0, "strong_count": 0, "growth_delta": 0},
        "grammar_stats": {"mistake_count": 0, "by_issue": {}, "top_issues": []},
        "source_counts": {"listening": 2, "reading": 1, "writing": 1, "speaking": 1, "diagnostic": 0},
    }
    recs = build_recommendations(aggregate)
    assert recs
    assert recs[0].module == "reading"
    assert "Reading" in recs[0].title or "below" in recs[0].reason.lower() or "weakest" in recs[0].reason.lower()

    planned = apply_plan_rules(aggregate, week_start=monday_of(date.today()))
    assert planned["study_plan"]["weeks"]
    week0 = planned["study_plan"]["weeks"][0]
    titles = [t["title"] for d in week0["days"] for t in d["tasks"]]
    assert any("Reading" in t for t in titles)
    assert planned["weekly_goals"]


def test_empty_history_onboarding_recommendations():
    aggregate = build_aggregate(
        {
            "target_band": 7.0,
            "lr_scores": [],
            "writing": [],
            "speaking": [],
            "diagnostic": None,
        }
    )
    recs = build_recommendations(aggregate)
    assert any(r.id.startswith("onboard") for r in recs)
    planned = apply_plan_rules(aggregate, week_start=date(2026, 7, 13))
    assert planned["study_plan"]["weeks"]
    assert planned["plan_week_start"] == "2026-07-13"


def test_diagnostic_seeds_missing_skills_even_with_practice_history():
    """Practice attempts must not block diagnostic bands from filling empty modules."""
    agg = build_aggregate(
        {
            "target_band": 6.5,
            "lr_scores": [
                {
                    "module": "reading",
                    "band": 5.0,
                    "skill_breakdown": {},
                },
                {
                    "module": "reading",
                    "band": 4.5,
                    "skill_breakdown": {},
                },
            ],
            "writing": [],
            "speaking": [],
            "diagnostic": {
                "attempt": {
                    "listening_band": 5.5,
                    "reading_band": 5.5,
                    "writing_band": 5.5,
                    "speaking_band": 5.5,
                },
                "evaluations": [],
            },
        }
    )
    summary = agg["module_summary"]
    assert summary["reading"]["latest"] == 5.0
    assert summary["listening"]["latest"] == 5.5
    assert summary["writing"]["latest"] == 5.5
    assert summary["speaking"]["latest"] == 5.5
    assert agg["current_band"] == 5.5
