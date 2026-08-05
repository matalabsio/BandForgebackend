#!/usr/bin/env python3
"""Seed practice_banks.weakness_tags from dominant bank_questions.skill_tag values.

Idempotent: replaces placeholder phase0_* tags with real skill tags (tfng, etc.).
Run from backend/:  python -m scripts.seed_phase5_bank_weakness_tags
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.supabase_client import get_supabase  # noqa: E402
from app.practice.weakness import dominant_tags_from_counter, normalize_tag  # noqa: E402


def _is_placeholder(tag: str) -> bool:
    t = normalize_tag(tag)
    return (
        not t
        or t == "phase0"
        or t.startswith("phase0")
        or "_bank_" in t
        or t == "general"
    )


def main() -> int:
    sb = get_supabase()
    banks = (
        sb.table("practice_banks")
        .select("id, skill, title, weakness_tags")
        .execute()
    ).data or []
    updated = 0
    for bank in banks:
        bank_id = str(bank["id"])
        sets = (
            sb.table("practice_sets")
            .select("id")
            .eq("bank_id", bank_id)
            .execute()
        ).data or []
        set_ids = [str(s["id"]) for s in sets]
        if not set_ids:
            continue
        sections = (
            sb.table("bank_sections")
            .select("id, practice_set_id")
            .in_("practice_set_id", set_ids)
            .execute()
        ).data or []
        sec_ids = [str(s["id"]) for s in sections]
        counter: Counter[str] = Counter()
        for i in range(0, len(sec_ids), 80):
            chunk = sec_ids[i : i + 80]
            if not chunk:
                break
            qrows = (
                sb.table("bank_questions")
                .select("skill_tag, question_type")
                .in_("section_id", chunk)
                .execute()
            ).data or []
            for q in qrows:
                tag = normalize_tag(q.get("skill_tag") or q.get("question_type"))
                if tag and not _is_placeholder(tag):
                    counter[tag] += 1
        dominant = dominant_tags_from_counter(counter, min_share=0.2)
        if not dominant:
            continue
        existing = bank.get("weakness_tags") or []
        existing_norm = [normalize_tag(t) for t in existing if t]
        # Keep any non-placeholder tags already set; merge dominant
        kept = [t for t in existing_norm if not _is_placeholder(t)]
        merged: list[str] = []
        seen: set[str] = set()
        for t in dominant + kept:
            if t in seen:
                continue
            seen.add(t)
            merged.append(t)
        if merged == existing_norm and not any(_is_placeholder(t) for t in existing_norm):
            continue
        sb.table("practice_banks").update({"weakness_tags": merged}).eq(
            "id", bank_id
        ).execute()
        updated += 1
        print(f"  {bank.get('skill')} · {bank.get('title')}: {merged}")

    print(f"Updated {updated} banks")
    try:
        from app.practice.catalog import clear_hub_catalog_cache

        clear_hub_catalog_cache()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
