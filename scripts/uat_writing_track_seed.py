"""Phase 4B.0 — reversible Writing track UAT seed harness (local/staging only).

Creates a tiny identifiable inventory for Phase 4B filter UAT:

  Academic T1  (task1_academic, exam_module=academic)
  Both T2      (task2, exam_module=both)
  GT T1        (task1_general, exam_module=general_training)
  Academic mock (mock_tests.exam_module=academic)
  GT mock      (mock_tests.exam_module=general_training)

Attaches those rows to writing_skill via program_content_items.
Does NOT activate writing_skill.

Safety: refuses to run against shared cloud / production hosts.
Cleanup deletes ONLY records with these deterministic IDs / marker.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.db.supabase_client import get_supabase

# ---------------------------------------------------------------------------
# Identity / markers
# ---------------------------------------------------------------------------

UAT_MARKER = "UAT_PHASE_4B_SEED"
UAT_TITLE_PREFIX = "[UAT4B]"
UAT_BANK_NUMBER = 90
UAT_BANK_TITLE = "UAT4B Writing"

# Deterministic UUIDs (do not collide with seeded catalog UUIDs).
IDS = {
    "bank": UUID("e4b04b00-0000-4000-a000-000000000090"),
    "set_academic_t1": UUID("e4b04b00-0000-4000-a000-000000000001"),
    "set_both_t2": UUID("e4b04b00-0000-4000-a000-000000000002"),
    "set_gt_t1": UUID("e4b04b00-0000-4000-a000-000000000003"),
    "hub_academic_t1": UUID("e4b04b00-0000-4000-a000-000000000011"),
    "hub_both_t2": UUID("e4b04b00-0000-4000-a000-000000000012"),
    "hub_gt_t1": UUID("e4b04b00-0000-4000-a000-000000000013"),
    "section_academic_t1": UUID("e4b04b00-0000-4000-a000-000000000021"),
    "section_both_t2": UUID("e4b04b00-0000-4000-a000-000000000022"),
    "section_gt_t1": UUID("e4b04b00-0000-4000-a000-000000000023"),
    "q_academic_t1": UUID("e4b04b00-0000-4000-a000-000000000031"),
    "q_both_t2": UUID("e4b04b00-0000-4000-a000-000000000032"),
    "q_gt_t1": UUID("e4b04b00-0000-4000-a000-000000000033"),
    "mock_academic": UUID("e4b04b00-0000-4000-a000-000000000041"),
    "mock_gt": UUID("e4b04b00-0000-4000-a000-000000000042"),
    "mock_q_academic": UUID("e4b04b00-0000-4000-a000-000000000043"),
    "mock_q_gt": UUID("e4b04b00-0000-4000-a000-000000000044"),
    "pci_academic_t1": UUID("e4b04b00-0000-4000-a000-000000000051"),
    "pci_both_t2": UUID("e4b04b00-0000-4000-a000-000000000052"),
    "pci_gt_t1": UUID("e4b04b00-0000-4000-a000-000000000053"),
    "pci_mock_academic": UUID("e4b04b00-0000-4000-a000-000000000054"),
    "pci_mock_gt": UUID("e4b04b00-0000-4000-a000-000000000055"),
}

BLOCKED_HOST_FRAGMENTS = (
    "nkwtxkhtsclyakympbno.supabase.co",  # shared live project
    "supabase.co",  # any remote Supabase cloud host
)

PROMPTS = {
    "academic_t1": (
        f"{UAT_TITLE_PREFIX} Synthetic Academic Task 1. "
        "Describe the chart below in at least 150 words."
    ),
    "both_t2": (
        f"{UAT_TITLE_PREFIX} Synthetic Task 2 essay suitable for both modules. "
        "Discuss both views and give your opinion (min 250 words)."
    ),
    "gt_t1": (
        f"{UAT_TITLE_PREFIX} Synthetic General Training letter. "
        "Write a letter to a company about a damaged online order."
    ),
}


class UnsafeDatabaseError(RuntimeError):
    """Raised when the configured Supabase target is not a safe UAT DB."""


def assert_safe_uat_database(*, settings: Any | None = None) -> str:
    """Refuse shared cloud / production hosts. Returns the verified URL."""
    settings = settings or get_settings()
    url = str(getattr(settings, "supabase_url", "") or "").strip().lower()
    if not url:
        raise UnsafeDatabaseError("SUPABASE_URL is empty.")

    # Prefer explicit local markers.
    is_loopback = any(
        h in url for h in ("127.0.0.1", "localhost", "0.0.0.0", "host.docker.internal")
    )
    local_flag = str(
        getattr(settings, "supabase_local", None)
        or __import__("os").environ.get("SUPABASE_LOCAL", "")
    ).strip().lower() in {"1", "true", "yes", "on"}

    if any(frag in url for frag in BLOCKED_HOST_FRAGMENTS):
        raise UnsafeDatabaseError(
            f"Refusing UAT seed against remote Supabase host: {url}. "
            "Use local Supabase (.env.local) only."
        )

    if not (is_loopback or local_flag):
        raise UnsafeDatabaseError(
            f"Cannot establish UAT safety for SUPABASE_URL={url}. "
            "Require loopback URL or SUPABASE_LOCAL=true."
        )

    app_env = str(getattr(settings, "app_env", "") or "").strip().lower()
    if app_env == "production":
        raise UnsafeDatabaseError("APP_ENV=production — refusing UAT seed.")

    return str(getattr(settings, "supabase_url"))


def _sb():
    assert_safe_uat_database()
    return get_supabase()


def _title(name: str) -> str:
    return f"{UAT_TITLE_PREFIX} {name}"


def inventory_snapshot(sb: Any | None = None) -> dict[str, Any]:
    sb = sb or _sb()
    set_ids = [
        str(IDS["set_academic_t1"]),
        str(IDS["set_both_t2"]),
        str(IDS["set_gt_t1"]),
    ]
    mock_ids = [str(IDS["mock_academic"]), str(IDS["mock_gt"])]
    sets = (
        sb.table("practice_sets")
        .select("id, title, exam_module, status, description")
        .in_("id", set_ids)
        .execute()
    ).data or []
    mocks = (
        sb.table("mock_tests")
        .select("id, title, exam_module, status")
        .in_("id", mock_ids)
        .execute()
    ).data or []
    pci = (
        sb.table("program_content_items")
        .select("id, item_type, item_id, exam_module")
        .in_(
            "id",
            [
                str(IDS["pci_academic_t1"]),
                str(IDS["pci_both_t2"]),
                str(IDS["pci_gt_t1"]),
                str(IDS["pci_mock_academic"]),
                str(IDS["pci_mock_gt"]),
            ],
        )
        .execute()
    ).data or []
    plan = (
        sb.table("plans")
        .select("slug, is_active")
        .eq("slug", "writing_skill")
        .limit(1)
        .execute()
    ).data or []
    return {
        "supabase_url": assert_safe_uat_database(),
        "sets": sets,
        "mocks": mocks,
        "program_content_items": pci,
        "writing_skill": plan[0] if plan else None,
    }


def _ensure_writing_skill_inactive(sb: Any) -> str:
    rows = (
        sb.table("plans")
        .select("id, slug, is_active")
        .eq("slug", "writing_skill")
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise RuntimeError("writing_skill plan missing from local DB.")
    if rows[0].get("is_active") is True:
        raise RuntimeError(
            "writing_skill.is_active is unexpectedly true — refusing to seed."
        )
    return str(rows[0]["id"])


def _upsert(sb: Any, table: str, row: dict[str, Any], *, on_conflict: str) -> None:
    sb.table(table).upsert(row, on_conflict=on_conflict).execute()


def seed(*, publish: bool = True) -> dict[str, Any]:
    """Insert/upsert the controlled UAT inventory. Idempotent."""
    sb = _sb()
    plan_id = _ensure_writing_skill_inactive(sb)
    status = "published" if publish else "draft"

    _upsert(
        sb,
        "practice_banks",
        {
            "id": str(IDS["bank"]),
            "skill": "writing",
            "bank_number": UAT_BANK_NUMBER,
            "title": UAT_BANK_TITLE,
            "weakness_tags": [],
        },
        on_conflict="id",
    )

    writing_sets = [
        (
            "set_academic_t1",
            "hub_academic_t1",
            "section_academic_t1",
            "q_academic_t1",
            9101,
            "Academic Task 1",
            "academic",
            "task1_academic",
            PROMPTS["academic_t1"],
            "writing-uat4b-academic-t1",
            150,
        ),
        (
            "set_both_t2",
            "hub_both_t2",
            "section_both_t2",
            "q_both_t2",
            9102,
            "Task 2 Both",
            "both",
            "task2",
            PROMPTS["both_t2"],
            "writing-uat4b-both-t2",
            250,
        ),
        (
            "set_gt_t1",
            "hub_gt_t1",
            "section_gt_t1",
            "q_gt_t1",
            9103,
            "General Training Task 1 Letter",
            "general_training",
            "task1_general",
            PROMPTS["gt_t1"],
            "writing-uat4b-gt-t1",
            150,
        ),
    ]

    for (
        set_key,
        hub_key,
        sec_key,
        q_key,
        set_number,
        name,
        exam_module,
        q_type,
        prompt,
        slug,
        min_words,
    ) in writing_sets:
        _upsert(
            sb,
            "practice_sets",
            {
                "id": str(IDS[set_key]),
                "bank_id": str(IDS["bank"]),
                "set_number": set_number,
                "difficulty": "medium",
                "title": _title(name),
                "description": UAT_MARKER,
                "status": status,
                "exam_module": exam_module,
            },
            on_conflict="id",
        )
        _upsert(
            sb,
            "practice_hubs",
            {
                "id": str(IDS[hub_key]),
                "set_id": str(IDS[set_key]),
                "slug": slug,
                "videos": [],
                "practice_prompt": "",
                "submit_config": {
                    "type": "bank",
                    "module": "writing",
                    "href": f"/practice/writing/{IDS[hub_key]}/exercise",
                },
                "estimated_min": 25 if q_type != "task2" else 40,
                "sort_order": set_number,
            },
            on_conflict="id",
        )
        _upsert(
            sb,
            "bank_sections",
            {
                "id": str(IDS[sec_key]),
                "practice_set_id": str(IDS[set_key]),
                "module": "writing",
                "part": 1,
                "title": f"Writing Task {'2' if q_type == 'task2' else '1'}",
                "passage_text": prompt,
                "image_url": None,
            },
            on_conflict="id",
        )
        _upsert(
            sb,
            "bank_questions",
            {
                "id": str(IDS[q_key]),
                "section_id": str(IDS[sec_key]),
                "question_number": 1,
                "question_type": q_type,
                "prompt": prompt,
                "options": {"min_words": min_words},
                "correct_answer": None,
                "skill_tag": "writing",
            },
            on_conflict="id",
        )

    for mock_key, q_key, catalog, exam_module, name, prompt, q_type in (
        (
            "mock_academic",
            "mock_q_academic",
            91,
            "academic",
            "Academic Writing Mock",
            PROMPTS["academic_t1"],
            "task1_academic",
        ),
        (
            "mock_gt",
            "mock_q_gt",
            92,
            "general_training",
            "General Training Writing Mock",
            PROMPTS["gt_t1"],
            "task1_general",
        ),
    ):
        _upsert(
            sb,
            "mock_tests",
            {
                "id": str(IDS[mock_key]),
                "title": _title(name),
                "description": UAT_MARKER,
                "status": status,
                "is_published": status == "published",
                "catalog_number": catalog,
                "listening_parts": 1,
                "reading_passages": 1,
                "writing_tasks": 1,
                "exam_module": exam_module,
                "is_free": False,
            },
            on_conflict="id",
        )
        for mod, seq, mins in (
            ("listening", 1, 30),
            ("reading", 2, 30),
            ("writing", 3, 60),
            ("speaking", 4, 14),
        ):
            sb.table("mock_test_modules").upsert(
                {
                    "mock_test_id": str(IDS[mock_key]),
                    "module": mod,
                    "sequence_order": seq,
                    "duration_minutes": mins,
                    "is_enabled": mod == "writing",
                },
                on_conflict="mock_test_id,module",
            ).execute()
        _upsert(
            sb,
            "questions",
            {
                "id": str(IDS[q_key]),
                "mock_test_id": str(IDS[mock_key]),
                "module": "writing",
                "part": 1,
                "question_number": 1,
                "question_type": q_type,
                "prompt": prompt,
                "options": {"min_words": 150, "title": "WRITING TASK 1"},
            },
            on_conflict="id",
        )

    pci_rows = [
        (
            "pci_academic_t1",
            "practice_hub",
            "hub_academic_t1",
            "academic",
            10,
        ),
        (
            "pci_both_t2",
            "practice_hub",
            "hub_both_t2",
            "both",
            20,
        ),
        (
            "pci_gt_t1",
            "practice_hub",
            "hub_gt_t1",
            "general_training",
            30,
        ),
        (
            "pci_mock_academic",
            "mock_test",
            "mock_academic",
            "academic",
            40,
        ),
        (
            "pci_mock_gt",
            "mock_test",
            "mock_gt",
            "general_training",
            50,
        ),
    ]
    for pci_key, item_type, item_key, exam_module, sort_order in pci_rows:
        _upsert(
            sb,
            "program_content_items",
            {
                "id": str(IDS[pci_key]),
                "plan_id": plan_id,
                "item_type": item_type,
                "item_id": str(IDS[item_key]),
                "exam_module": exam_module,
                "sort_order": sort_order,
                "is_active": True,
            },
            on_conflict="id",
        )

    snap = inventory_snapshot(sb)
    if snap["writing_skill"] and snap["writing_skill"].get("is_active"):
        raise RuntimeError("writing_skill became active during seed — abort.")
    return snap


def cleanup() -> dict[str, Any]:
    """Remove ONLY Phase 4B UAT seed records (by deterministic IDs)."""
    sb = _sb()

    pci_ids = [
        str(IDS[k])
        for k in (
            "pci_academic_t1",
            "pci_both_t2",
            "pci_gt_t1",
            "pci_mock_academic",
            "pci_mock_gt",
        )
    ]
    sb.table("program_content_items").delete().in_("id", pci_ids).execute()

    mock_q_ids = [str(IDS["mock_q_academic"]), str(IDS["mock_q_gt"])]
    sb.table("questions").delete().in_("id", mock_q_ids).execute()

    for mock_id in (str(IDS["mock_academic"]), str(IDS["mock_gt"])):
        sb.table("mock_test_modules").delete().eq("mock_test_id", mock_id).execute()
    sb.table("mock_tests").delete().in_(
        "id", [str(IDS["mock_academic"]), str(IDS["mock_gt"])]
    ).execute()

    q_ids = [
        str(IDS["q_academic_t1"]),
        str(IDS["q_both_t2"]),
        str(IDS["q_gt_t1"]),
    ]
    sb.table("bank_questions").delete().in_("id", q_ids).execute()
    sec_ids = [
        str(IDS["section_academic_t1"]),
        str(IDS["section_both_t2"]),
        str(IDS["section_gt_t1"]),
    ]
    sb.table("bank_sections").delete().in_("id", sec_ids).execute()
    hub_ids = [
        str(IDS["hub_academic_t1"]),
        str(IDS["hub_both_t2"]),
        str(IDS["hub_gt_t1"]),
    ]
    sb.table("practice_hubs").delete().in_("id", hub_ids).execute()
    set_ids = [
        str(IDS["set_academic_t1"]),
        str(IDS["set_both_t2"]),
        str(IDS["set_gt_t1"]),
    ]
    sb.table("practice_sets").delete().in_("id", set_ids).execute()
    sb.table("practice_banks").delete().eq("id", str(IDS["bank"])).execute()

    return inventory_snapshot(sb)


def verify_seeded() -> dict[str, Any]:
    snap = inventory_snapshot()
    assert len(snap["sets"]) == 3, snap
    assert len(snap["mocks"]) == 2, snap
    assert len(snap["program_content_items"]) == 5, snap
    by_id = {str(r["id"]): r for r in snap["sets"]}
    assert by_id[str(IDS["set_academic_t1"])]["exam_module"] == "academic"
    assert by_id[str(IDS["set_both_t2"])]["exam_module"] == "both"
    assert by_id[str(IDS["set_gt_t1"])]["exam_module"] == "general_training"
    mocks = {str(r["id"]): r for r in snap["mocks"]}
    assert mocks[str(IDS["mock_academic"])]["exam_module"] == "academic"
    assert mocks[str(IDS["mock_gt"])]["exam_module"] == "general_training"
    assert snap["writing_skill"]["is_active"] is False
    return snap


def verify_clean() -> dict[str, Any]:
    snap = inventory_snapshot()
    assert snap["sets"] == [], snap
    assert snap["mocks"] == [], snap
    assert snap["program_content_items"] == [], snap
    return snap


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4B.0 UAT writing track seed")
    parser.add_argument(
        "command",
        choices=("seed", "cleanup", "verify", "status", "cycle"),
        help="seed | cleanup | verify | status | cycle",
    )
    args = parser.parse_args(argv)
    try:
        url = assert_safe_uat_database()
        print(f"safe_db={url}")
        if args.command == "seed":
            snap = seed()
            verify_seeded()
            print(json.dumps({"ok": True, "command": "seed", "inventory": snap}, default=str, indent=2))
        elif args.command == "cleanup":
            snap = cleanup()
            verify_clean()
            print(json.dumps({"ok": True, "command": "cleanup", "inventory": snap}, default=str, indent=2))
        elif args.command == "verify":
            snap = verify_seeded()
            print(json.dumps({"ok": True, "command": "verify", "inventory": snap}, default=str, indent=2))
        elif args.command == "status":
            snap = inventory_snapshot()
            print(json.dumps({"ok": True, "command": "status", "inventory": snap}, default=str, indent=2))
        elif args.command == "cycle":
            sb = _sb()
            all_sets = (
                sb.table("practice_sets").select("id, description").execute().data or []
            )
            before_non_uat_sets = sum(
                1
                for r in all_sets
                if UAT_MARKER not in str(r.get("description") or "")
            )
            seed()
            verify_seeded()
            cleanup()
            verify_clean()
            seed()
            verify_seeded()
            all_sets_after = (
                sb.table("practice_sets").select("id, description").execute().data or []
            )
            after_non_uat_sets = sum(
                1
                for r in all_sets_after
                if UAT_MARKER not in str(r.get("description") or "")
            )
            if before_non_uat_sets != after_non_uat_sets:
                raise RuntimeError(
                    f"Non-UAT practice_sets count changed: "
                    f"{before_non_uat_sets} → {after_non_uat_sets}"
                )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "cycle",
                        "non_uat_sets_unchanged": before_non_uat_sets,
                        "inventory": inventory_snapshot(),
                    },
                    default=str,
                    indent=2,
                )
            )
        return 0
    except Exception as exc:  # noqa: BLE001 — CLI
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
