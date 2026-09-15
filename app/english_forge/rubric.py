"""Grade-band rubrics for English Forge coach evaluation — rubric-v1.

Shared by the live LLM evaluator, deterministic stub, and regression suite.
Product labels match frontend GRADE_BAND_META (Set number + class range).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .schemas import GradeBand

RUBRIC_VERSION = "rubric-v1"
EVALUATOR_VERSION = "school-speaking-v0.2"
SCHEMA_VERSION = "coach-card-v0"
STUB_EVALUATOR_VERSION = "school-speaking-stub-v0.2"

FillerPolicy = Literal["never", "heavy_only", "gentle", "fluency"]


@dataclass(frozen=True)
class BandRubric:
    grade_band: GradeBand
    set_number: int
    classes: str
    class_label: str
    target_duration_sec: int
    max_duration_sec: int
    short_word_thresh: int
    short_sec_thresh: int
    good_enough: str
    fix_policy: str
    vocab_ceiling: str
    filler_policy: FillerPolicy
    retry_style: str
    llm_block: str


_FORBIDDEN = """Forbidden for all bands:
- Never give IELTS bands or examiner criterion scores (FC/LR/GRA/P).
- Do not invent quotes the student did not say.
- Do not shame accent, silence, nervousness, or Indian English that is clear.
- Do not dump every error — at most ONE primary_fix (or null).
- Never score similarity to a sample/reference answer."""


BAND_RUBRICS: dict[GradeBand, BandRubric] = {
    "1-3": BandRubric(
        grade_band="1-3",
        set_number=1,
        classes="Class 1–3",
        class_label="Set 1 · Class 1–3",
        target_duration_sec=20,
        max_duration_sec=30,
        short_word_thresh=5,
        short_sec_thresh=5,
        good_enough=(
            "Can an adult follow the idea? Basic complete sentences. "
            "Familiar everyday words. Keeps trying. Pronunciation understandable."
        ),
        fix_policy=(
            "Lean praise. Fix ONLY if the error blocks meaning "
            "(missing article that confuses, 'go school', 'he go'). "
            "Otherwise primary_fix = null. Use very simple kid words in why_kid_friendly."
        ),
        vocab_ceiling="Easy everyday words a Class 1–3 child can try (soft, kind, play).",
        filler_policy="never",
        retry_style="Same prompt; ask for two full sentences in a clear voice.",
        llm_block="""Grade band 1-3 (Set 1 · Class 1–3):
- Understandability: Can an adult follow the idea?
- Sentences: Basic complete sentence is enough.
- Grammar: Only major meaning-blocking errors.
- Vocabulary: Familiar everyday words only in new_words.
- Fluency: Keeps trying — praise effort.
- Pronunciation: Understandable is enough; never shame accent.
- Fix policy: Lean praise; primary_fix only if meaning is blocked; else null.
- Fillers: Do NOT mention filler words for this band.
- Retry: Same prompt; ask for two full sentences.
- Target speaking length: about 20 seconds (max 30).""",
    ),
    "4-5": BandRubric(
        grade_band="4-5",
        set_number=2,
        classes="Class 3–6",
        class_label="Set 2 · Class 3–6",
        target_duration_sec=30,
        max_duration_sec=40,
        short_word_thresh=8,
        short_sec_thresh=10,
        good_enough=(
            "Mostly clear. Connected short sentences. Common errors OK to fix gently. "
            "Topic vocabulary. Short continuous speech. Mostly clear pronunciation."
        ),
        fix_policy=(
            "One gentle common-error fix (missing 'to', he/she + verb -s, simple tense). "
            "Still at most one primary_fix. Keep why_kid_friendly simple."
        ),
        vocab_ceiling="Topic words they can use now (because, together, favourite).",
        filler_policy="heavy_only",
        retry_style="Same prompt; try again for about 30 seconds.",
        llm_block="""Grade band 4-5 (Set 2 · Class 3–6):
- Understandability: Mostly clear.
- Sentences: Short connected sentences.
- Grammar: Gentle common-error fixes only (one primary_fix).
- Vocabulary: Topic vocabulary OK in new_words.
- Fluency: Short continuous speech.
- Pronunciation: Mostly clear; advisory only.
- Fix policy: One clear common-error fix; do not over-correct.
- Fillers: Mention fillers ONLY if they are heavy (many um/uh/like).
- Retry: Same prompt for about 30 seconds.
- Target speaking length: about 30 seconds (max 40).""",
    ),
    "6-8": BandRubric(
        grade_band="6-8",
        set_number=3,
        classes="Class 6–8",
        class_label="Set 3 · Class 6–8",
        target_duration_sec=45,
        max_duration_sec=60,
        short_word_thresh=12,
        short_sec_thresh=15,
        good_enough=(
            "Clear with minor issues. Developed response. Meaningful recurring errors. "
            "Vocabulary variety. Sustains the answer. Generally clear pronunciation."
        ),
        fix_policy=(
            "One clear high-impact grammar or meaning fix. "
            "Prefer errors that affect meaning or recur. Topic vocabulary OK."
        ),
        vocab_ceiling="Topic vocabulary with some variety (playground, explain, usually).",
        filler_policy="gentle",
        retry_style="Related prompt (~45s) that builds on the same topic world.",
        llm_block="""Grade band 6-8 (Set 3 · Class 6–8):
- Understandability: Clear with minor issues.
- Sentences: Developed response (not just one line).
- Grammar: One high-impact / recurring error as primary_fix.
- Vocabulary: Variety OK — topic words in new_words.
- Fluency: Sustains the response.
- Pronunciation: Generally clear; advisory only.
- Fix policy: One high-impact coaching move; not pedantry.
- Fillers: Gentle note if fillers are present.
- Retry: Closely related follow-up (~45 seconds).
- Target speaking length: about 45 seconds (max 60).""",
    ),
    "9-10": BandRubric(
        grade_band="9-10",
        set_number=4,
        classes="Class 8–10",
        class_label="Set 4 · Class 8–10",
        target_duration_sec=60,
        max_duration_sec=90,
        short_word_thresh=15,
        short_sec_thresh=20,
        good_enough=(
            "Clear and precise. Structured response. More precise correction "
            "(tense, connector, opinion structure). Range + precision in vocab. "
            "Sustains and develops ideas. Clear and controlled pronunciation."
        ),
        fix_policy=(
            "Still ONE primary fix — precision (tense, connector, clearer opinion), "
            "not a dump of every error. why_kid_friendly can be slightly more precise "
            "but never IELTS jargon."
        ),
        vocab_ceiling="Range + precision (however, therefore, because, usually).",
        filler_policy="fluency",
        retry_style="Related prompt asking for a reason or comparison (~60s).",
        llm_block="""Grade band 9-10 (Set 4 · Class 8–10):
- Understandability: Clear and precise.
- Sentences: Structured response that develops ideas.
- Grammar: One precision fix (tense / connector / opinion clarity) — still only ONE.
- Vocabulary: Range + precision in new_words.
- Fluency: Sustains and develops; gentle fluency coaching OK.
- Pronunciation: Clear and controlled; never shame accent.
- Fix policy: Precision without dumping every error; primary_fix null if excellent.
- Fillers: Fluency coaching if fillers interrupt flow.
- Retry: Related prompt that asks for a reason or comparison (~60 seconds).
- Target speaking length: about 60 seconds (max 90).""",
    ),
}


def get_rubric(grade_band: GradeBand | str) -> BandRubric:
    key: GradeBand
    if grade_band in BAND_RUBRICS:
        key = grade_band  # type: ignore[assignment]
    else:
        key = "6-8"
    return BAND_RUBRICS[key]


def rubric_system_block(grade_band: GradeBand | str) -> str:
    """Full band-specific instructions to append to the system prompt."""
    r = get_rubric(grade_band)
    return f"{r.llm_block}\n\n{_FORBIDDEN}"


def class_label(grade_band: GradeBand | str) -> str:
    return get_rubric(grade_band).class_label
