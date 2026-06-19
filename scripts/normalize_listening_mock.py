"""Normalize founder listening JSON into DB-ready payloads and SQL seeds.

Usage::

    cd backend && source .venv/bin/activate
    python -m scripts.normalize_listening_mock \\
      --input ../test/MT1/LT/interface/BandForge_Listening_S2_Interface_Data.json \\
      --mock-id e0000000-0000-4000-8000-000000000002 \\
      --audio-key listening/bandforge-s2/part-1/full.mp3 \\
      --out seed/generated/bandforge_s2_normalized.json \\
      --sql seed/bandforge_listening_s2_seed.sql
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SUPPORTED_GROUP_TYPES = frozenset(
    {
        "multiple_choice",
        "multiple_choice_single",
        "multiple_choice_multiple",
        "matching",
        "sentence_completion",
        "form_completion",
    }
)

DEFERRED_GROUP_TYPES = frozenset(
    {
        "map_labeling",
        "note_completion",
    }
)

TYPE_MAP = {
    "multiple_choice": "mcq",
    "multiple_choice_single": "mcq",
    "matching": "matching",
    "sentence_completion": "sentence_completion",
    "form_completion": "form_completion",
    "map_labeling": "map_labeling",
    "note_completion": "note_completion",
}


def _sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _sql_json(value: Any | None) -> str:
    if value is None:
        return "NULL"
    dumped = json.dumps(value, ensure_ascii=False).replace("'", "''")
    return f"'{dumped}'::jsonb"


def _normalize_options(raw: list[dict[str, Any]] | None) -> list[dict[str, str]] | None:
    if not raw:
        return None
    out: list[dict[str, str]] = []
    for item in raw:
        label = str(item.get("label") or item.get("letter") or "").strip()
        text = str(item.get("text") or "").strip()
        if label:
            out.append({"label": label, "text": text})
    return out or None


def _skill_tag(question_type: str, question_number: int) -> str:
    if question_type == "matching":
        return "matching"
    if question_type in {"sentence_completion", "form_completion"}:
        return "completion"
    if question_type == "mcq":
        return "detail"
    return "detail"


def _group_passage_text(group: dict[str, Any], *, gtype: str, instruction: str | None) -> str | None:
    """Instruction / form header shown on the first question of a group."""
    if gtype == "form_completion":
        form_title = str(group.get("form_title") or "").strip()
        parts = [p for p in (form_title, instruction or "") if p]
        return "\n\n".join(parts) if parts else instruction
    return instruction


def _flatten_groups(
    data: dict[str, Any],
    *,
    allow_unsupported: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (question_rows, metadata_rows)."""
    groups = data.get("question_groups") or []
    if not groups:
        raise ValueError("question_groups is empty or missing")

    rows: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []

    for group in groups:
        gtype = str(group.get("question_type", "")).strip()
        if gtype in DEFERRED_GROUP_TYPES and gtype not in SUPPORTED_GROUP_TYPES:
            if not allow_unsupported:
                raise ValueError(
                    f"Unsupported question_type '{gtype}' in group {group.get('group_id')}. "
                    f"Pass --allow-unsupported to skip, or extend TYPE_MAP."
                )
            continue
        if gtype not in SUPPORTED_GROUP_TYPES and gtype not in TYPE_MAP:
            raise ValueError(f"Unknown question_type: {gtype}")

        db_type = TYPE_MAP.get(gtype, gtype)
        instruction = str(group.get("instruction") or "").strip() or None
        group_options = _normalize_options(group.get("options"))

        if gtype == "multiple_choice_multiple":
            numbers = [int(n) for n in (group.get("question_numbers") or [])]
            answers = [str(a).strip() for a in (group.get("answers") or [])]
            if len(numbers) != len(answers):
                raise ValueError(
                    f"Group {group.get('group_id')}: question_numbers and answers length mismatch"
                )
            stem = str(group.get("stem") or "").strip()
            first_in_group = min(numbers)
            for number, letter in zip(numbers, answers):
                passage_text = instruction if number == first_in_group else None
                rows.append(
                    {
                        "question_number": number,
                        "question_type": "mcq",
                        "prompt": stem or instruction or f"Question {number}",
                        "passage_text": passage_text,
                        "options": group_options,
                        "correct_answer": letter,
                        "skill_tag": _skill_tag("mcq", number),
                        "transcript_location": None,
                    }
                )
                for ev in group.get("answer_evidence") or []:
                    if str(ev.get("letter", "")).strip() == letter:
                        meta.append(
                            {
                                "question_number": number,
                                "transcript_location": ev.get("transcript_location"),
                            }
                        )
                        break
            continue

        questions = group.get("questions")
        if not questions:
            if gtype in DEFERRED_GROUP_TYPES:
                continue
            raise ValueError(f"Group {group.get('group_id')} has no questions array")

        first_number: int | None = None
        for q in questions:
            number = int(q.get("number"))
            if first_number is None:
                first_number = number

            prompt = str(q.get("prompt") or "").strip()
            if gtype == "sentence_completion":
                before = str(q.get("text_before") or "").strip()
                after = str(q.get("text_after") or "").strip()
                prompt = f"{before} ___ {after}".strip()

            per_q_options = _normalize_options(q.get("options")) or group_options
            answer = q.get("answer")
            if answer is None and q.get("answers"):
                answer = "/".join(str(a) for a in q["answers"])
            accepted = q.get("accepted_answers")
            if accepted:
                answer = "/".join(str(a) for a in accepted)
            elif answer is not None:
                answer = str(answer)
            correct = str(answer).strip() if answer is not None else ""

            passage_text = (
                _group_passage_text(group, gtype=gtype, instruction=instruction)
                if number == first_number
                else None
            )

            rows.append(
                {
                    "question_number": number,
                    "question_type": db_type,
                    "prompt": prompt,
                    "passage_text": passage_text,
                    "options": per_q_options,
                    "correct_answer": correct,
                    "skill_tag": _skill_tag(db_type, number),
                    "transcript_location": q.get("transcript_location"),
                }
            )
            if q.get("transcript_location"):
                meta.append(
                    {
                        "question_number": number,
                        "transcript_location": q.get("transcript_location"),
                    }
                )

    rows.sort(key=lambda r: r["question_number"])
    return rows, meta


def _renumber_per_part(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map global IELTS numbers (11–20, etc.) to 1–10 within a part."""
    if not rows:
        return rows
    numbers = [int(r["question_number"]) for r in rows]
    min_num = min(numbers)
    if min_num == 1:
        return rows
    offset = min_num - 1
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        row["question_number"] = int(r["question_number"]) - offset
        out.append(row)
    out.sort(key=lambda r: r["question_number"])
    return out


def normalize(
    data: dict[str, Any],
    *,
    mock_id: str,
    audio_key: str,
    allow_unsupported: bool,
    part: int = 1,
    renumber_per_part: bool = False,
) -> dict[str, Any]:
    rows, meta = _flatten_groups(data, allow_unsupported=allow_unsupported)
    if renumber_per_part:
        rows = _renumber_per_part(rows)
    expected = int(data.get("total_questions") or len(rows))
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} questions, flattened {len(rows)}")

    title = str(data.get("title") or "IELTS Listening Section").strip()
    section = data.get("section")
    description = (
        f"Founder Section {section}: {title}. "
        f"Source: {data.get('resource_id', '')}. "
        f"Audio: {audio_key}."
    )

    db_rows = []
    for r in rows:
        db_rows.append(
            {
                "mock_test_id": mock_id,
                "module": "listening",
                "part": part,
                "question_type": r["question_type"],
                "question_number": r["question_number"],
                "prompt": r["prompt"],
                "passage_text": r.get("passage_text"),
                "audio_url": audio_key,
                "options": r.get("options"),
                "correct_answer": r["correct_answer"],
                "skill_tag": r["skill_tag"],
            }
        )

    return {
        "mock_test": {
            "id": mock_id,
            "title": f"IELTS Listening — {title}",
            "description": description,
            "is_published": True,
            "source_section": section,
            "resource_id": data.get("resource_id"),
        },
        "questions": db_rows,
        "metadata": {
            "transcript": data.get("transcript"),
            "audio_file": data.get("audio_file"),
            "transcript_locations": meta,
        },
    }


def render_sql(
    payload: dict[str, Any],
    *,
    skip_mock_upsert: bool = False,
    scoped_part: int | None = None,
) -> str:
    mock = payload["mock_test"]
    mock_id = mock["id"]
    part = scoped_part
    if part is None and payload["questions"]:
        part = int(payload["questions"][0]["part"])

    scope_clause = (
        f"mock_test_id = '{mock_id}' AND module = 'listening' AND part = {part}"
        if part is not None
        else f"mock_test_id = '{mock_id}'"
    )

    lines = [
        "-- Generated by normalize_listening_mock.py — review before applying",
        f"-- mock_test_id = {mock_id}",
        "",
        "DELETE FROM answers WHERE question_id IN (",
        f"  SELECT id FROM questions WHERE {scope_clause}",
        ");",
    ]

    if part is None:
        lines.extend(
            [
                "DELETE FROM module_scores WHERE attempt_id IN (",
                f"  SELECT id FROM test_attempts WHERE mock_test_id = '{mock_id}'",
                ");",
                f"DELETE FROM test_attempts WHERE mock_test_id = '{mock_id}';",
            ]
        )

    lines.append(f"DELETE FROM questions WHERE {scope_clause};")

    if not skip_mock_upsert:
        lines.extend(
            [
                "",
                "INSERT INTO mock_tests (id, title, description, is_published)",
                "VALUES (",
                f"  '{mock_id}',",
                f"  {_sql_str(mock['title'])},",
                f"  {_sql_str(mock.get('description'))},",
                "  true",
                ")",
                "ON CONFLICT (id) DO UPDATE",
                "SET",
                "  title = EXCLUDED.title,",
                "  description = EXCLUDED.description,",
                "  is_published = true;",
            ]
        )

    lines.extend(
        [
            "",
            "INSERT INTO questions (",
            "  mock_test_id, module, part, question_type, question_number, prompt,",
            "  passage_text, audio_url, options, correct_answer, skill_tag",
            ") VALUES",
        ]
    )

    value_lines = []
    for q in payload["questions"]:
        value_lines.append(
            "("
            f"'{q['mock_test_id']}', 'listening', {q['part']}, "
            f"{_sql_str(q['question_type'])}, {q['question_number']}, "
            f"{_sql_str(q['prompt'])}, "
            f"{_sql_str(q.get('passage_text'))}, "
            f"{_sql_str(q['audio_url'])}, "
            f"{_sql_json(q.get('options'))}, "
            f"{_sql_str(q['correct_answer'])}, "
            f"{_sql_str(q.get('skill_tag'))}"
            ")"
        )

    lines.append(",\n".join(value_lines) + ";")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Founder JSON path")
    parser.add_argument("--mock-id", required=True, help="UUID for mock_tests.id")
    parser.add_argument(
        "--audio-key",
        required=True,
        help="R2 object key stored on every question row",
    )
    parser.add_argument("--out", type=Path, help="Write normalized JSON here")
    parser.add_argument("--sql", type=Path, help="Write seed SQL here")
    parser.add_argument(
        "--meta-out",
        type=Path,
        help="Write metadata sidecar JSON (transcript, locations)",
    )
    parser.add_argument(
        "--allow-unsupported",
        action="store_true",
        help="Skip unsupported groups instead of failing (for S3 preview)",
    )
    parser.add_argument(
        "--part",
        type=int,
        default=1,
        help="Listening part number stored on each question row (default: 1)",
    )
    parser.add_argument(
        "--renumber-per-part",
        action="store_true",
        help="Map global IELTS question numbers to 1–10 within the part",
    )
    parser.add_argument(
        "--skip-mock-upsert",
        action="store_true",
        help="Omit INSERT INTO mock_tests (full-mock catalog already exists)",
    )
    args = parser.parse_args()

    if not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        args.mock_id,
        flags=re.I,
    ):
        print("Invalid --mock-id UUID", file=sys.stderr)
        raise SystemExit(1)

    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        raise SystemExit(1)

    data = json.loads(args.input.read_text(encoding="utf-8"))
    payload = normalize(
        data,
        mock_id=args.mock_id,
        audio_key=args.audio_key,
        allow_unsupported=args.allow_unsupported,
        part=args.part,
        renumber_per_part=args.renumber_per_part,
    )

    print(f"OK: {len(payload['questions'])} questions for mock {args.mock_id}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.out}")

    if args.meta_out:
        args.meta_out.parent.mkdir(parents=True, exist_ok=True)
        args.meta_out.write_text(
            json.dumps(payload["metadata"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.meta_out}")

    if args.sql:
        args.sql.parent.mkdir(parents=True, exist_ok=True)
        args.sql.write_text(
            render_sql(
                payload,
                skip_mock_upsert=args.skip_mock_upsert,
                scoped_part=args.part,
            ),
            encoding="utf-8",
        )
        print(f"Wrote {args.sql}")


if __name__ == "__main__":
    main()
