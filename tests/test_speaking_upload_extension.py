"""Unit tests for speaking upload key helpers."""

from app.speaking.service import _audio_extension_for_upload


def test_audio_extension_prefers_content_type() -> None:
    assert _audio_extension_for_upload("audio/webm;codecs=opus") == "webm"
    assert _audio_extension_for_upload("audio/mp4") == "mp4"
    assert _audio_extension_for_upload("audio/m4a") == "mp4"
    assert _audio_extension_for_upload("audio/ogg;codecs=opus") == "ogg"


def test_audio_extension_falls_back_to_filename() -> None:
    assert _audio_extension_for_upload(None, "recording.mp4") == "mp4"
    assert _audio_extension_for_upload("", "clip.m4a") == "mp4"
    assert _audio_extension_for_upload(None, "recording.webm") == "webm"


def test_audio_extension_default_webm() -> None:
    assert _audio_extension_for_upload(None, None) == "webm"
    assert _audio_extension_for_upload("application/octet-stream", "blob") == "webm"
