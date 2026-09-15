"""Deterministic coach evaluator stub — school-speaking-stub-v0.2 (per-band)."""

from __future__ import annotations

import re

from .rubric import RUBRIC_VERSION, SCHEMA_VERSION, STUB_EVALUATOR_VERSION, get_rubric
from .schemas import CoachCard, CoachInternalSignals, EvaluateRequest, PrimaryFix


def evaluate_stub(req: EvaluateRequest) -> CoachCard:
    rubric = get_rubric(req.grade_band)
    words = [w for w in req.transcript.strip().split() if w]
    no_speech = (
        not req.transcript.strip()
        or req.transcript.strip() == "(no speech heard)"
        or req.transcript.lower().startswith("(we could")
    )
    short = (
        no_speech
        or len(words) < rubric.short_word_thresh
        or req.duration_sec < rubric.short_sec_thresh
    )
    signals = _detect_errors(req.transcript)

    if no_speech:
        return CoachCard(
            understandable="difficult",
            strength="Thanks for trying — next time speak a little closer to the mic.",
            primary_fix=None,
            new_words=[],
            filler_note=None,
            retry_prompt=f"{req.prompt} Say it again in a clear voice.",
            internal_signals=_signals(
                fluency_note="too_short",
                grammar_severity="none",
                pronunciation_advisory="hard_to_follow",
                task_relevance="partial",
            ),
        )

    if short:
        return CoachCard(
            understandable="mostly",
            strength=_short_strength(req.grade_band),
            primary_fix=None,
            new_words=[],
            filler_note=None,
            retry_prompt=_short_retry(req),
            internal_signals=_signals(
                fluency_note="too_short",
                grammar_severity="none",
                pronunciation_advisory="clear_enough",
                task_relevance="partial",
            ),
        )

    if req.grade_band == "1-3":
        return _card_1_3(req, signals)
    if req.grade_band == "4-5":
        return _card_4_5(req, signals)
    if req.grade_band == "6-8":
        return _card_6_8(req, signals)
    return _card_9_10(req, signals)


def _detect_errors(transcript: str) -> dict[str, object]:
    go_m = re.search(r"\b((?:he|she|it)\s+go)\b", transcript, re.I)
    to_m = re.search(r"\b((?:I|we|they|you)\s+go\s+school)\b", transcript, re.I)
    if not to_m:
        to_m = re.search(r"\b(go\s+school)\b", transcript, re.I)
    article_m = re.search(
        r"\b((?:is|was)\s+)(dog|cat|bird|car|ball|apple)\b",
        transcript,
        re.I,
    )
    teach_m = re.search(r"\b((?:she|he)\s+teach)\b", transcript, re.I)
    explain_m = re.search(r"\b((?:she|he)\s+explain)\b", transcript, re.I)
    filler_hits = len(re.findall(r"\b(um+|uh+|like)\b", transcript, re.I))
    return {
        "go_m": go_m,
        "to_m": to_m,
        "article_m": article_m,
        "teach_m": teach_m,
        "explain_m": explain_m,
        "filler_hits": filler_hits,
        "excellent": not (go_m or to_m or article_m or teach_m or explain_m),
    }


def _signals(
    *,
    fluency_note: str,
    grammar_severity: str,
    pronunciation_advisory: str,
    task_relevance: str,
) -> CoachInternalSignals:
    return CoachInternalSignals(
        fluency_note=fluency_note,
        grammar_severity=grammar_severity,  # type: ignore[arg-type]
        pronunciation_advisory=pronunciation_advisory,  # type: ignore[arg-type]
        task_relevance=task_relevance,  # type: ignore[arg-type]
        evaluator_version=STUB_EVALUATOR_VERSION,
        rubric_version=RUBRIC_VERSION,
        schema_version=SCHEMA_VERSION,
    )


def _short_strength(band: str) -> str:
    if band == "1-3":
        return "Nice try — you used your voice. That is brave!"
    if band == "4-5":
        return "Nice try — you started speaking. That matters."
    if band == "6-8":
        return "Good start — try speaking a little longer this time."
    return "You began well — develop your idea for about a minute."


def _short_retry(req: EvaluateRequest) -> str:
    if req.grade_band == "1-3":
        return f"{req.prompt} Say two full sentences this time."
    if req.grade_band == "4-5":
        return f"{req.prompt} Try again for about 30 seconds."
    if req.grade_band == "6-8":
        return f"{req.prompt} Try again for about 45 seconds."
    return f"{req.prompt} Try again for about 60 seconds and give one clear reason."


def _article_fix(article_m: re.Match[str]) -> PrimaryFix:
    noun = article_m.group(2).lower()
    return PrimaryFix(
        before=article_m.group(0),
        after=f"{article_m.group(1)}a {noun}",
        why_kid_friendly=f'Add "a" before {noun}.',
    )


def _missing_to_fix(to_m: re.Match[str], *, simple: bool) -> PrimaryFix:
    before = to_m.group(1)
    after = re.sub(r"\bgo\s+school\b", "go to school", before, flags=re.I)
    if simple:
        return PrimaryFix(
            before=before,
            after=after,
            why_kid_friendly='Add "to" before school.',
        )
    return PrimaryFix(
        before=before,
        after=after,
        why_kid_friendly='Use "to" before places like school.',
    )


def _go_error_fix(go_m: re.Match[str], *, simple: bool) -> PrimaryFix:
    before = go_m.group(1)
    after = re.sub(r"\bgo\b", "goes", before, count=1, flags=re.I)
    if simple:
        return PrimaryFix(
            before=before,
            after=after,
            why_kid_friendly='With he/she, say "goes".',
        )
    return PrimaryFix(
        before=before,
        after=after,
        why_kid_friendly="With he/she/it, add -s to the verb in the present.",
    )


def _teach_fix(m: re.Match[str], *, precise: bool) -> PrimaryFix:
    before = m.group(1)
    after = re.sub(r"\bteach\b", "teaches", before, count=1, flags=re.I)
    after = re.sub(r"\bexplain\b", "explains", after, count=1, flags=re.I)
    if precise:
        return PrimaryFix(
            before=before,
            after=after,
            why_kid_friendly=(
                "With she/he, use the -s form — and you can add because to give a reason."
            ),
        )
    return PrimaryFix(
        before=before,
        after=after,
        why_kid_friendly='With she/he, say "teaches" or "explains".',
    )


def _filler_note(band: str, filler_hits: int) -> str | None:
    rubric = get_rubric(band)
    if rubric.filler_policy == "never":
        return None
    if rubric.filler_policy == "heavy_only" and filler_hits < 3:
        return None
    if filler_hits < 1:
        return None
    if rubric.filler_policy == "fluency":
        return "Pause quietly instead of filling the gap — then continue your idea."
    return "You used a few filler words. Pause quietly, then continue."


def _card_1_3(req: EvaluateRequest, signals: dict[str, object]) -> CoachCard:
    primary: PrimaryFix | None = None
    article_m = signals["article_m"]
    to_m = signals["to_m"]
    go_m = signals["go_m"]
    if isinstance(article_m, re.Match):
        primary = _article_fix(article_m)
    elif isinstance(to_m, re.Match):
        primary = _missing_to_fix(to_m, simple=True)
    elif isinstance(go_m, re.Match):
        primary = _go_error_fix(go_m, simple=True)

    return CoachCard(
        understandable="yes",
        strength="I could follow your idea. Well done!",
        primary_fix=primary,
        new_words=_new_words(req.prompt, "1-3"),
        filler_note=None,
        retry_prompt=f"Say a little more: {req.prompt}",
        internal_signals=_signals(
            fluency_note="sustained",
            grammar_severity="high_impact" if primary else "none",
            pronunciation_advisory="clear_enough",
            task_relevance="on_topic",
        ),
    )


def _card_4_5(req: EvaluateRequest, signals: dict[str, object]) -> CoachCard:
    primary: PrimaryFix | None = None
    to_m = signals["to_m"]
    go_m = signals["go_m"]
    teach_m = signals["teach_m"] or signals["explain_m"]
    if isinstance(to_m, re.Match):
        primary = _missing_to_fix(to_m, simple=False)
    elif isinstance(go_m, re.Match):
        primary = _go_error_fix(go_m, simple=False)
    elif isinstance(teach_m, re.Match):
        primary = _teach_fix(teach_m, precise=False)

    return CoachCard(
        understandable="yes",
        strength="You connected your ideas clearly. Nice work!",
        primary_fix=primary,
        new_words=_new_words(req.prompt, "4-5"),
        filler_note=_filler_note("4-5", int(signals["filler_hits"])),  # type: ignore[arg-type]
        retry_prompt=f"{req.prompt} Try again for about 30 seconds.",
        internal_signals=_signals(
            fluency_note="sustained",
            grammar_severity="high_impact" if primary else "none",
            pronunciation_advisory="clear_enough",
            task_relevance="on_topic",
        ),
    )


def _card_6_8(req: EvaluateRequest, signals: dict[str, object]) -> CoachCard:
    primary: PrimaryFix | None = None
    go_m = signals["go_m"]
    to_m = signals["to_m"]
    teach_m = signals["teach_m"] or signals["explain_m"]
    if isinstance(go_m, re.Match):
        primary = _go_error_fix(go_m, simple=False)
    elif isinstance(to_m, re.Match):
        primary = _missing_to_fix(to_m, simple=False)
    elif isinstance(teach_m, re.Match):
        primary = _teach_fix(teach_m, precise=False)

    return CoachCard(
        understandable="yes",
        strength="You explained your idea clearly. Well done!",
        primary_fix=primary,
        new_words=_new_words(req.prompt, "6-8"),
        filler_note=_filler_note("6-8", int(signals["filler_hits"])),  # type: ignore[arg-type]
        retry_prompt="Tell me about your favourite teacher in about 45 seconds.",
        internal_signals=_signals(
            fluency_note="sustained",
            grammar_severity="high_impact" if primary else "none",
            pronunciation_advisory="clear_enough",
            task_relevance="on_topic",
        ),
    )


def _card_9_10(req: EvaluateRequest, signals: dict[str, object]) -> CoachCard:
    primary: PrimaryFix | None = None
    teach_m = signals["teach_m"] or signals["explain_m"]
    go_m = signals["go_m"]
    to_m = signals["to_m"]
    if isinstance(teach_m, re.Match):
        primary = _teach_fix(teach_m, precise=True)
    elif isinstance(go_m, re.Match):
        before = go_m.group(1)
        after = re.sub(r"\bgo\b", "goes", before, count=1, flags=re.I)
        primary = PrimaryFix(
            before=before,
            after=after,
            why_kid_friendly="Keep present-tense agreement precise: he/she + verb-s.",
        )
    elif isinstance(to_m, re.Match):
        before = to_m.group(1)
        after = re.sub(r"\bgo\s+school\b", "go to school", before, flags=re.I)
        primary = PrimaryFix(
            before=before,
            after=after,
            why_kid_friendly='Add the preposition "to" before places for clearer speech.',
        )

    return CoachCard(
        understandable="yes",
        strength="You developed your idea with clear points. Strong speaking!",
        primary_fix=primary,
        new_words=_new_words(req.prompt, "9-10"),
        filler_note=_filler_note("9-10", int(signals["filler_hits"])),  # type: ignore[arg-type]
        retry_prompt=(
            f"{req.prompt} Try again for about 60 seconds and give one clear reason."
        ),
        internal_signals=_signals(
            fluency_note="sustained",
            grammar_severity="high_impact" if primary else "none",
            pronunciation_advisory="clear_enough",
            task_relevance="on_topic",
        ),
    )


def stub_transcript_for_prompt(prompt: str) -> str:
    if re.search(r"animal", prompt, re.I):
        return "My favourite animal is a dog. It is soft and brown. I like it because it is cute."
    if re.search(r"family", prompt, re.I):
        return "My family is mummy daddy and me. We play at home. I love my family."
    if re.search(r"friend", prompt, re.I):
        return "My friend is Riya. We play every day. She is kind."
    if re.search(r"food|like most", prompt, re.I):
        return "I like rice and dal. It is yummy. My mummy makes it."
    if re.search(r"colour|color", prompt, re.I):
        return "My favourite colour is blue. The sky is blue. I like blue."
    if re.search(r"toy", prompt, re.I):
        return "My favourite toy is a car. I push it on the floor. It is fun."
    if re.search(r"school", prompt, re.I):
        return (
            "My school is near my house. I go school every day. "
            "I like the playground and my friends."
        )
    if re.search(r"teacher", prompt, re.I):
        return (
            "My favourite teacher is Mrs Sharma. She teach science. "
            "She is kind and she explain clearly."
        )
    if re.search(r"weather", prompt, re.I):
        return "Today it is sunny. I feel happy. I can play outside."
    if re.search(r"park", prompt, re.I):
        return "I like the park near my house. I play on the swing. It is fun."
    if re.search(r"morning", prompt, re.I):
        return "In the morning I wake up. I brush my teeth. Then I go to school."
    return "I like speaking English. Um I practice at home with my sister."


def _new_words(prompt: str, band: str) -> list[str]:
    lower = prompt.lower()
    if band == "1-3":
        if "animal" in lower:
            return ["soft", "tail", "cute"]
        if "family" in lower:
            return ["kind", "home", "love"]
        if "friend" in lower:
            return ["play", "share", "happy"]
        if "food" in lower or "like most" in lower:
            return ["yummy", "sweet", "fresh"]
        if "colour" in lower or "color" in lower:
            return ["bright", "pretty", "favourite"]
        if "toy" in lower:
            return ["fun", "play", "share"]
        if "school" in lower:
            return ["friend", "teacher", "play"]
        if "weather" in lower:
            return ["sunny", "rainy", "cloudy"]
        if "park" in lower:
            return ["swing", "slide", "run"]
        if "morning" in lower:
            return ["wake", "brush", "ready"]
        return ["happy", "because", "like"]

    if band == "4-5":
        if "school" in lower:
            return ["because", "together", "favourite"]
        if "friend" in lower:
            return ["because", "together", "kind"]
        if "hobby" in lower:
            return ["because", "usually", "enjoy"]
        if "introduce" in lower or "yourself" in lower:
            return ["because", "enjoy", "family"]
        return ["because", "together", "usually"]

    if band == "6-8":
        if "school" in lower:
            return ["playground", "assembly", "classroom"]
        if "teacher" in lower:
            return ["subject", "kind", "explain"]
        if "free time" in lower or "weekend" in lower:
            return ["hobby", "relax", "outdoor"]
        if "study" in lower:
            return ["concentrate", "discuss", "usually"]
        return ["clearly", "because", "usually"]

    # 9-10
    if "school" in lower:
        return ["however", "therefore", "independent"]
    if "friend" in lower:
        return ["trustworthy", "however", "respect"]
    if "technology" in lower:
        return ["however", "therefore", "balanced"]
    if "memorable" in lower:
        return ["therefore", "confident", "preparation"]
    return ["however", "therefore", "because"]
