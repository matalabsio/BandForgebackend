"""Canonical paths for founder test content under repo ``test/``.

Layout::

    test/
      listening/audio/          # MP3 files (gitignored)
      listening/interface/      # BandForge_Listening_S*_Interface_Data.json
      listening/transcripts/
      listening/source/
      listening/screenshots/
      reading/interface/
      reading/source/
      writing/
      mocks/M01/

R2 object keys in Supabase stay ``test/Listening_S{N}_Audio.mp3`` (see ``R2_LISTENING_PART_AUDIO``).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPO_ROOT / "test"

LISTENING_DIR = TEST_ROOT / "listening"
LISTENING_AUDIO_DIR = LISTENING_DIR / "audio"
LISTENING_INTERFACE_DIR = LISTENING_DIR / "interface"
LISTENING_TRANSCRIPTS_DIR = LISTENING_DIR / "transcripts"
LISTENING_SOURCE_DIR = LISTENING_DIR / "source"
LISTENING_SCREENSHOTS_DIR = LISTENING_DIR / "screenshots"

READING_DIR = TEST_ROOT / "reading"
READING_INTERFACE_DIR = READING_DIR / "interface"
READING_SOURCE_DIR = READING_DIR / "source"

WRITING_DIR = TEST_ROOT / "writing"

MOCKS_DIR = TEST_ROOT / "mocks"
M01_MOCK_DIR = MOCKS_DIR / "M01"

# Interface JSON (founder exports)
LISTENING_S2_JSON = LISTENING_INTERFACE_DIR / "BandForge_Listening_S2_Interface_Data.json"
LISTENING_S3_JSON = LISTENING_INTERFACE_DIR / "BandForge_Listening_S3_Interface_Data.json"
LISTENING_S4_JSON = LISTENING_INTERFACE_DIR / "BandForge_Listening_S4_Interface_Data.json"

READING_T2_JSON = READING_INTERFACE_DIR / "BandForge_Reading_T2_Interface_Data.json"
READING_T3_JSON = READING_INTERFACE_DIR / "BandForge_Reading_T3_Interface_Data.json"

# R2 keys stored in ``questions.audio_url`` for M01 (do not change without DB migration)
R2_LISTENING_PART_AUDIO: dict[int, str] = {
    1: "test/Listening_S1_Audio.mp3",
    2: "test/Listening_S2_Audio.mp3",
    3: "test/Listening_S3_Audio.mp3",
    4: "test/Listening_S4_Audio.mp3",
}

_LISTENING_AUDIO_NAMES: dict[int, str] = {
    1: "Listening_S1_Audio.mp3",
    2: "Listening_S2_Audio.mp3",
    3: "Listening_S3_Audio.mp3",
    4: "Listening_S4_Audio.mp3",
}


def listening_audio_path(part: int) -> Path:
    """Local path to listening part MP3 (may be gitignored)."""
    name = _LISTENING_AUDIO_NAMES.get(part)
    if not name:
        raise ValueError(f"Invalid listening part: {part}")
    return LISTENING_AUDIO_DIR / name


def listening_audio_paths() -> list[tuple[int, Path, str]]:
    """(part, local_path, r2_key) for M01 upload scripts."""
    return [
        (part, listening_audio_path(part), R2_LISTENING_PART_AUDIO[part])
        for part in sorted(R2_LISTENING_PART_AUDIO)
    ]
