"""Wipe personalized Phase0/Bank-5 content; keep Mock 1, Mock 2, diagnostic.

Removes mock-sourced practice hubs/sets so personalized practice is refilled
only via Admin Question Bank (type=bank exercise UI).

Keeps:
  - Mock 1 (catalog_number=1) + Mock 2 (catalog_number=2) + their questions
  - Diagnostic mock + questions
  - practice_banks shells
  - skill_full_mocks → Mock 1

Deletes:
  - All Bank-5 practice_sets (Phase0 + custom drills) + hubs + bank_*
  - Junk mocks: Mock 3, tedst (not MT1/MT2/diagnostic)
  - user_hub_progress / practice_exercise_attempts for removed hubs

Archives:
  - Bank 1–4 practice_sets (empty catalogue shells)

DO NOT re-run scripts.seed_phase0_practice_hubs_from_mocks on production.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.wipe_personalized_phase0 --dry-run
    python -m scripts.wipe_personalized_phase0 --execute
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from app.db.supabase_client import get_supabase

DIAG = "d0000000-0000-4000-8000-000000000001"
MT1 = "a0000000-0000-4000-8000-000000000001"
MT2 = "a0000000-0000-4000-8000-000000000002"
KEEP_MOCK_IDS = frozenset({DIAG, MT1, MT2})
CUSTOM_BANK_NUMBER = 5


def chunks(xs: list[str], n: int = 100):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def delete_in(sb: Any, table: str, column: str, ids: list[str], *, dry: bool) -> int:
    if not ids:
        return 0
    total = 0
    for chunk in chunks(ids):
        if not dry:
            sb.table(table).delete().in_(column, chunk).execute()
        total += len(chunk)
    return total


def _bank_number(row: dict[str, Any]) -> int:
    pb = row.get("practice_banks") or {}
    if isinstance(pb, list):
        pb = pb[0] if pb else {}
    return int(pb.get("bank_number") or 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.dry_run == args.execute:
        print("Pass exactly one of --dry-run or --execute")
        return 2

    dry = args.dry_run
    sb = get_supabase()

    def log(msg: str) -> None:
        print(("DRY " if dry else "") + msg)

    # --- inventory ---
    mocks = (
        sb.table("mock_tests")
        .select("id, title, status, catalog_number, is_diagnostic, is_published")
        .execute()
        .data
        or []
    )
    keep_mocks = [m for m in mocks if str(m["id"]) in KEEP_MOCK_IDS]
    junk_mocks = [m for m in mocks if str(m["id"]) not in KEEP_MOCK_IDS]
    log(f"keep mocks: {[(m.get('title'), m.get('catalog_number'), m.get('is_diagnostic')) for m in keep_mocks]}")
    log(f"junk mocks to delete: {[(m.get('title'), str(m['id'])) for m in junk_mocks]}")

    sets = (
        sb.table("practice_sets")
        .select("id, title, status, set_number, practice_banks(skill, bank_number)")
        .execute()
        .data
        or []
    )
    bank5 = [s for s in sets if _bank_number(s) == CUSTOM_BANK_NUMBER]
    shells = [s for s in sets if _bank_number(s) != CUSTOM_BANK_NUMBER]
    bank5_ids = [str(s["id"]) for s in bank5]
    log(f"Bank-5 sets to delete: {len(bank5)}")
    for s in bank5:
        log(f"  [{s.get('status')}] {_bank_number(s)} {s.get('title')}")
    log(f"Bank 1–4 shells to archive: {len(shells)}")

    hubs_all = sb.table("practice_hubs").select("id, slug, set_id").execute().data or []
    hubs_drop = [h for h in hubs_all if str(h.get("set_id")) in set(bank5_ids)]
    hub_ids = [str(h["id"]) for h in hubs_drop]
    log(f"hubs to delete: {len(hub_ids)} (phase0-ish: {sum(1 for h in hubs_drop if str(h.get('slug') or '').startswith('phase0-'))})")

    # All bank_* content (Bank-5 + any stray Bank 1–4 drafts) must go —
    # personalized reloads only via new Admin uploads.
    sections = sb.table("bank_sections").select("id, practice_set_id").execute().data or []
    section_ids = [str(s["id"]) for s in sections]
    all_bq = sb.table("bank_questions").select("id").execute().data or []
    log(
        f"bank_sections total: {len(section_ids)}; bank_questions total: {len(all_bq)} "
        f"(Bank-5 sets targeted: {len(bank5_ids)})"
    )
    # Keep skill_full_mocks on MT1
    log(f"skill_full_mocks stay on MT1={MT1}")
    if not dry:
        for skill in ("listening", "reading", "writing", "speaking"):
            sb.table("skill_full_mocks").update({"mock_test_id": MT1}).eq(
                "skill", skill
            ).execute()

    # 1) progress / attempts for hubs being removed
    uhp = sb.table("user_hub_progress").select("id, hub_id").execute().data or []
    uhp_drop = [str(r["id"]) for r in uhp if str(r.get("hub_id")) in set(hub_ids)]
    pea = (
        sb.table("practice_exercise_attempts").select("id, hub_id").execute().data or []
    )
    pea_drop = [str(r["id"]) for r in pea if str(r.get("hub_id")) in set(hub_ids)]
    log(f"user_hub_progress to delete: {len(uhp_drop)}; practice_attempts: {len(pea_drop)}")
    delete_in(sb, "user_hub_progress", "id", uhp_drop, dry=dry)
    delete_in(sb, "practice_exercise_attempts", "id", pea_drop, dry=dry)

    # 2) bank questions → sections → hubs → Bank-5 sets
    if section_ids:
        qids: list[str] = []
        for chunk in chunks(section_ids):
            rows = (
                sb.table("bank_questions")
                .select("id")
                .in_("section_id", chunk)
                .execute()
                .data
                or []
            )
            qids.extend(str(r["id"]) for r in rows)
        delete_in(sb, "bank_questions", "id", qids, dry=dry)
        log(f"deleted bank_questions: {len(qids)}")
        delete_in(sb, "bank_sections", "id", section_ids, dry=dry)
        log(f"deleted bank_sections: {len(section_ids)}")

    delete_in(sb, "practice_hubs", "id", hub_ids, dry=dry)
    log(f"deleted practice_hubs: {len(hub_ids)}")
    delete_in(sb, "practice_sets", "id", bank5_ids, dry=dry)
    log(f"deleted Bank-5 practice_sets: {len(bank5_ids)}")

    # 3) archive Bank 1–4 shells
    shell_ids = [str(s["id"]) for s in shells]
    if shell_ids and not dry:
        for chunk in chunks(shell_ids):
            sb.table("practice_sets").update({"status": "archived"}).in_(
                "id", chunk
            ).execute()
    log(f"archived Bank 1–4 sets: {len(shell_ids)}")

    # 4) delete junk mocks (not MT1/MT2/diagnostic)
    for m in junk_mocks:
        mid = str(m["id"])
        title = m.get("title")
        if dry:
            log(f"would delete junk mock {mid} | {title}")
            continue
        qs = (
            sb.table("questions").select("id").eq("mock_test_id", mid).execute().data
            or []
        )
        qids = [str(q["id"]) for q in qs]
        delete_in(sb, "answers", "question_id", qids, dry=False)
        try:
            delete_in(sb, "question_versions", "question_id", qids, dry=False)
        except Exception as e:  # noqa: BLE001
            log(f"  question_versions: {e}")

        attempts = (
            sb.table("test_attempts").select("id").eq("mock_test_id", mid).execute().data
            or []
        )
        aid = [str(a["id"]) for a in attempts]
        if aid:
            for t, col in [
                ("speaking_responses", "attempt_id"),
                ("speaking_reviews", "attempt_id"),
                ("writing_reviews", "attempt_id"),
                ("answers", "attempt_id"),
            ]:
                try:
                    delete_in(sb, t, col, aid, dry=False)
                except Exception as e:  # noqa: BLE001
                    log(f"  skip {t}: {e}")
            delete_in(sb, "test_attempts", "id", aid, dry=False)

        try:
            sb.table("mock_attempts").delete().eq("mock_test_id", mid).execute()
        except Exception as e:  # noqa: BLE001
            log(f"  mock_attempts: {e}")
        try:
            sb.table("mock_test_modules").delete().eq("mock_test_id", mid).execute()
        except Exception as e:  # noqa: BLE001
            log(f"  modules: {e}")

        sb.table("questions").delete().eq("mock_test_id", mid).execute()
        try:
            sb.table("mock_tests").update(
                {"status": "archived", "is_published": False}
            ).eq("id", mid).execute()
        except Exception as e:  # noqa: BLE001
            log(f"  archive: {e}")
        try:
            sb.table("mock_tests").delete().eq("id", mid).execute()
            log(f"deleted junk mock {mid} | {title}")
        except Exception as e:  # noqa: BLE001
            log(f"FAILED delete mock {mid} | {title}: {e}")

    # 5) clear practice catalogue caches
    if not dry:
        try:
            from app.cache.hybrid_cache import delete_many

            delete_many(
                [
                    "practice:hubs:assignable_grouped",
                    *[f"practice:hubs:list:assignable:{s}" for s in (
                        "listening",
                        "reading",
                        "writing",
                        "speaking",
                    )],
                ]
            )
            log("cleared practice hub caches")
        except Exception as e:  # noqa: BLE001
            log(f"cache clear skip: {e}")

    # --- verify ---
    mocks2 = (
        sb.table("mock_tests")
        .select("id, title, is_diagnostic, catalog_number, status")
        .execute()
        .data
        or []
    )
    qs2 = sb.table("questions").select("id, module, mock_test_id").execute().data or []
    bq2 = sb.table("bank_questions").select("id").execute().data or []
    bs2 = sb.table("bank_sections").select("id").execute().data or []
    ps2 = (
        sb.table("practice_sets")
        .select("id, status, practice_banks(bank_number)")
        .execute()
        .data
        or []
    )
    hubs2 = sb.table("practice_hubs").select("id, slug").execute().data or []
    sfm = sb.table("skill_full_mocks").select("*").execute().data or []
    phase0_left = [
        h for h in hubs2 if str(h.get("slug") or "").startswith("phase0-")
    ]
    bank5_left = [s for s in ps2 if _bank_number(s) == CUSTOM_BANK_NUMBER]

    print("\n=== VERIFY ===")
    print(
        "mocks:",
        [
            (m.get("catalog_number"), m.get("is_diagnostic"), m.get("title"), m.get("status"))
            for m in mocks2
        ],
    )
    by_mock = Counter(str(q.get("mock_test_id")) for q in qs2)
    print("questions by mock_test_id:", dict(by_mock))
    print("bank_questions", len(bq2), "bank_sections", len(bs2))
    print(
        "practice_sets",
        len(ps2),
        "statuses",
        dict(Counter(s.get("status") for s in ps2)),
        "bank5_left",
        len(bank5_left),
    )
    print("hubs", len(hubs2), "phase0_left", len(phase0_left))
    print("skill_full_mocks", [(r.get("skill"), r.get("mock_test_id")) for r in sfm])

    if dry:
        print("DRY_RUN_OK")
        return 0

    mock_ids = {str(m["id"]) for m in mocks2}
    ok = (
        mock_ids == KEEP_MOCK_IDS
        and all(str(q.get("mock_test_id")) in KEEP_MOCK_IDS for q in qs2)
        and len(bq2) == 0
        and len(bs2) == 0
        and len(bank5_left) == 0
        and len(phase0_left) == 0
        and all(str(r.get("mock_test_id")) == MT1 for r in sfm)
    )
    print("PROD_WIPE_OK" if ok else "CHECK_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
