"""Review agreement / override analytics for speaking & writing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.admin.review_comparison import OVERRIDE_THRESHOLD, delta_between, is_overridden, mae
from app.admin.schemas import CriterionMaeItem, ReviewAnalyticsResponse
from app.admin.speaking_band import (
    CRITERIA_KEYS as SPEAKING_KEYS,
    ai_scores_to_criteria as speaking_ai_criteria,
    compute_overall_band as speaking_overall,
)
from app.admin.writing_band import (
    CRITERIA_KEYS as WRITING_KEYS,
    ai_scores_to_criteria as writing_ai_criteria,
    compute_overall_band as writing_overall,
)
from app.db.supabase_client import get_supabase

SPEAKING_LABELS = {
    "fluency": "Fluency",
    "lexical": "Lexical",
    "grammar": "Grammar",
    "pronunciation": "Pronunciation",
}

WRITING_LABELS = {
    "task_achievement": "Task achievement",
    "coherence": "Coherence",
    "lexical_resource": "Lexical",
    "grammar": "Grammar",
}


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _fetch_completed(
    *,
    table: str,
    status_values: list[str],
    since: datetime,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table(table)
        .select(
            "id, status, human_band, human_criteria_scores, ai_scores, reviewed_at, created_at"
        )
        .in_("status", status_values)
        .order("reviewed_at", desc=True)
        .limit(500)
        .execute()
    )
    rows = result.data or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _parse_dt(row.get("reviewed_at")) or _parse_dt(row.get("created_at"))
        if ts is None or ts < since:
            continue
        out.append(row)
    return out


def _aggregate_module(
    rows: list[dict[str, Any]],
    *,
    keys: tuple[str, ...],
    labels: dict[str, str],
    ai_mapper,
    overall_fn,
) -> dict[str, Any]:
    completed = len(rows)
    with_ai = 0
    without_ai = 0
    agreed = 0
    overridden = 0
    comparable = 0
    overall_deltas: list[float] = []
    criterion_deltas: dict[str, list[float]] = {k: [] for k in keys}

    for row in rows:
        human_raw = row.get("human_criteria_scores")
        human = human_raw if isinstance(human_raw, dict) else None
        ai_raw = row.get("ai_scores")
        ai_scores = ai_raw if isinstance(ai_raw, dict) else None
        ai = ai_mapper(ai_scores)

        human_band = row.get("human_band")
        try:
            human_overall = float(human_band) if human_band is not None else None
        except (TypeError, ValueError):
            human_overall = None
        if human_overall is None and human and all(human.get(k) is not None for k in keys):
            try:
                human_overall = overall_fn(human)
            except ValueError:
                human_overall = None

        if not ai:
            without_ai += 1
            continue

        with_ai += 1
        ai_overall = overall_fn(ai)
        comparable += 1

        d_overall = delta_between(human_overall, ai_overall)
        if d_overall is not None:
            overall_deltas.append(d_overall)
            if abs(d_overall) <= OVERRIDE_THRESHOLD:
                agreed += 1

        if is_overridden(
            human_criteria=human,
            ai_criteria=ai,
            human_overall=human_overall,
            ai_overall=ai_overall,
        ):
            overridden += 1

        if human:
            for key in keys:
                if human.get(key) is None or ai.get(key) is None:
                    continue
                d = delta_between(float(human[key]), float(ai[key]))
                if d is not None:
                    criterion_deltas[key].append(d)

    return {
        "completed": completed,
        "with_ai": with_ai,
        "without_ai": without_ai,
        "agreement_rate": round(agreed / comparable, 3) if comparable else None,
        "override_rate": round(overridden / comparable, 3) if comparable else None,
        "overall_mae": mae(overall_deltas),
        "criterion_mae": [
            CriterionMaeItem(
                key=key,
                label=labels[key],
                mae=mae(criterion_deltas[key]),
                sample_count=len(criterion_deltas[key]),
            )
            for key in keys
        ],
    }


def get_review_analytics(
    *,
    module: Literal["speaking", "writing", "all"] = "all",
    days: int = 30,
) -> ReviewAnalyticsResponse:
    since = datetime.now(UTC) - timedelta(days=max(1, min(days, 365)))

    speaking_rows: list[dict[str, Any]] = []
    writing_rows: list[dict[str, Any]] = []

    if module in ("speaking", "all"):
        speaking_rows = _fetch_completed(
            table="speaking_reviews",
            status_values=["completed"],
            since=since,
        )
    if module in ("writing", "all"):
        writing_rows = _fetch_completed(
            table="writing_reviews",
            status_values=["completed"],
            since=since,
        )

    if module == "speaking":
        agg = _aggregate_module(
            speaking_rows,
            keys=SPEAKING_KEYS,
            labels=SPEAKING_LABELS,
            ai_mapper=speaking_ai_criteria,
            overall_fn=speaking_overall,
        )
        return ReviewAnalyticsResponse(module=module, days=days, **agg)

    if module == "writing":
        agg = _aggregate_module(
            writing_rows,
            keys=WRITING_KEYS,
            labels=WRITING_LABELS,
            ai_mapper=writing_ai_criteria,
            overall_fn=writing_overall,
        )
        return ReviewAnalyticsResponse(module=module, days=days, **agg)

    speak = _aggregate_module(
        speaking_rows,
        keys=SPEAKING_KEYS,
        labels=SPEAKING_LABELS,
        ai_mapper=speaking_ai_criteria,
        overall_fn=speaking_overall,
    )
    write = _aggregate_module(
        writing_rows,
        keys=WRITING_KEYS,
        labels=WRITING_LABELS,
        ai_mapper=writing_ai_criteria,
        overall_fn=writing_overall,
    )

    completed = speak["completed"] + write["completed"]
    with_ai = speak["with_ai"] + write["with_ai"]
    without_ai = speak["without_ai"] + write["without_ai"]

    # Weight rates by comparable (with_ai) counts
    def weighted_rate(a: float | None, an: int, b: float | None, bn: int) -> float | None:
        if an + bn == 0:
            return None
        av = (a or 0) * an
        bv = (b or 0) * bn
        return round((av + bv) / (an + bn), 3)

    overall_maes = [v for v in (speak["overall_mae"], write["overall_mae"]) if v is not None]
    overall_mae = (
        round(sum(overall_maes) / len(overall_maes), 3) if overall_maes else None
    )

    return ReviewAnalyticsResponse(
        module="all",
        days=days,
        completed=completed,
        with_ai=with_ai,
        without_ai=without_ai,
        agreement_rate=weighted_rate(
            speak["agreement_rate"],
            speak["with_ai"],
            write["agreement_rate"],
            write["with_ai"],
        ),
        override_rate=weighted_rate(
            speak["override_rate"],
            speak["with_ai"],
            write["override_rate"],
            write["with_ai"],
        ),
        overall_mae=overall_mae,
        criterion_mae=[
            CriterionMaeItem(
                key=f"speaking:{item.key}",
                label=f"Speaking · {item.label}",
                mae=item.mae,
                sample_count=item.sample_count,
            )
            for item in speak["criterion_mae"]
        ]
        + [
            CriterionMaeItem(
                key=f"writing:{item.key}",
                label=f"Writing · {item.label}",
                mae=item.mae,
                sample_count=item.sample_count,
            )
            for item in write["criterion_mae"]
        ],
    )
