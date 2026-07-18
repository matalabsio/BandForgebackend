"""Load versioned writing examiner prompts from disk."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parent / "prompts"
DEFAULT_PROMPT_VERSION = "v5"
PROMPT_VERSION = DEFAULT_PROMPT_VERSION


@dataclass(frozen=True)
class LoadedPrompt:
    version: str
    system: str
    task1_rules: str | None = None


class PromptLoader:
    """Roadmap alias: Prompt Loader for versioned writing prompts."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or PROMPTS_ROOT

    def load(self, version: str | None = None) -> LoadedPrompt:
        ver = (version or DEFAULT_PROMPT_VERSION).strip()
        version_dir = self._root / ver
        if not version_dir.is_dir():
            raise FileNotFoundError(
                f"Writing prompt version not found: {ver} (expected {version_dir})"
            )

        system_path = version_dir / "system.md"
        if not system_path.is_file():
            raise FileNotFoundError(f"Missing system.md for writing prompt {ver}")

        system = system_path.read_text(encoding="utf-8").strip()
        if not system:
            raise ValueError(f"system.md is empty for writing prompt {ver}")

        task1_path = version_dir / "task1_rules.md"
        task1_rules = (
            task1_path.read_text(encoding="utf-8").strip()
            if task1_path.is_file()
            else None
        )

        manifest_path = version_dir / "manifest.json"
        if manifest_path.is_file():
            meta = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("version") and str(meta["version"]) != ver:
                raise ValueError(
                    f"Prompt manifest version mismatch: dir={ver} manifest={meta['version']}"
                )

        return LoadedPrompt(version=ver, system=system, task1_rules=task1_rules)


@lru_cache(maxsize=8)
def load_writing_prompt(version: str | None = None) -> LoadedPrompt:
    """Load a versioned writing prompt (cached)."""
    return PromptLoader().load(version)


__all__ = [
    "DEFAULT_PROMPT_VERSION",
    "LoadedPrompt",
    "PROMPT_VERSION",
    "PromptLoader",
    "load_writing_prompt",
]
