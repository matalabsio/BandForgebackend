"""Build module-target submit_config for practice hubs (Phase 2).

Phase 0 hubs mirror MT1/MT2 parts — open real mock UIs with the matching
catalog_number + part instead of the thin bank exercise form.
"""

from __future__ import annotations

import re
from typing import Any

SKILLS = ("listening", "reading", "writing", "speaking")

_PHASE0_SLUG = re.compile(
    r"^phase0-(listening|reading|writing|speaking)-mt([12])-(?:p(\d+)|full)$",
    re.IGNORECASE,
)


def parse_phase0_slug(slug: str | None) -> tuple[str, int, int | None] | None:
    """Return (skill, catalog_number, part|None) from Phase 0 hub slug."""
    if not slug:
        return None
    m = _PHASE0_SLUG.match(str(slug).strip())
    if not m:
        return None
    skill = m.group(1).lower()
    catalog = int(m.group(2))
    part = int(m.group(3)) if m.group(3) else None
    return skill, catalog, part


def module_submit_config(
    *,
    skill: str,
    catalog_number: int,
    part: int | None = None,
    hub_id: str | None = None,
) -> dict[str, Any]:
    """Canonical submit_config pointing at the mock module UI."""
    skill = str(skill or "").strip().lower()
    catalog = 1 if int(catalog_number) <= 1 else 2
    config: dict[str, Any] = {
        "type": "module",
        "module": skill,
        "catalog_number": catalog,
    }
    if part is not None and part > 0:
        config["part"] = int(part)

    if skill == "listening":
        p = int(part or 1)
        config["part"] = p
        config["href"] = (
            f"/test/{catalog}/listening?part={p}&auto=1&skill_context=listening"
        )
    elif skill == "reading":
        p = int(part or 1)
        config["part"] = p
        config["href"] = (
            f"/test/{catalog}/reading?passage={p}&auto=1&skill_context=reading"
        )
    elif skill == "writing":
        p = 1 if not part or part < 1 else (2 if part >= 2 else 1)
        config["part"] = p
        mock = "m01" if catalog == 1 else "m02"
        config["href"] = (
            f"/test/writing/task/{p}?auto=1&skill_context=writing&mock={mock}"
        )
    elif skill == "speaking":
        config["href"] = (
            f"/test/{catalog}/speaking?auto=1&skill_context=speaking"
        )
    else:
        config["href"] = f"/practice/{skill}"

    if hub_id:
        # Preserve hub id for plan completion; query params added by frontend.
        config["hub_id"] = str(hub_id)
    return config


def plan_module_href(
    *,
    skill: str,
    hub_id: str,
    task_type: str,
    task_id: str = "",
    catalog_number: int = 1,
    part: int | None = None,
    submit_config: dict[str, Any] | None = None,
) -> str:
    """Full plan-aware href for Practice/Submit opening a mock module."""
    cfg = submit_config if isinstance(submit_config, dict) else {}
    catalog = int(cfg.get("catalog_number") or catalog_number or 1)
    catalog = 1 if catalog <= 1 else 2
    cfg_part = cfg.get("part")
    resolved_part = (
        int(cfg_part)
        if cfg_part is not None
        else (int(part) if part is not None else None)
    )

    base = module_submit_config(
        skill=skill,
        catalog_number=catalog,
        part=resolved_part,
        hub_id=hub_id,
    )["href"]
    # Writing practice vs submit historically maps task type → part when config
    # has no part (non–Phase-0 hubs).
    if skill == "writing" and resolved_part is None:
        p = 2 if task_type == "submit" else 1
        mock = "m01" if catalog == 1 else "m02"
        base = (
            f"/test/writing/task/{p}?auto=1&skill_context=writing&mock={mock}"
        )

    sep = "&" if "?" in base else "?"
    q = f"from=plan&task={task_type}&hubId={hub_id}"
    if task_id:
        q += f"&taskId={task_id}"
    return f"{base}{sep}{q}"


def config_from_slug_or_defaults(
    *,
    skill: str,
    slug: str | None,
    hub_id: str,
    section_part: int | None = None,
) -> dict[str, Any]:
    """Prefer Phase 0 slug metadata; else section part + catalog 1."""
    parsed = parse_phase0_slug(slug)
    if parsed:
        sk, catalog, part = parsed
        return module_submit_config(
            skill=sk,
            catalog_number=catalog,
            part=part if part is not None else section_part,
            hub_id=hub_id,
        )
    return module_submit_config(
        skill=skill,
        catalog_number=1,
        part=section_part,
        hub_id=hub_id,
    )
