"""Unit smoke for bank builder route helpers (mirrors admin-builder-source.ts)."""

from __future__ import annotations


def builder_back_href(kind: str, mock_id: str = "", set_id: str = "") -> str:
    if kind == "mock":
        return f"/admin/mocks/{mock_id}"
    return "/admin/question-bank"


def builder_part_href(
    kind: str,
    *,
    mock_id: str = "",
    set_id: str = "",
    skill: str = "listening",
    module: str = "listening",
    part: int = 1,
) -> str:
    if kind == "mock":
        return f"/admin/mocks/{mock_id}/{module}/{part}"
    return f"/admin/question-bank/{skill}/{set_id}/{part}"


def test_bank_sticky_back_and_part_hrefs():
    assert builder_back_href("bank") == "/admin/question-bank"
    assert (
        builder_part_href(
            "bank",
            set_id="aaa",
            skill="listening",
            module="listening",
            part=2,
        )
        == "/admin/question-bank/listening/aaa/2"
    )
    assert builder_back_href("mock", mock_id="m1") == "/admin/mocks/m1"
    assert (
        builder_part_href("mock", mock_id="m1", module="reading", part=3)
        == "/admin/mocks/m1/reading/3"
    )
