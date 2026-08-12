"""DEPRECATED — use wipe_personalized_phase0 instead.

This script wiped ALL catalog mock questions including MT1/MT2. That is no
longer the production policy: keep Mock 1 + Mock 2 + diagnostic; only remove
personalized Phase0 / Bank-5 content.

See:
    python -m scripts.wipe_personalized_phase0 --dry-run
    python -m scripts.wipe_personalized_phase0 --execute
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "Refusing to run. Use:\n"
        "  python -m scripts.wipe_personalized_phase0 --dry-run\n"
        "  python -m scripts.wipe_personalized_phase0 --execute\n"
        "That keeps Mock 1, Mock 2, and diagnostic; wipes personalized Bank-5 only.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
