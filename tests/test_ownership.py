"""Ownership checks return 404 for cross-user access (no enumeration)."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.security.ownership import ensure_owner_or_not_found


def test_ensure_owner_or_not_found_allows_owner():
    user_id = uuid4()
    ensure_owner_or_not_found({"user_id": str(user_id)}, user_id)


def test_ensure_owner_or_not_found_hides_other_users():
    owner = uuid4()
    other = uuid4()
    with pytest.raises(HTTPException) as exc:
        ensure_owner_or_not_found({"user_id": str(owner)}, other)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Not found."
