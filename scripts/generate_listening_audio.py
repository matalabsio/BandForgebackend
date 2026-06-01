"""Generate IELTS Listening audio locally using gTTS.

Presets:
  ielts-day3 (default) — 20 short clips from seed/listening_scripts.json
  greenfield           — single Part 1 clip from seed/greenfield_listening_scripts.json

After running, push to R2::

    python -m scripts.upload_listening_audio --preset ielts-day3
    python -m scripts.upload_listening_audio --preset greenfield

Usage::

    cd backend
    python -m scripts.generate_listening_audio
    python -m scripts.generate_listening_audio --preset greenfield
    python -m scripts.generate_listening_audio --preset ielts-day3 --part 1
    python -m scripts.generate_listening_audio --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

try:
    from gtts import gTTS
except ImportError as exc:  # pragma: no cover — surfaced at runtime
    raise SystemExit(
        "gTTS is not installed. Run: pip install -r backend/requirements.txt"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]

PRESETS: dict[str, dict[str, Path | str]] = {
    "ielts-day3": {
        "scripts": REPO_ROOT / "seed" / "listening_scripts.json",
        "out": REPO_ROOT / "audio_seed" / "ielts-day3",
        "mode": "clips",
    },
    "greenfield": {
        "scripts": REPO_ROOT / "seed" / "greenfield_listening_scripts.json",
        "out": REPO_ROOT / "audio_seed" / "greenfield",
        "mode": "full_part",
    },
}


class Clip(TypedDict):
    key: str
    tld: str
    text: str


def _part_of(key: str) -> int | None:
    if not key.startswith("part-"):
        return None
    try:
        return int(key.split("/", 1)[0].removeprefix("part-"))
    except ValueError:
        return None


def _synthesize(dest: Path, text: str, tld: str = "co.uk") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tts = gTTS(text=text, lang="en", tld=tld)
    tts.save(str(dest))


def generate_ielts_day3(
    scripts_path: Path,
    out_dir: Path,
    *,
    force: bool = False,
    only_part: int | None = None,
) -> tuple[int, int]:
    if not scripts_path.exists():
        raise SystemExit(f"Missing scripts file: {scripts_path}")
    data = json.loads(scripts_path.read_text(encoding="utf-8"))
    clips: list[Clip] = data.get("clips") or []
    if len(clips) != 20:
        print(
            f"Warning: expected 20 clips, found {len(clips)} in {scripts_path}",
            file=sys.stderr,
        )

    written = 0
    skipped = 0
    out_dir.mkdir(parents=True, exist_ok=True)

    for clip in clips:
        key = clip["key"]
        part = _part_of(key)
        if only_part and part != only_part:
            continue

        dest = out_dir / key
        if dest.exists() and not force:
            print(f"[SKIP] {dest} (exists, pass --force to overwrite)")
            skipped += 1
            continue

        _synthesize(dest, clip["text"], clip.get("tld", "co.uk"))
        print(f"[OK  ] {dest}  ({clip.get('tld', 'co.uk')})")
        written += 1

    return written, skipped


def generate_greenfield(
    scripts_path: Path,
    out_dir: Path,
    *,
    force: bool = False,
) -> tuple[int, int]:
    if not scripts_path.exists():
        raise SystemExit(f"Missing scripts file: {scripts_path}")
    data = json.loads(scripts_path.read_text(encoding="utf-8"))
    full = data.get("full_part") or {}
    key = str(full.get("key", "part-1/full.mp3"))
    text = str(full.get("text", "")).strip()
    if not text:
        raise SystemExit(f"No full_part.text in {scripts_path}")

    dest = out_dir / key
    if dest.exists() and not force:
        print(f"[SKIP] {dest} (exists, pass --force to overwrite)")
        return 0, 1

    _synthesize(dest, text, str(full.get("tld", "co.uk")))
    print(f"[OK  ] {dest}  ({full.get('tld', 'co.uk')})")
    return 1, 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        default="ielts-day3",
        help="Audio preset (default: ielts-day3)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Override output folder",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing mp3 files."
    )
    parser.add_argument(
        "--part",
        type=int,
        choices=[1, 2, 3, 4],
        help="ielts-day3 only: generate clips for one part.",
    )
    args = parser.parse_args()

    preset = PRESETS[args.preset]
    out_dir = args.out or Path(preset["out"])  # type: ignore[arg-type]
    scripts_path = Path(preset["scripts"])  # type: ignore[arg-type]

    if preset["mode"] == "full_part":
        written, skipped = generate_greenfield(
            scripts_path, out_dir, force=args.force
        )
    else:
        written, skipped = generate_ielts_day3(
            scripts_path, out_dir, force=args.force, only_part=args.part
        )

    print(f"\nDone. Generated {written} clip(s), skipped {skipped}.")
    print(f"Output: {out_dir}")
    print(f"Next: python -m scripts.upload_listening_audio --preset {args.preset}")


if __name__ == "__main__":
    main()
