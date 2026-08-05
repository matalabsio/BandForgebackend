"""Published full-mock catalog IDs (M01 = Test 1, M02 = Test 2)."""

from __future__ import annotations

# Academic Mock 1 — single container for all L/R modules
# Valid UUID (hex only). Prefix a000 = Academic Mock 1 (plan mnemonic m000 is not valid in Postgres).
M01_MOCK_TEST_ID = "a0000000-0000-4000-8000-000000000001"

# Academic Mock 2 — Test 2 (content seeded separately).
M02_MOCK_TEST_ID = "a0000000-0000-4000-8000-000000000002"

PUBLISHED_FULL_MOCK_IDS: tuple[str, ...] = (
    M01_MOCK_TEST_ID,
    M02_MOCK_TEST_ID,
)

# Candidate app: published mocks with catalog_number in 1..MAX are startable.
# Aligns with admin CreateMockRequest catalog_number ge=1, le=20.
MAX_CANDIDATE_CATALOG_NUMBER = 20


def is_candidate_live_catalog_number(catalog_number: int | None) -> bool:
    return (
        catalog_number is not None
        and 1 <= int(catalog_number) <= MAX_CANDIDATE_CATALOG_NUMBER
    )

MODULE_ORDER = ("listening", "reading", "writing", "speaking")

# Parts that count toward full-test progression (subset of questions in DB).
# Test 1 flow: Listening parts 1-4 → Reading passages 1-2 → writing tasks 1-2 → results.
MODULE_LIVE_PARTS: dict[str, dict[str, tuple[int, ...]]] = {
    M01_MOCK_TEST_ID: {
        "listening": (1, 2, 3, 4),
        "reading": (1, 2),
        "writing": (1, 2),
    },
    M02_MOCK_TEST_ID: {
        "listening": (1, 2, 3, 4),
        "reading": (1, 2, 3),
        "writing": (1, 2),
    },
}

# Legacy URL aliases only — live Reading for M01 is passages (1, 2).
# Requests for passage 3/4 remap to 1/2 so old links do not 404.
MODULE_CONTENT_PART_ALIAS: dict[str, dict[str, dict[int, int]]] = {
    M01_MOCK_TEST_ID: {
        "reading": {3: 1, 4: 2},
    },
}


def live_content_part(*, mock_test_id: str, module: str, live_part: int) -> int:
    aliases = MODULE_CONTENT_PART_ALIAS.get(mock_test_id, {}).get(module, {})
    return int(aliases.get(live_part, live_part))


def enabled_modules_in_catalog_order(
    modules: list[dict],
) -> list[dict]:
    """Enabled mock_test_modules rows sorted by MODULE_ORDER (not DB sequence_order)."""
    order = {name: idx for idx, name in enumerate(MODULE_ORDER)}
    enabled = [m for m in modules if m.get("is_enabled")]
    return sorted(enabled, key=lambda row: order.get(str(row.get("module")), 99))
