"""Aggregate eval signals into learning-profile fields."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.learning.schemas import (
    GrammarStats,
    ModuleBandSummary,
    SourceCounts,
    VocabStats,
    WeaknessItem,
)


def _round_half(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 2) / 2


def _module_from_scores(
    rows: list[dict[str, Any]],
    module: str,
    target: float | None,
) -> ModuleBandSummary:
    bands = [float(r["band"]) for r in rows if r.get("module") == module and r.get("band") is not None]
    if not bands:
        return ModuleBandSummary()
    latest = bands[0]
    best = max(bands)
    gap = None if target is None else _round_half(target - latest)
    return ModuleBandSummary(latest=latest, best=best, n=len(bands), gap=gap)


def _skill_weaknesses(lr_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate L/R skill_tag pct across attempts (lower pct = weaker)."""
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"correct": 0.0, "total": 0.0, "n": 0})
    for row in lr_scores:
        module = str(row.get("module") or "")
        breakdown = row.get("skill_breakdown") or {}
        if not isinstance(breakdown, dict):
            continue
        for tag, stats in breakdown.items():
            if not isinstance(stats, dict):
                continue
            key = f"{module}:{tag}"
            correct = float(stats.get("correct") or 0)
            total = float(stats.get("total") or 0)
            if total <= 0:
                continue
            totals[key]["correct"] += correct
            totals[key]["total"] += total
            totals[key]["n"] += 1
            totals[key]["module"] = module  # type: ignore[assignment]
            totals[key]["tag"] = tag  # type: ignore[assignment]

    out: list[dict[str, Any]] = []
    for key, agg in totals.items():
        total = agg["total"]
        if total <= 0:
            continue
        pct = (agg["correct"] / total) * 100.0
        out.append(
            {
                "key": key,
                "module": agg.get("module"),
                "skill_tag": agg.get("tag"),
                "pct": round(pct, 1),
                "correct": int(agg["correct"]),
                "total": int(total),
                "attempts": int(agg["n"]),
            }
        )
    out.sort(key=lambda x: (x["pct"], -x["total"]))
    return out


def _criterion_trends(writing: list[dict[str, Any]], speaking: list[dict[str, Any]]) -> dict[str, Any]:
    def series(rows: list[dict[str, Any]], keys: list[str]) -> dict[str, Any]:
        buckets: dict[str, list[float]] = {k: [] for k in keys}
        for row in rows[:8]:
            criteria = row.get("criteria") or {}
            if not isinstance(criteria, dict):
                continue
            for k in keys:
                val = criteria.get(k)
                if val is None:
                    continue
                try:
                    buckets[k].append(float(val))
                except (TypeError, ValueError):
                    continue
        result: dict[str, Any] = {}
        for k, vals in buckets.items():
            if not vals:
                continue
            result[k] = {
                "avg": round(sum(vals) / len(vals), 2),
                "latest": vals[0],
                "series": vals,
                "n": len(vals),
            }
        return result

    return {
        "writing": series(
            writing,
            ["task_achievement", "coherence", "lexical_resource", "grammar"],
        ),
        "speaking": series(
            speaking,
            ["fluency", "lexical", "grammar", "pronunciation"],
        ),
    }


def _vocab_stats(
    writing: list[dict[str, Any]],
    speaking: list[dict[str, Any]],
) -> VocabStats:
    weak_words: Counter[str] = Counter()
    strong = 0
    weak = 0
    total = 0
    recent = (writing[:5] + speaking[:5])
    prior = (writing[5:10] + speaking[5:10])

    def consume(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
        t = s = w = 0
        for row in rows:
            for item in row.get("vocabulary_highlights") or []:
                if not isinstance(item, dict):
                    continue
                t += 1
                polarity = str(item.get("polarity") or "weak").lower()
                word = str(item.get("word") or "").strip().lower()
                if polarity == "strong":
                    s += 1
                else:
                    w += 1
                    if word:
                        weak_words[word] += 1
        return t, s, w

    total, strong, weak = consume(recent)
    prior_total, _, _ = consume(prior)
    return VocabStats(
        highlight_count=total,
        weak_count=weak,
        strong_count=strong,
        recurring_weak=[w for w, _ in weak_words.most_common(5)],
        growth_delta=total - prior_total,
    )


def _grammar_stats(writing: list[dict[str, Any]], speaking: list[dict[str, Any]]) -> GrammarStats:
    by_issue: Counter[str] = Counter()
    count = 0
    for row in writing[:10]:
        for mist in row.get("grammar_mistakes") or []:
            if not isinstance(mist, dict):
                continue
            count += 1
            issue = str(mist.get("issue") or "grammar").strip() or "grammar"
            by_issue[issue.lower()] += 1
    for row in speaking[:10]:
        for pattern in row.get("recurring_patterns") or []:
            text = str(pattern).strip()
            if not text:
                continue
            count += 1
            # Bucket speaking GRA patterns loosely
            key = text[:48].lower()
            by_issue[key] += 1
    return GrammarStats(
        mistake_count=count,
        by_issue=dict(by_issue.most_common(12)),
        top_issues=[i for i, _ in by_issue.most_common(5)],
    )


def _top_weaknesses(
    skill_weaknesses: list[dict[str, Any]],
    criterion_trends: dict[str, Any],
    writing: list[dict[str, Any]],
    speaking: list[dict[str, Any]],
    module_summary: dict[str, ModuleBandSummary],
    target: float | None,
) -> list[WeaknessItem]:
    items: list[WeaknessItem] = []

    for sw in skill_weaknesses[:6]:
        pct = float(sw["pct"])
        if pct >= 70:
            continue
        severity = max(0.0, min(1.0, (70 - pct) / 70))
        items.append(
            WeaknessItem(
                area=f"skill:{sw['skill_tag']}",
                module=str(sw["module"]),
                label=f"{str(sw['module']).title()} · {sw['skill_tag']} ({pct:.0f}%)",
                severity=round(severity, 2),
                evidence_count=int(sw.get("attempts") or 1),
            )
        )

    for module, trends in criterion_trends.items():
        if not isinstance(trends, dict):
            continue
        for criterion, stats in trends.items():
            if not isinstance(stats, dict):
                continue
            avg = stats.get("avg")
            if avg is None:
                continue
            try:
                avg_f = float(avg)
            except (TypeError, ValueError):
                continue
            floor = (target - 1.0) if target is not None else 6.0
            if avg_f >= floor:
                continue
            severity = max(0.0, min(1.0, (floor - avg_f) / 3.0))
            items.append(
                WeaknessItem(
                    area=f"criterion:{criterion}",
                    module=str(module),
                    label=f"{str(module).title()} · {criterion.replace('_', ' ')} (~{avg_f:.1f})",
                    severity=round(severity, 2),
                    evidence_count=int(stats.get("n") or 1),
                )
            )

    for row in (writing[:3] + speaking[:3]):
        for tip in (row.get("improvements") or [])[:2]:
            text = str(tip).strip()
            if not text:
                continue
            items.append(
                WeaknessItem(
                    area="feedback",
                    module=str(row.get("module") or "writing"),
                    label=text[:120],
                    severity=0.45,
                    evidence_count=1,
                )
            )

    # Module-level gap
    if target is not None:
        for mod, summary in module_summary.items():
            if summary.latest is None:
                continue
            gap = target - summary.latest
            if gap >= 0.5:
                items.append(
                    WeaknessItem(
                        area=f"module:{mod}",
                        module=mod,
                        label=f"{mod.title()} is {gap:.1f} below target",
                        severity=min(1.0, gap / 2.0),
                        evidence_count=summary.n,
                    )
                )

    # Dedupe by label, keep highest severity
    by_label: dict[str, WeaknessItem] = {}
    for item in items:
        prev = by_label.get(item.label)
        if prev is None or item.severity > prev.severity:
            by_label[item.label] = item
    ranked = sorted(by_label.values(), key=lambda w: (-w.severity, -w.evidence_count))
    return ranked[:8]


def build_aggregate(sources: dict[str, Any]) -> dict[str, Any]:
    target = sources.get("target_band")
    if target is not None:
        try:
            target = float(target)
        except (TypeError, ValueError):
            target = None

    lr = list(sources.get("lr_scores") or [])
    writing = list(sources.get("writing") or [])
    speaking = list(sources.get("speaking") or [])
    diagnostic = sources.get("diagnostic")

    # Seed empty module history from diagnostic when thin
    if diagnostic and isinstance(diagnostic, dict):
        attempt = diagnostic.get("attempt") or {}
        thin = len(lr) + len(writing) + len(speaking) < 2
        if thin and attempt:
            for mod, key in (
                ("listening", "listening_band"),
                ("reading", "reading_band"),
                ("writing", "writing_band"),
                ("speaking", "speaking_band"),
            ):
                band = attempt.get(key)
                if band is None:
                    continue
                try:
                    bf = float(band)
                except (TypeError, ValueError):
                    continue
                bucket = (
                    lr if mod in ("listening", "reading")
                    else writing if mod == "writing"
                    else speaking
                )
                if not any(r.get("module") == mod for r in bucket):
                    bucket.append(
                        {
                            "module": mod,
                            "band": bf,
                            "criteria": {},
                            "improvements": [],
                            "grammar_mistakes": [],
                            "vocabulary_highlights": [],
                            "skill_breakdown": {},
                            "from_diagnostic": True,
                        }
                    )
            # Prefer feedback criteria from diagnostic AI evals
            for ev in diagnostic.get("evaluations") or []:
                if not isinstance(ev, dict):
                    continue
                etype = str(ev.get("evaluation_type") or "")
                criteria = ev.get("criteria_scores") if isinstance(ev.get("criteria_scores"), dict) else {}
                feedback = ev.get("feedback") if isinstance(ev.get("feedback"), dict) else {}
                if etype == "writing" and writing:
                    for row in writing:
                        if row.get("from_diagnostic") and not row.get("criteria"):
                            row["criteria"] = criteria
                            row["improvements"] = list(feedback.get("improvements") or feedback.get("weaknesses") or [])
                            row["grammar_mistakes"] = list(feedback.get("grammar_mistakes") or [])
                            row["vocabulary_highlights"] = list(feedback.get("vocabulary_highlights") or [])
                            break

    module_summary = {
        "listening": _module_from_scores(lr, "listening", target),
        "reading": _module_from_scores(lr, "reading", target),
        "writing": _module_from_scores(writing, "writing", target),
        "speaking": _module_from_scores(speaking, "speaking", target),
    }

    skill_weaknesses = _skill_weaknesses(lr)
    criterion_trends = _criterion_trends(writing, speaking)
    vocab = _vocab_stats(writing, speaking)
    grammar = _grammar_stats(writing, speaking)
    top_weaknesses = _top_weaknesses(
        skill_weaknesses,
        criterion_trends,
        writing,
        speaking,
        module_summary,
        target,
    )

    latest_bands = [
        s.latest for s in module_summary.values() if s.latest is not None
    ]
    current_band = _round_half(sum(latest_bands) / len(latest_bands)) if latest_bands else None

    source_counts = SourceCounts(
        listening=sum(1 for r in lr if r.get("module") == "listening" and not r.get("from_diagnostic")),
        reading=sum(1 for r in lr if r.get("module") == "reading" and not r.get("from_diagnostic")),
        writing=sum(1 for r in writing if not r.get("from_diagnostic")),
        speaking=sum(1 for r in speaking if not r.get("from_diagnostic")),
        diagnostic=1 if diagnostic else 0,
    )

    return {
        "current_band": current_band,
        "target_band": target,
        "module_summary": {k: v.model_dump() for k, v in module_summary.items()},
        "criterion_trends": criterion_trends,
        "skill_weaknesses": skill_weaknesses,
        "top_weaknesses": [w.model_dump() for w in top_weaknesses],
        "vocab_stats": vocab.model_dump(),
        "grammar_stats": grammar.model_dump(),
        "source_counts": source_counts.model_dump(),
    }
