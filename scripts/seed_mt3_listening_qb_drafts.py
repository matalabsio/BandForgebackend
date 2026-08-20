"""Create four draft Question Bank sets from Mock 3 listening parts.

Does not publish. Does not touch MT1/MT2 hubs.

Usage::

    cd backend && source .venv/bin/activate
    python -m scripts.seed_mt3_listening_qb_drafts
    python -m scripts.seed_mt3_listening_qb_drafts --dry-run
"""

from __future__ import annotations

import argparse
import sys
from typing import Any
from uuid import UUID, uuid4

from app.admin.question_bank import CUSTOM_BANK_NUMBER, CUSTOM_BANK_TITLE, default_bank_audio_key
from app.admin.stream_videos import videos_for_skill
from app.db.supabase_client import get_supabase
from app.mock_catalog.constants import M03_MOCK_TEST_ID

TITLES = {
    1: "MT3_LT_S1",
    2: "MT3_LT_S2",
    3: "MT3_LT_S3",
    4: "MT3_LT_S4",
}


def _bank_href(skill: str, hub_id: str) -> dict[str, Any]:
    return {
        "type": "bank",
        "module": skill,
        "href": f"/practice/{skill}/{hub_id}/exercise",
    }


def _ensure_custom_bank(sb: Any, skill: str) -> str:
    rows = (
        sb.table("practice_banks")
        .select("id")
        .eq("skill", skill)
        .eq("bank_number", CUSTOM_BANK_NUMBER)
        .limit(1)
        .execute()
    ).data or []
    if rows:
        return str(rows[0]["id"])
    created = (
        sb.table("practice_banks")
        .insert(
            {
                "skill": skill,
                "bank_number": CUSTOM_BANK_NUMBER,
                "title": CUSTOM_BANK_TITLE,
                "weakness_tags": [],
            }
        )
        .execute()
    ).data or []
    if not created:
        raise RuntimeError(f"Could not create custom bank for {skill}")
    return str(created[0]["id"])


def _next_set_number(sb: Any, bank_id: str) -> int:
    rows = (
        sb.table("practice_sets")
        .select("set_number")
        .eq("bank_id", bank_id)
        .order("set_number", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return int(rows[0]["set_number"]) + 1 if rows else 1


def _next_sort_order(sb: Any) -> int:
    rows = (
        sb.table("practice_hubs")
        .select("sort_order")
        .order("sort_order", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return int(rows[0]["sort_order"] or 0) + 1 if rows else 1


def _fetch_part(sb: Any, part: int) -> list[dict[str, Any]]:
    return list(
        (
            sb.table("questions")
            .select(
                "question_number, question_type, prompt, passage_text, "
                "audio_url, options, correct_answer, skill_tag"
            )
            .eq("mock_test_id", M03_MOCK_TEST_ID)
            .eq("module", "listening")
            .eq("part", part)
            .order("question_number")
            .execute()
        ).data
        or []
    )


def _find_existing_set(sb: Any, bank_id: str, title: str) -> dict[str, Any] | None:
    rows = (
        sb.table("practice_sets")
        .select("id, status, title")
        .eq("bank_id", bank_id)
        .eq("title", title)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


def seed_part(sb: Any, *, bank_id: str, part: int, dry_run: bool) -> str:
    title = TITLES[part]
    qs = _fetch_part(sb, part)
    if len(qs) != 10:
        raise RuntimeError(f"{title}: expected 10 mock questions, got {len(qs)}")

    existing = _find_existing_set(sb, bank_id, title)
    if existing and str(existing.get("status")) == "published":
        raise RuntimeError(f"Refusing to overwrite published set {title} ({existing['id']})")

    if dry_run:
        print(f"[dry-run] {title}: {len(qs)} questions")
        return str(existing["id"]) if existing else "dry-run"

    if existing:
        set_id = str(existing["id"])
        sb.table("practice_sets").update(
            {
                "status": "draft",
                "description": f"Mock 3 listening part {part} (draft).",
            }
        ).eq("id", set_id).execute()
    else:
        created = (
            sb.table("practice_sets")
            .insert(
                {
                    "bank_id": bank_id,
                    "set_number": _next_set_number(sb, bank_id),
                    "title": title,
                    "difficulty": "medium",
                    "description": f"Mock 3 listening part {part} (draft).",
                    "status": "draft",
                }
            )
            .execute()
        ).data or []
        if not created:
            raise RuntimeError(f"Could not create {title}")
        set_id = str(created[0]["id"])

        next_sort = _next_sort_order(sb)
        slug = f"listening-mt3-s{part}-{uuid4().hex[:8]}"
        hub_rows = (
            sb.table("practice_hubs")
            .insert(
                {
                    "set_id": set_id,
                    "slug": slug,
                    "videos": videos_for_skill("listening"),
                    "practice_prompt": "",
                    "submit_config": {},
                    "estimated_min": 25,
                    "sort_order": next_sort,
                }
            )
            .execute()
        ).data or []
        if not hub_rows:
            raise RuntimeError(f"Could not create hub for {title}")
        hub_id = str(hub_rows[0]["id"])
        sb.table("practice_hubs").update(
            {"submit_config": _bank_href("listening", hub_id)}
        ).eq("id", hub_id).execute()

    audio_key = default_bank_audio_key(set_id=UUID(set_id), part=1)
    existing_sec = (
        sb.table("bank_sections")
        .select("id")
        .eq("practice_set_id", set_id)
        .eq("part", 1)
        .limit(1)
        .execute()
    ).data or []
    section_fields = {
        "title": title,
        "instructions": None,
        "audio_key": audio_key,
        "module": "listening",
        "part": 1,
        "practice_set_id": set_id,
    }
    if existing_sec:
        section_id = str(existing_sec[0]["id"])
        sb.table("bank_sections").update(
            {"title": title, "audio_key": audio_key}
        ).eq("id", section_id).execute()
    else:
        created_sec = sb.table("bank_sections").insert(section_fields).execute().data or []
        if not created_sec:
            raise RuntimeError(f"Could not create section for {title}")
        section_id = str(created_sec[0]["id"])

    sb.table("bank_questions").delete().eq("section_id", section_id).execute()
    inserts = []
    for q in qs:
        inserts.append(
            {
                "section_id": section_id,
                "question_number": int(q["question_number"]),
                "question_type": str(q.get("question_type") or "mcq"),
                "prompt": str(q.get("prompt") or ""),
                "passage_text": q.get("passage_text"),
                "options": q.get("options"),
                "correct_answer": q.get("correct_answer"),
                "skill_tag": q.get("skill_tag"),
                "audio_url": audio_key,
            }
        )
    sb.table("bank_questions").insert(inserts).execute()
    print(f"{title}: draft set {set_id} ({len(inserts)} questions) audio={audio_key}")
    return set_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sb = get_supabase()
    bank_id = _ensure_custom_bank(sb, "listening")
    ids: list[str] = []
    for part in (1, 2, 3, 4):
        ids.append(seed_part(sb, bank_id=bank_id, part=part, dry_run=args.dry_run))
    print("set_ids:", ",".join(ids))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
