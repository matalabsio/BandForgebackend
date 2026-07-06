"""Tests for listening instruction extraction."""

from app.listening.instructions import (
    extract_form_title,
    extract_listening_instructions,
    extract_notes_layout,
)

SAMPLE = """Questions 1–10: Form Completion
Complete the form below. Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.

╔══════════════════════════════════════════════════════════════╗
║     GREENFIELD COLLEGE – COURSE REGISTRATION FORM            ║
╚══════════════════════════════════════════════════════════════╝"""

NOTES_SAMPLE = """Complete the notes below. Write NO MORE THAN TWO WORDS for each answer.
@@notes_title@@DENDROCHRONOLOGY: DATING THE PAST THROUGH TREE RINGS
@@section@@31-33|The basic principle
@@section@@34-36|Building a long timeline
@@section@@37-39|Applications
@@section@@40|Limitations"""


def test_extract_listening_instructions_strips_form_template():
    out = extract_listening_instructions(SAMPLE)
    assert out is not None
    assert "GREENFIELD" not in out
    assert "NO MORE THAN" in out
    assert "Form Completion" in out


def test_extract_form_title_from_box_art():
    assert extract_form_title(SAMPLE) == "GREENFIELD COLLEGE – COURSE REGISTRATION FORM"


def test_extract_form_title_from_marker():
    text = (
        "Complete the form below.\n\n"
        "@@form_title@@BROOKSIDE LETTINGS — TENANT ENQUIRY FORM"
    )
    assert extract_form_title(text) == "BROOKSIDE LETTINGS — TENANT ENQUIRY FORM"
    assert "BROOKSIDE" not in (extract_listening_instructions(text) or "")


def test_extract_notes_layout_and_strip_from_instructions():
    layout = extract_notes_layout(NOTES_SAMPLE)
    assert layout["notes_title"] == "DENDROCHRONOLOGY: DATING THE PAST THROUGH TREE RINGS"
    assert layout["notes_sections"] == [
        {"heading": "The basic principle", "start": 31, "end": 33},
        {"heading": "Building a long timeline", "start": 34, "end": 36},
        {"heading": "Applications", "start": 37, "end": 39},
        {"heading": "Limitations", "start": 40, "end": 40},
    ]
    instr = extract_listening_instructions(NOTES_SAMPLE)
    assert instr == "Complete the notes below. Write NO MORE THAN TWO WORDS for each answer."
    assert "@@notes_" not in (instr or "")
