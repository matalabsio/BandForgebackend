"""Gap-based skill sequencing for personalized study plans (mirrors frontend/lib/plan-preview.ts)."""

from __future__ import annotations

from typing import Literal

SkillKey = Literal["listening", "reading", "writing", "speaking"]
SkillBands = dict[str, float | None]
SkillGapMap = dict[str, float]
SkillDayAllocation = dict[str, int]
SessionPathKind = Literal["foundation", "mixed"]

HARD_GAP_THRESHOLD = 1.0
GAP_FLOOR = 0.5
FOUNDATION_BAND_THRESHOLD = 6.0
MAX_RUN = 2

SKILL_ORDER: list[str] = ["listening", "reading", "writing", "speaking"]
HARD_POOL: list[str] = ["writing", "speaking"]
EASY_POOL: list[str] = ["listening", "reading"]
MIXED_TEMPLATE: list[str] = ["H", "E", "H", "H", "E"]

SKILL_LABEL = {
    "listening": "Listening",
    "reading": "Reading",
    "writing": "Writing",
    "speaking": "Speaking",
}


def skill_gap(band: float | None, target: float) -> float:
    if band is None or band <= 0:
        return max(target, GAP_FLOOR)
    return max(target - band, GAP_FLOOR)


def raw_skill_gap(band: float | None, target: float) -> float:
    if band is None or band <= 0:
        return target
    return max(0.0, target - band)


def classify_skill(gap: float) -> Literal["hard", "easy"]:
    return "hard" if gap >= HARD_GAP_THRESHOLD else "easy"


def classify_skills(bands: SkillBands, target: float) -> dict[str, str]:
    gaps = gap_map(bands, target, use_floor=True)
    return {key: classify_skill(gaps[key]) for key in SKILL_ORDER}


def is_foundation_path(bands: SkillBands) -> bool:
    for key in SKILL_ORDER:
        band = bands.get(key)
        if band is None or band <= 0:
            return False
        if band >= FOUNDATION_BAND_THRESHOLD:
            return False
    return True


def gap_map(bands: SkillBands, target: float, *, use_floor: bool) -> SkillGapMap:
    fn = skill_gap if use_floor else raw_skill_gap
    return {key: fn(bands.get(key), target) for key in SKILL_ORDER}


def allocate_days(gaps: SkillGapMap, total_days: int) -> SkillDayAllocation:
    total_gap = sum(gaps.get(k, 0) for k in SKILL_ORDER)
    if total_gap <= 0 or total_days <= 0:
        even = total_days // len(SKILL_ORDER)
        allocated: SkillDayAllocation = {k: even for k in SKILL_ORDER}
        remain = total_days - even * len(SKILL_ORDER)
        for key in SKILL_ORDER:
            if remain <= 0:
                break
            allocated[key] += 1
            remain -= 1
        return allocated

    quotas = [(key, (gaps[key] / total_gap) * total_days) for key in SKILL_ORDER]
    floors = [(key, int(q // 1), q - int(q // 1)) for key, q in quotas]
    allocated = {key: floor for key, floor, _ in floors}
    remain = total_days - sum(floor for _, floor, _ in floors)
    sorted_floors = sorted(floors, key=lambda row: row[2], reverse=True)
    i = 0
    while remain > 0:
        key = sorted_floors[i % len(sorted_floors)][0]
        allocated[key] += 1
        remain -= 1
        i += 1
    return allocated


def _pick_from_pool(
    pool: list[str],
    gaps: SkillGapMap,
    last_skill: str | None,
    consecutive: int,
    alternation: dict[str, int],
) -> str:
    eligible = [s for s in pool if not (last_skill == s and consecutive >= MAX_RUN)]
    candidates = eligible if eligible else list(pool)
    candidates.sort(key=lambda s: (-gaps[s], alternation[s]))
    pick = candidates[0]
    alternation[pick] += 1
    return pick


def build_session_sequence(
    bands: SkillBands,
    target: float,
) -> tuple[SessionPathKind, list[str]]:
    if is_foundation_path(bands):
        return "foundation", list(SKILL_ORDER)

    gaps = gap_map(bands, target, use_floor=True)
    order: list[str] = []
    last_skill: str | None = None
    consecutive = 0
    alternation = {k: 0 for k in SKILL_ORDER}

    for slot in MIXED_TEMPLATE:
        pool = HARD_POOL if slot == "H" else EASY_POOL
        pick = _pick_from_pool(pool, gaps, last_skill, consecutive, alternation)
        if pick == last_skill:
            consecutive += 1
        else:
            last_skill = pick
            consecutive = 1
        order.append(pick)

    return "mixed", order


def build_primary_focus_queue(allocation: SkillDayAllocation) -> list[str]:
    """Expand day counts into a length-N queue, interleaving larger allocations first."""
    total = sum(allocation.get(k, 0) for k in SKILL_ORDER)
    if total <= 0:
        return []

    remaining = {k: allocation.get(k, 0) for k in SKILL_ORDER}
    queue: list[str] = []
    while len(queue) < total:
        candidates = [k for k in SKILL_ORDER if remaining[k] > 0]
        if not candidates:
            break
        candidates.sort(key=lambda k: (-remaining[k], SKILL_ORDER.index(k)))
        pick = candidates[0]
        queue.append(pick)
        remaining[pick] -= 1
    return queue


def focus_skills_from_gaps(raw_gaps: SkillGapMap) -> list[str]:
    ranked = sorted(SKILL_ORDER, key=lambda k: raw_gaps.get(k, 0), reverse=True)
    top_gap = raw_gaps.get(ranked[0], 0)
    if top_gap <= 0:
        return []
    tied = [k for k in ranked if raw_gaps.get(k, 0) == top_gap]
    if len(tied) >= 2:
        return tied[:2]
    if len(ranked) > 1:
        second_gap = raw_gaps.get(ranked[1], 0)
        if second_gap > 0 and abs(top_gap - second_gap) <= 0.5:
            return [ranked[0], ranked[1]]
    return [ranked[0]]


def focus_label(skills: list[str]) -> str:
    if not skills:
        return "Balanced across all skills"
    return " & ".join(SKILL_LABEL[s] for s in skills)
