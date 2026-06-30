"""Structured JSON logs for the payments module.

Never log secrets, signatures, card/UPI data, or full webhook bodies.
"""

from __future__ import annotations

import json
from typing import Any


def payment_log(event: str, **fields: Any) -> None:
    payload: dict[str, Any] = {"event": event, **fields}
    print(json.dumps(payload, default=str))
