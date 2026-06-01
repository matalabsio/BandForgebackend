"""Tests for listening instruction extraction."""

from app.listening.instructions import extract_listening_instructions

SAMPLE = """Questions 1–10: Form Completion
Complete the form below. Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.

╔══════════════════════════════════════════════════════════════╗
║     GREENFIELD COLLEGE – COURSE REGISTRATION FORM            ║
╚══════════════════════════════════════════════════════════════╝"""


def test_extract_listening_instructions_strips_form_template():
    out = extract_listening_instructions(SAMPLE)
    assert out is not None
    assert "GREENFIELD" not in out
    assert "NO MORE THAN" in out
    assert "Form Completion" in out
