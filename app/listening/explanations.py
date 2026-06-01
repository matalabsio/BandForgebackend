"""One-line explanations for score-report question review (no AI)."""

from __future__ import annotations


def build_explanation(
    *,
    prompt: str,
    user_answer: str | None,
    correct_answer: str | None,
    is_correct: bool,
) -> str:
    label = (prompt or "this question").strip()
    if is_correct:
        return f"Correct — your answer for “{label}” matches the recording."

    if not (user_answer or "").strip():
        return f"No answer given. For “{label}”, the acceptable answer is: {correct_answer or '—'}."

    accepted = (correct_answer or "—").replace("/", " or ")
    return (
        f"For “{label}”, acceptable answers include: {accepted}. "
        f"Check spelling and the two-word limit when you listen again."
    )
