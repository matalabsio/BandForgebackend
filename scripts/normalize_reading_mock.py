"""Normalize founder reading JSON into SQL seed files.

Usage::

    cd backend && source .venv/bin/activate
    python -m scripts.normalize_reading_mock \\
      --input ../test/MT1/RT/interface/BandForge_Reading_T2_Interface_Data.json \\
      --sql seed/bandforge_reading_t2_seed.sql
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TFNG_OPTIONS = [
    {"label": "TRUE", "text": "TRUE"},
    {"label": "FALSE", "text": "FALSE"},
    {"label": "NOT GIVEN", "text": "NOT GIVEN"},
]


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


def _mcq_options(q: dict[str, Any]) -> list[dict[str, str]]:
    raw = q.get("options") or []
    out: list[dict[str, str]] = []
    for opt in raw:
        if not isinstance(opt, dict):
            continue
        label = str(opt.get("label") or opt.get("letter") or "").strip()
        text = str(opt.get("text") or "").strip()
        if label:
            out.append({"label": label, "text": text})
    return out


def _correct_answer(q: dict[str, Any], qtype: str) -> str:
    if qtype == "tfng":
        ans = str(q["answer"]).upper()
        if ans in {"YES", "NO"}:
            return ans
        return ans
    if qtype == "matching_headings":
        return str(q["answer"]).strip().lower()
    if qtype in {"matching_features", "mcq", "matching_information"}:
        return str(q["answer"]).strip().upper()
    accepted = q.get("accepted_answers") or [q.get("answer")]
    parts = [str(a).strip() for a in accepted if a]
    return "/".join(parts) if parts else str(q.get("answer", ""))


def _prompt(q: dict[str, Any], qtype: str, group: dict[str, Any]) -> str:
    if qtype == "tfng":
        return str(q["statement"])
    if qtype == "matching_headings":
        return f"Paragraph {q.get('paragraph', '')}"
    if qtype in {"matching_features", "matching_information"}:
        return str(q.get("prompt") or q.get("statement") or "")
    if qtype == "mcq":
        return str(q.get("prompt") or "")
    return str(q.get("sentence") or q.get("prompt") or "")


YNG_OPTIONS = [
    {"label": "YES", "text": "YES"},
    {"label": "NO", "text": "NO"},
    {"label": "NOT GIVEN", "text": "NOT GIVEN"},
]


def _question_options(
    group: dict[str, Any], qtype: str, q: dict[str, Any]
) -> list[dict[str, str]] | None:
    if qtype == "matching_headings":
        return group.get("headings")
    if qtype == "matching_features":
        findings = group.get("findings") or []
        return [
            {
                "label": str(f.get("label") or "").strip(),
                "text": str(f.get("text") or "").strip(),
            }
            for f in findings
            if isinstance(f, dict) and f.get("label")
        ]
    if qtype == "mcq":
        opts = _mcq_options(q)
        return opts or None
    if qtype == "tfng":
        variant = str(group.get("options_variant") or "tfng").lower()
        if variant in {"yes_no", "ynng", "yes"}:
            return YNG_OPTIONS
        return TFNG_OPTIONS
    return None


def flatten_questions(data: dict[str, Any], *, part: int = 1) -> list[dict[str, Any]]:
    passage = str(data["passage_text"])
    mock_id = str(data["mock_test_id"])
    title = str(data["title"])
    description = data.get("description")
    rows: list[dict[str, Any]] = []
    all_numbers = [
        int(q["number"])
        for group in data.get("question_groups") or []
        for q in group.get("questions") or []
    ]
    passage_anchor = min(all_numbers) if all_numbers else 1

    for group in data.get("question_groups") or []:
        qtype = str(group["question_type"])
        for q in group.get("questions") or []:
            num = int(q["number"])
            rows.append(
                {
                    "mock_test_id": mock_id,
                    "title": title,
                    "description": description,
                    "part": part,
                    "question_number": num,
                    "question_type": qtype,
                    "prompt": _prompt(q, qtype, group),
                    "passage_text": passage if num == passage_anchor else None,
                    "options": _question_options(group, qtype, q),
                    "correct_answer": _correct_answer(q, qtype),
                    "skill_tag": q.get("skill_tag") or qtype,
                }
            )
    return rows


def render_sql(
    rows: list[dict[str, Any]],
    *,
    skip_mock_upsert: bool = False,
    scoped_part: int | None = None,
) -> str:
    if not rows:
        raise ValueError("No questions produced")
    mock_id = rows[0]["mock_test_id"]
    title = rows[0]["title"]
    description = rows[0].get("description")
    part = scoped_part if scoped_part is not None else int(rows[0]["part"])
    scope_clause = (
        f"mock_test_id = '{mock_id}' AND module = 'reading' AND part = {part}"
    )

    lines = [
        f"-- BandForge reading seed: {title}",
        f"-- mock_test_id = {mock_id} part = {part}",
        "",
        "DELETE FROM answers WHERE question_id IN (",
        f"  SELECT id FROM questions WHERE {scope_clause}",
        ");",
        f"DELETE FROM questions WHERE {scope_clause};",
    ]

    if not skip_mock_upsert:
        lines.extend(
            [
                f"DELETE FROM test_attempts WHERE mock_test_id = '{mock_id}';",
                "",
                "INSERT INTO mock_tests (id, title, description, is_published)",
                "VALUES (",
                f"  '{mock_id}',",
                f"  {_sql_str(title)},",
                f"  {_sql_str(description)},",
                "  true",
                ")",
                "ON CONFLICT (id) DO UPDATE SET",
                "  title = EXCLUDED.title,",
                "  description = EXCLUDED.description,",
                "  is_published = true;",
            ]
        )

    lines.extend(
        [
            "",
            "INSERT INTO questions (",
            "  mock_test_id, module, question_type, question_number, part, prompt,",
            "  passage_text, options, correct_answer, skill_tag",
            ") VALUES",
        ]
    )

    value_lines = []
    for r in rows:
        value_lines.append(
            "("
            f"'{r['mock_test_id']}', 'reading', '{r['question_type']}', {r['question_number']}, "
            f"{r['part']}, "
            f"{_sql_str(r['prompt'])}, "
            f"{_sql_str(r['passage_text'])}, "
            f"{_sql_json(r['options'])}, "
            f"{_sql_str(r['correct_answer'])}, "
            f"{_sql_str(r['skill_tag'])}"
            ")"
        )
    lines.append(",\n".join(value_lines) + ";")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--sql", required=True, type=Path)
    parser.add_argument("--part", type=int, default=1)
    parser.add_argument(
        "--skip-mock-upsert",
        action="store_true",
        help="Omit INSERT INTO mock_tests (full-mock catalog already exists)",
    )
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    rows = flatten_questions(data, part=args.part)
    sql = render_sql(
        rows,
        skip_mock_upsert=args.skip_mock_upsert,
        scoped_part=args.part,
    )
    args.sql.parent.mkdir(parents=True, exist_ok=True)
    args.sql.write_text(sql, encoding="utf-8")
    print(f"Wrote {len(rows)} questions -> {args.sql}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
