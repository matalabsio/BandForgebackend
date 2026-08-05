"""Phase 5: match practice hubs to skill_tag weaknesses."""

from __future__ import annotations

from collections import Counter
from typing import Any

WEAK_PCT_THRESHOLD = 0.70
MAX_WEAK_TAGS = 3

_TAG_ALIASES: dict[str, str] = {
    "true_/_false_/_not_given": "tfng",
    "true/false/not_given": "tfng",
    "true_false_not_given": "tfng",
    "truefalsenotgiven": "tfng",
    "yes_/_no_/_not_given": "ynng",
    "yes/no/not_given": "ynng",
    "yes_no_not_given": "ynng",
    "map_labelling": "map_labeling",
    "matching_heading": "matching_headings",
}

# Human labels for recommendations
TAG_LABELS: dict[str, str] = {
    "tfng": "True/False/Not Given",
    "ynng": "Yes/No/Not Given",
    "matching_headings": "Matching Headings",
    "matching_information": "Matching Information",
    "matching_features": "Matching Features",
    "matching_sentence_endings": "Matching Sentence Endings",
    "matching": "Matching",
    "sentence_completion": "Sentence Completion",
    "form_completion": "Form Completion",
    "note_completion": "Note Completion",
    "map_labeling": "Map Labelling",
    "map_labelling": "Map Labelling",
    "table_completion": "Table Completion",
    "summary_completion_box": "Summary Completion",
    "flowchart_completion": "Flow-chart Completion",
    "mcq": "Multiple Choice",
}


def normalize_tag(tag: str | None) -> str:
    raw = str(tag or "").strip().lower()
    if not raw:
        return ""
    if "true" in raw and "false" in raw and "not" in raw:
        return "tfng"
    if "yes" in raw and "/no" in raw.replace(" ", "") and "not" in raw:
        return "ynng"
    t = raw.replace(" ", "_").replace("-", "_").replace("/", "_")
    while "__" in t:
        t = t.replace("__", "_")
    t = t.strip("_")
    return _TAG_ALIASES.get(t, t)


def weak_tags_from_profile(
    skill_weaknesses: list[dict[str, Any]] | None,
    *,
    threshold: float = WEAK_PCT_THRESHOLD,
    max_per_skill: int = MAX_WEAK_TAGS,
) -> dict[str, list[str]]:
    """Top weak skill_tags per module from profile skill_weaknesses."""
    by_skill: dict[str, list[tuple[float, str]]] = {}
    for row in skill_weaknesses or []:
        if not isinstance(row, dict):
            continue
        skill = str(row.get("module") or row.get("skill") or "").strip().lower()
        tag = normalize_tag(row.get("skill_tag") or row.get("tag"))
        if not skill or not tag or tag == "general":
            continue
        try:
            pct = float(row.get("pct") if row.get("pct") is not None else 1.0)
        except (TypeError, ValueError):
            pct = 1.0
        # Accept 0–1 or 0–100
        if pct > 1.0:
            pct = pct / 100.0
        if pct >= threshold:
            continue
        by_skill.setdefault(skill, []).append((pct, tag))

    out: dict[str, list[str]] = {}
    for skill, pairs in by_skill.items():
        pairs.sort(key=lambda p: p[0])  # weakest first
        seen: set[str] = set()
        tags: list[str] = []
        for _pct, tag in pairs:
            if tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
            if len(tags) >= max_per_skill:
                break
        if tags:
            out[skill] = tags
    return out


def hub_tag_overlap_score(hub_tags: list[str] | Counter[str], weak_tags: list[str]) -> int:
    """How many weak tags appear in this hub's tag multiset (presence, not count)."""
    if not weak_tags:
        return 0
    if isinstance(hub_tags, Counter):
        present = {normalize_tag(t) for t, n in hub_tags.items() if n > 0}
    else:
        present = {normalize_tag(t) for t in hub_tags if t}
    return sum(1 for t in weak_tags if normalize_tag(t) in present)


def order_pool_for_weakness(
    hub_ids: list[str],
    *,
    weak_tags: list[str] | None,
    hub_tags_by_id: dict[str, list[str]] | None,
) -> list[str]:
    """Re-order difficulty pool: tag overlap first, preserve relative order within band."""
    if not hub_ids or not weak_tags or not hub_tags_by_id:
        return list(hub_ids)

    scored: list[tuple[int, int, str]] = []
    for i, hid in enumerate(hub_ids):
        tags = hub_tags_by_id.get(str(hid)) or []
        score = hub_tag_overlap_score(tags, weak_tags)
        # Higher overlap first; stable by original index
        scored.append((-score, i, str(hid)))
    scored.sort()
    return [hid for _neg, _i, hid in scored]


def dominant_tags_from_counter(counter: Counter[str], *, min_share: float = 0.25) -> list[str]:
    """Tags that make up a meaningful share of questions."""
    total = sum(counter.values())
    if total <= 0:
        return []
    out: list[str] = []
    for tag, n in counter.most_common():
        t = normalize_tag(tag)
        if not t or t == "general":
            continue
        if n / total >= min_share or not out:
            out.append(t)
        if len(out) >= 4:
            break
    return out
