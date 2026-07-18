"""Golden essay fixture loader for writing QA / calibration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CRITERIA_KEYS = (
    "task_achievement",
    "coherence",
    "lexical_resource",
    "grammar",
)

DEFAULT_TOLERANCE = 0.5
ESSAYS_DIR = Path(__file__).resolve().parents[2] / "tests" / "essays"
MANIFEST_PATH = ESSAYS_DIR / "manifest.json"


def _is_half_band(value: float) -> bool:
    return abs(value * 2 - round(value * 2)) < 1e-9 and 0.0 <= value <= 9.0


@dataclass(frozen=True)
class GoldenEssay:
    file: str
    label: str
    task_part: int
    question: str
    expected_overall: float
    expected_criteria: dict[str, float] | None
    tolerance: float
    essay: str

    @property
    def path(self) -> Path:
        return ESSAYS_DIR / self.file


def _parse_criteria(raw: Any) -> dict[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("expected_criteria must be an object")
    out: dict[str, float] = {}
    for key in CRITERIA_KEYS:
        if key not in raw:
            raise ValueError(f"expected_criteria missing {key}")
        val = float(raw[key])
        if not _is_half_band(val):
            raise ValueError(f"expected_criteria.{key} must be a half-band 0–9")
        out[key] = val
    return out


def _parse_entry(entry: dict[str, Any], *, essays_dir: Path) -> GoldenEssay:
    file_name = str(entry["file"])
    path = essays_dir / file_name
    if not path.is_file():
        raise FileNotFoundError(f"Golden essay file missing: {path}")

    expected_overall = float(entry["expected_overall"])
    if not _is_half_band(expected_overall):
        raise ValueError(f"{file_name}: expected_overall must be a half-band 0–9")

    tolerance = float(entry.get("tolerance", DEFAULT_TOLERANCE))
    if tolerance < 0:
        raise ValueError(f"{file_name}: tolerance must be >= 0")

    return GoldenEssay(
        file=file_name,
        label=str(entry.get("label") or path.stem),
        task_part=int(entry["task_part"]),
        question=str(entry["question"]).strip(),
        expected_overall=expected_overall,
        expected_criteria=_parse_criteria(entry.get("expected_criteria")),
        tolerance=tolerance,
        essay=path.read_text(encoding="utf-8").strip(),
    )


def load_golden_manifest(
    *,
    manifest_path: Path | None = None,
    essays_dir: Path | None = None,
) -> list[GoldenEssay]:
    """Load and validate all golden essays from the fixture manifest."""
    mpath = manifest_path or MANIFEST_PATH
    edir = essays_dir or ESSAYS_DIR
    data = json.loads(mpath.read_text(encoding="utf-8"))
    essays = data.get("essays")
    if not isinstance(essays, list) or not essays:
        raise ValueError(f"Invalid or empty golden manifest: {mpath}")

    return [_parse_entry(entry, essays_dir=edir) for entry in essays if isinstance(entry, dict)]


def resolve_golden(
    name: str | None,
    *,
    all_fixtures: bool = False,
    manifest_path: Path | None = None,
    essays_dir: Path | None = None,
) -> list[GoldenEssay]:
    entries = load_golden_manifest(manifest_path=manifest_path, essays_dir=essays_dir)
    if all_fixtures:
        return entries
    if not name:
        raise ValueError("Provide a fixture filename/label or all_fixtures=True")
    needle = name if name.endswith(".txt") else f"{name}.txt"
    for entry in entries:
        if entry.file == needle or entry.label == name or entry.file == name:
            return [entry]
    raise ValueError(f"Fixture not in golden manifest: {name}")


__all__ = [
    "CRITERIA_KEYS",
    "DEFAULT_TOLERANCE",
    "ESSAYS_DIR",
    "GoldenEssay",
    "MANIFEST_PATH",
    "load_golden_manifest",
    "resolve_golden",
]
