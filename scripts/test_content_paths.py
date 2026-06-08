"""Canonical paths for founder test content under repo ``test/``.

Layout::

    test/
      MT1/                    # Mock Test 1 (m01)
        manifest.json
        LT/                   # Listening — audio, interface JSON, transcripts, source
        RT/                   # Reading — interface JSON, founder .pages
        WT/                   # Writing — task PDFs
      MT2/                    # Mock Test 2 (m02)
        manifest.json
        LT/
        RT/
        WT/

R2 object keys in Supabase stay ``test/Listening_S{N}_Audio.mp3`` for M01 (see ``R2_LISTENING_PART_AUDIO``).
M02 uses ``listening/m02/part-{N}/full.mp3``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPO_ROOT / "test"

# Mock Test 1 (M01)
MT1_DIR = TEST_ROOT / "MT1"
MT1_MOCK_DIR = MT1_DIR  # alias for import_mock
MT1_LISTENING_DIR = MT1_DIR / "LT"
MT1_LISTENING_AUDIO_DIR = MT1_LISTENING_DIR / "audio"
MT1_LISTENING_INTERFACE_DIR = MT1_LISTENING_DIR / "interface"
MT1_LISTENING_TRANSCRIPTS_DIR = MT1_LISTENING_DIR / "transcripts"
MT1_LISTENING_SOURCE_DIR = MT1_LISTENING_DIR / "source"
MT1_LISTENING_SCREENSHOTS_DIR = MT1_LISTENING_DIR / "screenshots"
MT1_READING_DIR = MT1_DIR / "RT"
MT1_READING_INTERFACE_DIR = MT1_READING_DIR / "interface"
MT1_READING_SOURCE_DIR = MT1_READING_DIR / "source"
MT1_WRITING_DIR = MT1_DIR / "WT"

M01_MOCK_TEST_ID = "a0000000-0000-4000-8000-000000000001"

# Mock Test 2 (M02)
MT2_DIR = TEST_ROOT / "MT2"
MT2_MOCK_DIR = MT2_DIR
MT2_MOCK_TEST_ID = "a0000000-0000-4000-8000-000000000002"
MT2_LISTENING_DIR = MT2_DIR / "LT"
MT2_LISTENING_AUDIO_DIR = MT2_LISTENING_DIR / "audio"
MT2_LISTENING_INTERFACE_DIR = MT2_LISTENING_DIR / "interface"
MT2_LISTENING_PDF_DIR = MT2_LISTENING_DIR / "pdf"
MT2_LISTENING_TRANSCRIPTS_DIR = MT2_LISTENING_DIR / "transcripts"
MT2_READING_DIR = MT2_DIR / "RT"
MT2_READING_INTERFACE_DIR = MT2_READING_DIR / "interface"
MT2_READING_SOURCE_DIR = MT2_READING_DIR / "source"
MT2_WRITING_DIR = MT2_DIR / "WT"

# Legacy aliases (prefer MT1_* / MT2_* in new code)
LISTENING_DIR = MT1_LISTENING_DIR
LISTENING_AUDIO_DIR = MT1_LISTENING_AUDIO_DIR
LISTENING_INTERFACE_DIR = MT1_LISTENING_INTERFACE_DIR
LISTENING_TRANSCRIPTS_DIR = MT1_LISTENING_TRANSCRIPTS_DIR
LISTENING_SOURCE_DIR = MT1_LISTENING_SOURCE_DIR
LISTENING_SCREENSHOTS_DIR = MT1_LISTENING_SCREENSHOTS_DIR
READING_DIR = MT1_READING_DIR
READING_INTERFACE_DIR = MT1_READING_INTERFACE_DIR
READING_SOURCE_DIR = MT1_READING_SOURCE_DIR
WRITING_DIR = MT1_WRITING_DIR
MOCKS_DIR = TEST_ROOT / "mocks"  # deprecated; use MT1_DIR / MT2_DIR
M01_MOCK_DIR = MT1_MOCK_DIR

# M01 listening interface JSON (S2–S4; S1 is Greenfield in DB)
LISTENING_S2_JSON = MT1_LISTENING_INTERFACE_DIR / "BandForge_Listening_S2_Interface_Data.json"
LISTENING_S3_JSON = MT1_LISTENING_INTERFACE_DIR / "BandForge_Listening_S3_Interface_Data.json"
LISTENING_S4_JSON = MT1_LISTENING_INTERFACE_DIR / "BandForge_Listening_S4_Interface_Data.json"

# M02 listening interface JSON
LISTENING_MT2_S1_JSON = MT2_LISTENING_INTERFACE_DIR / "BandForge_Listening_MT2_S1_Interface_Data.json"
LISTENING_MT2_S2_JSON = MT2_LISTENING_INTERFACE_DIR / "BandForge_Listening_MT2_S2_Interface_Data.json"
LISTENING_MT2_S3_JSON = MT2_LISTENING_INTERFACE_DIR / "BandForge_Listening_MT2_S3_Interface_Data.json"
LISTENING_MT2_S4_JSON = MT2_LISTENING_INTERFACE_DIR / "BandForge_Listening_MT2_S4_Interface_Data.json"

MT2_LISTENING_AUDIO_NAMES: dict[int, str] = {
    1: "MT2_LT_S1_Audio.mp3",
    2: "MT2_LT_S2_Audio.mp3",
    3: "MT2_LT_S3_Audio.mp3",
    4: "MT2_LT_S4_Audio.mp3",
}

# M02 reading interface JSON
READING_MT2_P1_JSON = MT2_READING_INTERFACE_DIR / "BandForge_Reading_MT2_P1_Interface_Data.json"
READING_MT2_P2_JSON = MT2_READING_INTERFACE_DIR / "BandForge_Reading_MT2_P2_Interface_Data.json"
READING_MT2_P3_JSON = MT2_READING_INTERFACE_DIR / "BandForge_Reading_MT2_P3_Interface_Data.json"

# M01 reading interface JSON
READING_T2_JSON = MT1_READING_INTERFACE_DIR / "BandForge_Reading_T2_Interface_Data.json"
READING_T3_JSON = MT1_READING_INTERFACE_DIR / "BandForge_Reading_T3_Interface_Data.json"

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

R2_M02_LISTENING_PART_AUDIO: dict[int, str] = {
    1: "listening/m02/part-1/full.mp3",
    2: "listening/m02/part-2/full.mp3",
    3: "listening/m02/part-3/full.mp3",
    4: "listening/m02/part-4/full.mp3",
}


def listening_audio_path(part: int) -> Path:
    """Local path to M01 listening part MP3 (may be gitignored)."""
    name = _LISTENING_AUDIO_NAMES.get(part)
    if not name:
        raise ValueError(f"Invalid listening part: {part}")
    return MT1_LISTENING_AUDIO_DIR / name


def listening_audio_paths() -> list[tuple[int, Path, str]]:
    """(part, local_path, r2_key) for M01 upload scripts."""
    return [
        (part, listening_audio_path(part), R2_LISTENING_PART_AUDIO[part])
        for part in sorted(R2_LISTENING_PART_AUDIO)
    ]


def mt2_listening_audio_path(part: int) -> Path:
    """Local path to M02 listening part MP3 (may be gitignored)."""
    name = MT2_LISTENING_AUDIO_NAMES.get(part)
    if not name:
        raise ValueError(f"Invalid MT2 listening part: {part}")
    return MT2_LISTENING_AUDIO_DIR / name
