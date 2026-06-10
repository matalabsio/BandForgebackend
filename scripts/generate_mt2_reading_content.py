"""Validate and refresh MT2 reading interface JSON from canonical sources.

The founder handoff files in test/MT2/RT/interface/ are the source of truth.
Edit those JSON files directly, then run:

    cd backend && source .venv/bin/activate
    python -m scripts.generate_mt2_reading_content
    python -m scripts.normalize_reading_mock --input ../test/MT2/RT/interface/BandForge_Reading_MT2_P1_Interface_Data.json --part 1 --skip-mock-upsert --sql seed/m02_reading_passage1_seed.sql
"""

from __future__ import annotations

import json
from pathlib import Path

M02 = "a0000000-0000-4000-8000-000000000002"
INTERFACE_DIR = Path(__file__).resolve().parents[2] / "test" / "MT2" / "RT" / "interface"

FILES = [
    "BandForge_Reading_MT2_P1_Interface_Data.json",
    "BandForge_Reading_MT2_P2_Interface_Data.json",
    "BandForge_Reading_MT2_P3_Interface_Data.json",
]


def _validate_payload(data: dict, *, part: int) -> None:
    assert data["mock_test_id"] == M02
    assert data["task"] == part
    assert data.get("passage_text"), "passage_text required"
    groups = data.get("question_groups") or []
    assert groups, "question_groups required"
    nums: list[int] = []
    for group in groups:
        for q in group.get("questions") or []:
            nums.append(int(q["number"]))
    assert nums == sorted(nums), f"question numbers not sorted: {nums}"
    assert max(nums) == 13, f"P{part} expects 13 questions, got max {max(nums)}"


def main() -> None:
    INTERFACE_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = INTERFACE_DIR / name
        data = json.loads(path.read_text(encoding="utf-8"))
        part = int(data["task"])
        _validate_payload(data, part=part)
        # Normalize trailing newline for stable diffs
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"OK {path.name} ({len(data['question_groups'])} groups, part {part})")


if __name__ == "__main__":
    main()
