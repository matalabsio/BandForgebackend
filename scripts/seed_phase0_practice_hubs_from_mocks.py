"""Phase 0: seed published practice hubs from Mock 1 + Mock 2.

Copies each mock part into bank_sections / bank_questions, creates a
practice_set + hub, marks published, and archives empty catalogue shells.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.seed_phase0_practice_hubs_from_mocks
    python -m scripts.seed_phase0_practice_hubs_from_mocks --dry-run
"""

from __future__ import annotations

import argparse
import sys
from typing import Any
from uuid import UUID, uuid4

# Explicit Mock 1 / Mock 2 catalogue numbers only (never diagnostic / stub Mock 3).
MOCK_SPECS: list[dict[str, Any]] = [
    {"catalog_number": 1, "label": "MT1"},
    {"catalog_number": 2, "label": "MT2"},
]

# (skill, mock_label, part, difficulty, title_suffix)
# Listening 8 + Reading 5 + Writing 4 + Speaking 2 = 19 hubs
HUB_SPECS: list[tuple[str, str, int, str, str]] = [
    # Listening — Mock1 P1–4, Mock2 P1–4
    ("listening", "MT1", 1, "easy", "Part 1"),
    ("listening", "MT1", 2, "easy", "Part 2"),
    ("listening", "MT1", 3, "medium", "Part 3"),
    ("listening", "MT1", 4, "medium", "Part 4"),
    ("listening", "MT2", 1, "medium", "Part 1"),
    ("listening", "MT2", 2, "medium", "Part 2"),
    ("listening", "MT2", 3, "hard", "Part 3"),
    ("listening", "MT2", 4, "hard", "Part 4"),
    # Reading — Mock1 P1–2, Mock2 P1–3
    ("reading", "MT1", 1, "easy", "Passage 1"),
    ("reading", "MT1", 2, "medium", "Passage 2"),
    ("reading", "MT2", 1, "medium", "Passage 1"),
    ("reading", "MT2", 2, "hard", "Passage 2"),
    ("reading", "MT2", 3, "hard", "Passage 3"),
    # Writing — each task is its own hub
    ("writing", "MT1", 1, "easy", "Task 1"),
    ("writing", "MT1", 2, "medium", "Task 2"),
    ("writing", "MT2", 1, "medium", "Task 1"),
    ("writing", "MT2", 2, "hard", "Task 2"),
    # Speaking — one hub per mock (all parts in one set)
    ("speaking", "MT1", 0, "easy", "Full set"),
    ("speaking", "MT2", 0, "medium", "Full set"),
]

CUSTOM_BANK_NUMBER = 5
CUSTOM_BANK_TITLE = "Custom"
PHASE0_SLUG_PREFIX = "phase0"


def _slug(skill: str, mock_label: str, part: int) -> str:
    if part <= 0:
        return f"{PHASE0_SLUG_PREFIX}-{skill}-{mock_label.lower()}-full"
    return f"{PHASE0_SLUG_PREFIX}-{skill}-{mock_label.lower()}-p{part}"


def _title(skill: str, mock_label: str, suffix: str) -> str:
    return f"Phase0 {mock_label} {skill.title()} — {suffix}"


def _module_target_href(
    skill: str, mock_label: str, part: int, hub_id: str
) -> dict[str, Any]:
    from app.practice.module_href import module_submit_config

    catalog = 1 if mock_label.upper() == "MT1" else 2
    # Speaking full set: part <= 0 → no part
    resolved_part = None if part <= 0 else part
    return module_submit_config(
        skill=skill,
        catalog_number=catalog,
        part=resolved_part,
        hub_id=hub_id,
    )


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
                "weakness_tags": ["phase0", skill],
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


def _find_hub_by_slug(sb: Any, slug: str) -> dict[str, Any] | None:
    rows = (
        sb.table("practice_hubs")
        .select("id, set_id, slug")
        .eq("slug", slug)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


def _load_mock_map(sb: Any) -> dict[str, str]:
    """label (MT1/MT2) → mock_test_id"""
    out: dict[str, str] = {}
    for spec in MOCK_SPECS:
        rows = (
            sb.table("mock_tests")
            .select("id, title, catalog_number, is_diagnostic")
            .eq("catalog_number", spec["catalog_number"])
            .limit(1)
            .execute()
        ).data or []
        if not rows:
            raise RuntimeError(f"Mock catalog_number={spec['catalog_number']} not found")
        row = rows[0]
        if row.get("is_diagnostic"):
            raise RuntimeError(f"Refusing diagnostic mock {row.get('title')}")
        out[str(spec["label"])] = str(row["id"])
    return out


def _fetch_questions(
    sb: Any, *, mock_id: str, module: str, part: int | None
) -> list[dict[str, Any]]:
    q = (
        sb.table("questions")
        .select(
            "id, question_number, question_type, prompt, passage_text, "
            "audio_url, options, correct_answer, skill_tag, part"
        )
        .eq("mock_test_id", mock_id)
        .eq("module", module)
        .order("question_number")
    )
    if part is not None and part > 0:
        q = q.eq("part", part)
    return list(q.execute().data or [])


def _upsert_section(
    sb: Any,
    *,
    set_id: str,
    module: str,
    part: int,
    fields: dict[str, Any],
) -> str:
    existing = (
        sb.table("bank_sections")
        .select("id")
        .eq("practice_set_id", set_id)
        .eq("part", part)
        .limit(1)
        .execute()
    ).data or []
    payload = {
        "practice_set_id": set_id,
        "module": module,
        "part": part,
        "updated_at": "now()",
        **fields,
    }
    # supabase-py may not accept "now()" string for timestamptz; omit and let default
    payload.pop("updated_at", None)
    if existing:
        sec_id = str(existing[0]["id"])
        sb.table("bank_sections").update(fields).eq("id", sec_id).execute()
        return sec_id
    created = sb.table("bank_sections").insert(payload).execute().data or []
    if not created:
        raise RuntimeError(f"Failed to create section {module} part {part}")
    return str(created[0]["id"])


def _replace_questions(sb: Any, *, section_id: str, inserts: list[dict[str, Any]]) -> None:
    sb.table("bank_questions").delete().eq("section_id", section_id).execute()
    if not inserts:
        return
    rows = [{**row, "section_id": section_id} for row in inserts]
    sb.table("bank_questions").insert(rows).execute()


def _question_inserts(qs: list[dict[str, Any]], *, audio_key: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for q in qs:
        out.append(
            {
                "question_number": int(q.get("question_number") or len(out) + 1),
                "question_type": str(q.get("question_type") or "mcq"),
                "prompt": str(q.get("prompt") or ""),
                "passage_text": q.get("passage_text"),
                "options": q.get("options"),
                "correct_answer": q.get("correct_answer"),
                "skill_tag": q.get("skill_tag"),
                "audio_url": audio_key or q.get("audio_url"),
            }
        )
    return out


def _seed_one_hub(
    sb: Any,
    *,
    skill: str,
    mock_label: str,
    mock_id: str,
    part: int,
    difficulty: str,
    suffix: str,
    dry_run: bool,
) -> str:
    slug = _slug(skill, mock_label, part)
    title = _title(skill, mock_label, suffix)
    existing = _find_hub_by_slug(sb, slug)
    if existing:
        set_id = str(existing["set_id"])
        hub_id = str(existing["id"])
        print(f"  reuse hub {slug} ({hub_id})")
    else:
        if dry_run:
            print(f"  [dry-run] would create hub {slug}")
            return slug
        bank_id = _ensure_custom_bank(sb, skill)
        set_number = _next_set_number(sb, bank_id)
        set_rows = (
            sb.table("practice_sets")
            .insert(
                {
                    "bank_id": bank_id,
                    "set_number": set_number,
                    "title": title,
                    "difficulty": difficulty,
                    "description": f"Phase 0 seed from {mock_label}",
                    "status": "draft",
                }
            )
            .execute()
        ).data or []
        if not set_rows:
            raise RuntimeError(f"Could not create set for {slug}")
        set_id = str(set_rows[0]["id"])
        hub_rows = (
            sb.table("practice_hubs")
            .insert(
                {
                    "set_id": set_id,
                    "slug": slug,
                    "videos": [],
                    "practice_prompt": f"Practice {suffix} from {mock_label}.",
                    "submit_config": _module_target_href(
                        skill, mock_label, part, "pending"
                    ),
                    "estimated_min": 25,
                    "sort_order": _next_sort_order(sb),
                }
            )
            .execute()
        ).data or []
        if not hub_rows:
            raise RuntimeError(f"Could not create hub for {slug}")
        hub_id = str(hub_rows[0]["id"])
        print(f"  created hub {slug} ({hub_id})")

    if dry_run:
        return slug

    # Copy content
    if skill == "speaking" and part <= 0:
        # All speaking parts into one set (sections 1–3)
        for sp in (1, 2, 3):
            qs = _fetch_questions(sb, mock_id=mock_id, module="speaking", part=sp)
            if not qs:
                continue
            section_id = _upsert_section(
                sb,
                set_id=set_id,
                module="speaking",
                part=sp,
                fields={
                    "title": f"Speaking Part {sp}",
                    "passage_text": None,
                    "audio_key": None,
                    "instructions": None,
                },
            )
            _replace_questions(
                sb, section_id=section_id, inserts=_question_inserts(qs, audio_key=None)
            )
    else:
        qs = _fetch_questions(sb, mock_id=mock_id, module=skill, part=part)
        if not qs:
            raise RuntimeError(f"No {skill} questions for {mock_label} part {part}")

        audio_key = None
        passage = None
        instructions = None
        if skill == "listening":
            audio_key = next(
                (str(q.get("audio_url") or "").strip() for q in qs if q.get("audio_url")),
                None,
            )
            instructions = next(
                (
                    str(q.get("passage_text") or "").strip()
                    for q in qs
                    if str(q.get("passage_text") or "").strip()
                ),
                None,
            )
        elif skill == "reading":
            passage = next(
                (
                    str(q.get("passage_text") or "").strip()
                    for q in qs
                    if str(q.get("passage_text") or "").strip()
                ),
                None,
            )
        elif skill == "writing":
            passage = str(qs[0].get("prompt") or "")

        section_id = _upsert_section(
            sb,
            set_id=set_id,
            module=skill,
            part=max(part, 1),
            fields={
                "title": suffix,
                "passage_text": passage,
                "audio_key": audio_key,
                "instructions": instructions,
                "image_url": None,
            },
        )
        _replace_questions(
            sb,
            section_id=section_id,
            inserts=_question_inserts(qs, audio_key=audio_key),
        )

    # Publish + point submit_config at mock module UI (Phase 2)
    sb.table("practice_sets").update(
        {"status": "published", "difficulty": difficulty, "title": title}
    ).eq("id", set_id).execute()
    sb.table("practice_hubs").update(
        {
            "submit_config": _module_target_href(skill, mock_label, part, hub_id),
            "practice_prompt": f"Practice {suffix} from {mock_label}.",
        }
    ).eq("id", hub_id).execute()
    return slug


def _archive_empty_shells(sb: Any, *, dry_run: bool) -> int:
    """Archive practice sets with zero bank questions (keep Phase0 seeded published)."""
    sets = (
        sb.table("practice_sets")
        .select("id, title, status, practice_banks(skill)")
        .neq("status", "archived")
        .execute()
    ).data or []
    archived = 0
    for row in sets:
        set_id = str(row["id"])
        title = str(row.get("title") or "")
        if title.startswith("Phase0 "):
            continue
        sections = (
            sb.table("bank_sections")
            .select("id")
            .eq("practice_set_id", set_id)
            .execute()
        ).data or []
        q_count = 0
        for sec in sections:
            count = (
                sb.table("bank_questions")
                .select("id", count="exact")
                .eq("section_id", str(sec["id"]))
                .limit(1)
                .execute()
            )
            q_count += int(count.count or 0)
        if q_count > 0:
            continue
        print(f"  archive empty set {set_id} ({title!r})")
        if not dry_run:
            sb.table("practice_sets").update({"status": "archived"}).eq(
                "id", set_id
            ).execute()
        archived += 1
    return archived


def _verify_counts(sb: Any) -> dict[str, int]:
    from app.practice.catalog import clear_hub_catalog_cache
    from app.practice import repository

    clear_hub_catalog_cache()
    grouped = repository.list_assignable_hubs_grouped()
    return {skill: len(rows) for skill, rows in grouped.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing",
    )
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="Do not archive empty catalogue shells",
    )
    args = parser.parse_args(argv)

    from app.db.supabase_client import get_supabase

    sb = get_supabase()
    mock_map = _load_mock_map(sb)
    print("Mocks:", {k: v for k, v in mock_map.items()})

    for skill, mock_label, part, difficulty, suffix in HUB_SPECS:
        mock_id = mock_map[mock_label]
        print(f"\n[{skill}] {mock_label} part={part} difficulty={difficulty}")
        try:
            _seed_one_hub(
                sb,
                skill=skill,
                mock_label=mock_label,
                mock_id=mock_id,
                part=part,
                difficulty=difficulty,
                suffix=suffix,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            return 1

    if not args.skip_archive:
        print("\nArchiving empty catalogue shells…")
        n = _archive_empty_shells(sb, dry_run=args.dry_run)
        print(f"  archived={n}")

    if not args.dry_run:
        print("\nAssignable catalogue counts:")
        counts = _verify_counts(sb)
        for skill, n in counts.items():
            print(f"  {skill}: {n}")
        mins = {
            "listening": 6,
            "reading": 5,
            "writing": 4,
            "speaking": 2,
        }
        ok = True
        for skill, need in mins.items():
            if counts.get(skill, 0) < need:
                print(f"  FAIL: {skill} needs ≥{need}, got {counts.get(skill, 0)}")
                ok = False
        if not ok:
            return 2
        print("Phase 0 inventory OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
