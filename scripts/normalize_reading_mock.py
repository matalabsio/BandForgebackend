"""Normalize founder reading JSON into SQL seed files.

Usage::

    cd backend && source .venv/bin/activate
    python -m scripts.normalize_reading_mock \\
      --input ../test/reading/interface/BandForge_Reading_T2_Interface_Data.json \\
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


def _correct_answer(q: dict[str, Any], qtype: str) -> str:
    if qtype == "tfng":
        return str(q["answer"]).upper()
    if qtype == "matching_headings":
        return str(q["answer"]).strip().lower()
    accepted = q.get("accepted_answers") or [q.get("answer")]
    parts = [str(a).strip() for a in accepted if a]
    return "/".join(parts) if parts else str(q.get("answer", ""))


def _prompt(q: dict[str, Any], qtype: str, group: dict[str, Any]) -> str:
    if qtype == "tfng":
        return str(q["statement"])
    if qtype == "matching_headings":
        return f"Paragraph {q.get('paragraph', '')}"
    return str(q.get("sentence") or q.get("prompt") or "")


def flatten_questions(data: dict[str, Any]) -> list[dict[str, Any]]:
    passage = str(data["passage_text"])
    mock_id = str(data["mock_test_id"])
    title = str(data["title"])
    description = data.get("description")
    rows: list[dict[str, Any]] = []

    for group in data.get("question_groups") or []:
        qtype = str(group["question_type"])
        headings = group.get("headings")
        heading_options = headings if qtype == "matching_headings" else None
        for q in group.get("questions") or []:
            num = int(q["number"])
            options = heading_options if qtype == "matching_headings" else (
                TFNG_OPTIONS if qtype == "tfng" else None
            )
            rows.append(
                {
                    "mock_test_id": mock_id,
                    "title": title,
                    "description": description,
                    "question_number": num,
                    "question_type": qtype,
                    "prompt": _prompt(q, qtype, group),
                    "passage_text": passage if num == 1 else None,
                    "options": options,
                    "correct_answer": _correct_answer(q, qtype),
                    "skill_tag": q.get("skill_tag") or qtype,
                }
            )
    return rows


def render_sql(rows: list[dict[str, Any]]) -> str:
    if not rows:
        raise ValueError("No questions produced")
    mock_id = rows[0]["mock_test_id"]
    title = rows[0]["title"]
    description = rows[0].get("description")

    lines = [
        f"-- BandForge reading seed: {title}",
        f"-- mock_test_id = {mock_id}",
        "",
        "DELETE FROM answers WHERE question_id IN (",
        f"  SELECT id FROM questions WHERE mock_test_id = '{mock_id}'",
        ");",
        f"DELETE FROM questions WHERE mock_test_id = '{mock_id}';",
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
        "",
        "INSERT INTO questions (",
        "  mock_test_id, module, question_type, question_number, prompt,",
        "  passage_text, options, correct_answer, skill_tag",
        ") VALUES",
    ]

    value_lines = []
    for r in rows:
        value_lines.append(
            "("
            f"'{r['mock_test_id']}', 'reading', '{r['question_type']}', {r['question_number']}, "
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
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    rows = flatten_questions(data)
    sql = render_sql(rows)
    args.sql.parent.mkdir(parents=True, exist_ok=True)
    args.sql.write_text(sql, encoding="utf-8")
    print(f"Wrote {len(rows)} questions -> {args.sql}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
