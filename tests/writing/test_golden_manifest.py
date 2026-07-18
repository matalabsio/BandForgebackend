"""Golden essay manifest integrity."""

from __future__ import annotations

from app.writing.golden import (
    CRITERIA_KEYS,
    ESSAYS_DIR,
    load_golden_manifest,
    resolve_golden,
)


def test_golden_manifest_loads_all_files():
    essays = load_golden_manifest()
    assert len(essays) >= 10
    for entry in essays:
        assert entry.path.is_file()
        assert entry.path.parent == ESSAYS_DIR
        assert entry.essay.strip()
        assert entry.expected_overall * 2 == round(entry.expected_overall * 2)
        assert 0 <= entry.expected_overall <= 9
        assert entry.tolerance >= 0
        if entry.expected_criteria:
            for key in CRITERIA_KEYS:
                assert key in entry.expected_criteria


def test_resolve_golden_by_label():
    only = resolve_golden("task2_band6")
    assert len(only) == 1
    assert only[0].expected_overall == 6.0


def test_resolve_golden_all():
    all_entries = resolve_golden(None, all_fixtures=True)
    assert len(all_entries) == len(load_golden_manifest())
