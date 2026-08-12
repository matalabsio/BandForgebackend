"""Load 4 listening + 1 reading + 1 writing + 1 speaking custom bank sets via admin APIs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.admin.question_bank import (  # noqa: E402
    create_question_bank_set,
    default_bank_audio_key,
    patch_question_bank_set_status,
    save_bank_listening,
    save_bank_reading,
    save_bank_speaking,
    save_bank_writing,
    set_intro_stream_uid,
)
from app.admin.schemas import (  # noqa: E402
    ListeningBuilderQuestionIn,
    ListeningBuilderSaveRequest,
    PatchQuestionBankSetStatusRequest,
    QuestionBankCreateSetRequest,
    ReadingBuilderQuestionIn,
    ReadingBuilderSaveRequest,
    SpeakingBuilderQuestionIn,
    SpeakingBuilderSaveRequest,
    WritingBuilderSaveRequest,
)
from app.db.supabase_client import get_supabase  # noqa: E402
from app.storage.r2 import upload_object  # noqa: E402
from app.storage.stream import (  # noqa: E402
    StreamError,
    create_direct_upload,
    set_require_signed_urls,
)

EXISTING_LISTENING_SET = UUID("8342fe29-a24e-4f65-b73f-cd1aff20e11a")
LT_DIR = ROOT / "test/MT2/LT/interface"
LT_AUDIO = ROOT / "test/MT2/LT/audio"
RT_PATH = ROOT / "test/MT2/RT/interface/BandForge_Reading_MT2_P1_Interface_Data.json"
WATCH_VIDEO = ROOT / "Video/optimized/listening-intro-720p.mp4"

LISTEN_TYPE = {
    "form_completion": "Form completion",
    "sentence_completion": "Sentence completion",
    "note_completion": "Note completion",
    "multiple_choice": "MCQ — single answer",
    "multiple_choice_single": "MCQ — single answer",
    "multiple_choice_multiple": "MCQ — choose TWO",
}
READ_TYPE = {
    "tfng": "True/False/Not Given",
    "matching_headings": "Matching headings",
    "sentence_completion": "Sentence completion",
}


def _admin_id() -> UUID:
    sb = get_supabase()
    rows = (
        sb.table("users")
        .select("id")
        .eq("email", "product@matalabs.io")
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise SystemExit("Admin user product@matalabs.io not found.")
    return UUID(str(rows[0]["id"]))


def _opt_label(raw: dict) -> tuple[str, str]:
    label = str(raw.get("label") or raw.get("letter") or "").strip()
    text = str(raw.get("text") or "").strip()
    return label, text


def _completion_prompt(item: dict) -> str:
    if item.get("sentence"):
        return str(item["sentence"]).strip()
    if item.get("prompt"):
        return str(item["prompt"]).strip()
    before = str(item.get("text_before") or "").strip()
    after = str(item.get("text_after") or "").strip()
    if before and after:
        return f"{before} ______ {after}".strip()
    if before:
        return f"{before} ______".strip()
    return "______"


def listening_questions(payload: dict) -> tuple[str, list[ListeningBuilderQuestionIn]]:
    instruction = ""
    out: list[ListeningBuilderQuestionIn] = []
    for group in payload.get("question_groups") or []:
        gtype = str(group.get("question_type") or "")
        instruction = instruction or str(group.get("instruction") or "").strip()
        if gtype == "multiple_choice_multiple":
            options = [
                {"label": lab, "text": text}
                for lab, text in (_opt_label(o) for o in group.get("options") or [])
                if lab
            ]
            answers = group.get("answers") or []
            out.append(
                ListeningBuilderQuestionIn(
                    question_type="MCQ — choose TWO",
                    prompt=str(group.get("stem") or group.get("instruction") or "Choose TWO."),
                    options=options,
                    correct_answer=",".join(str(a).strip() for a in answers),
                    alt_answers=[],
                    choose_two=True,
                    difficulty="medium",
                )
            )
            continue
        for item in group.get("questions") or []:
            qtype = LISTEN_TYPE.get(gtype, "Sentence completion")
            options = None
            raw_opts = item.get("options") or group.get("options")
            if raw_opts and "MCQ" in qtype:
                options = [
                    {"label": lab, "text": text}
                    for lab, text in (_opt_label(o) for o in raw_opts)
                    if lab
                ]
            answer = str(item.get("answer") or "").strip()
            alts = [str(a).strip() for a in (item.get("accepted_answers") or []) if str(a).strip()]
            out.append(
                ListeningBuilderQuestionIn(
                    question_type=qtype,
                    prompt=_completion_prompt(item),
                    options=options,
                    correct_answer=answer,
                    alt_answers=alts,
                    choose_two=False,
                    difficulty="medium",
                )
            )
    return instruction, out


def reading_questions(payload: dict) -> list[ReadingBuilderQuestionIn]:
    out: list[ReadingBuilderQuestionIn] = []
    heading_opts = None
    for group in payload.get("question_groups") or []:
        gtype = str(group.get("question_type") or "")
        if gtype == "matching_headings":
            heading_opts = [
                {"label": str(h.get("label") or "").strip(), "text": str(h.get("text") or "").strip()}
                for h in group.get("headings") or []
            ]
        for item in group.get("questions") or []:
            if gtype == "tfng":
                out.append(
                    ReadingBuilderQuestionIn(
                        question_type="True/False/Not Given",
                        prompt=str(item.get("statement") or item.get("prompt") or "").strip(),
                        options=[
                            {"label": "TRUE", "text": "TRUE"},
                            {"label": "FALSE", "text": "FALSE"},
                            {"label": "NOT GIVEN", "text": "NOT GIVEN"},
                        ],
                        correct_answer=str(item.get("answer") or "").strip(),
                        alt_answers=[],
                        difficulty="medium",
                    )
                )
            elif gtype == "matching_headings":
                para = str(item.get("paragraph") or "").strip()
                out.append(
                    ReadingBuilderQuestionIn(
                        question_type="Matching headings",
                        prompt=f"Paragraph {para}" if para else "Choose the heading.",
                        options=heading_opts,
                        correct_answer=str(item.get("answer") or "").strip(),
                        alt_answers=[],
                        difficulty="medium",
                    )
                )
            else:
                sentence = str(item.get("sentence") or item.get("prompt") or "").strip()
                alts = [str(a).strip() for a in (item.get("accepted_answers") or []) if str(a).strip()]
                out.append(
                    ReadingBuilderQuestionIn(
                        question_type="Sentence completion",
                        prompt=sentence,
                        options=None,
                        correct_answer=str(item.get("answer") or "").strip(),
                        alt_answers=alts,
                        difficulty="medium",
                    )
                )
    return out


def upload_watch_video() -> str | None:
    if not WATCH_VIDEO.is_file():
        print("Watch video file missing; skip Stream upload.")
        return None
    data = WATCH_VIDEO.read_bytes()
    try:
        created = create_direct_upload(
            title="Listening Watch explainer",
            max_duration_seconds=3600,
            require_signed_urls=True,
        )
        with httpx.Client(timeout=300.0) as client:
            res = client.post(
                created["uploadURL"],
                files={"file": (WATCH_VIDEO.name, data, "video/mp4")},
            )
        if res.status_code >= 400:
            res = httpx.put(
                created["uploadURL"],
                content=data,
                headers={"Content-Type": "video/mp4"},
                timeout=300.0,
            )
        if res.status_code >= 400:
            print(f"Stream upload failed ({res.status_code}); continuing without Watch video.")
            return None
        uid = created["uid"]
        try:
            set_require_signed_urls(uid, required=True)
        except StreamError as exc:
            print(f"Stream signed-URL flag skipped: {exc}")
        print(f"Watch video uploaded uid={uid}")
        return uid
    except StreamError as exc:
        print(f"Stream not available ({exc}); publishing without Watch video.")
        return None


def create_or_reuse(*, admin_id: UUID, skill: str, title: str, description: str, reuse: UUID | None) -> UUID:
    if reuse:
        get_supabase().table("practice_sets").update({"title": title, "description": description}).eq(
            "id", str(reuse)
        ).execute()
        print(f"Reuse {skill} set {reuse} → {title}")
        return reuse
    created = create_question_bank_set(
        body=QuestionBankCreateSetRequest(
            skill=skill,
            title=title,
            description=description,
            status="draft",
            difficulty="medium",
        ),
        admin_id=admin_id,
    )
    print(f"Created {skill} set {created.set_id} hub={created.hub_id} → {title}")
    return created.set_id


def publish(set_id: UUID, admin_id: UUID) -> None:
    out = patch_question_bank_set_status(
        set_id=set_id,
        body=PatchQuestionBankSetStatusRequest(status="published"),
        admin_id=admin_id,
    )
    print(f"Published {out.set_id} ({out.skill}) status={out.status}")


def hub_url(set_id: UUID, skill: str) -> str:
    rows = (
        get_supabase()
        .table("practice_hubs")
        .select("id")
        .eq("set_id", str(set_id))
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        return ""
    return f"/practice/{skill}/{rows[0]['id']}/exercise"


def main() -> None:
    admin_id = _admin_id()
    watch_uid = upload_watch_video()

    listening_jobs = [
        (
            EXISTING_LISTENING_SET,
            "Listening 1 — Tenant enquiry",
            "Form completion. Brookside Lettings telephone call.",
            LT_DIR / "BandForge_Listening_MT2_S1_Interface_Data.json",
            LT_AUDIO / "MT2_LT_S1_Audio.mp3",
        ),
        (
            None,
            "Listening 2 — Wetlands welcome talk",
            "Sentence completion + MCQ. Marshfield Wetlands Centre.",
            LT_DIR / "BandForge_Listening_MT2_S2_Interface_Data.json",
            LT_AUDIO / "MT2_LT_S2_Audio.mp3",
        ),
        (
            None,
            "Listening 3 — Research tutorial",
            "Choose TWO + MCQ + sentences. Student transport project.",
            LT_DIR / "BandForge_Listening_MT2_S3_Interface_Data.json",
            LT_AUDIO / "MT2_LT_S3_Audio.mp3",
        ),
        (
            None,
            "Listening 4 — Dendrochronology lecture",
            "Note completion. Academic lecture on tree-ring dating.",
            LT_DIR / "BandForge_Listening_MT2_S4_Interface_Data.json",
            LT_AUDIO / "MT2_LT_S4_Audio.mp3",
        ),
    ]

    results: list[tuple[str, UUID, str]] = []
    for reuse, title, description, json_path, audio_path in listening_jobs:
        payload = json.loads(json_path.read_text())
        instructions, questions = listening_questions(payload)
        set_id = create_or_reuse(
            admin_id=admin_id,
            skill="listening",
            title=title,
            description=description,
            reuse=reuse,
        )
        key = default_bank_audio_key(set_id=set_id, part=1)
        upload_object(key=key, body=audio_path.read_bytes(), content_type="audio/mpeg")
        saved = save_bank_listening(
            set_id=set_id,
            part=1,
            body=ListeningBuilderSaveRequest(
                audio_key=key,
                instructions=instructions or payload.get("title"),
                questions=questions,
            ),
            admin_id=admin_id,
        )
        print(f"Saved listening {set_id} questions={saved.questions_written} audio={key}")
        if watch_uid:
            set_intro_stream_uid(set_id=set_id, stream_uid=watch_uid)
        publish(set_id, admin_id)
        results.append(("listening", set_id, hub_url(set_id, "listening")))

    reading_payload = json.loads(RT_PATH.read_text())
    reading_id = create_or_reuse(
        admin_id=admin_id,
        skill="reading",
        title="Reading 1 — How animals make sense of their world",
        description="TFNG, matching headings, sentence completion. Academic passage.",
        reuse=None,
    )
    reading_saved = save_bank_reading(
        set_id=reading_id,
        part=1,
        body=ReadingBuilderSaveRequest(
            passage_text=str(reading_payload["passage_text"]),
            questions=reading_questions(reading_payload),
        ),
        admin_id=admin_id,
    )
    print(f"Saved reading {reading_id} questions={reading_saved.questions_written}")
    publish(reading_id, admin_id)
    results.append(("reading", reading_id, hub_url(reading_id, "reading")))

    writing_id = create_or_reuse(
        admin_id=admin_id,
        skill="writing",
        title="Writing 1 — Technology and face-to-face communication",
        description="IELTS Task 2 opinion essay.",
        reuse=None,
    )
    save_bank_writing(
        set_id=writing_id,
        part=1,
        body=WritingBuilderSaveRequest(
            prompt=(
                "Some people think that modern technology is making face-to-face "
                "communication less common and less important. Others believe that "
                "technology actually helps people stay connected in more meaningful ways.\n\n"
                "Discuss both these views and give your own opinion.\n\n"
                "Give reasons for your answer and include any relevant examples from your "
                "own knowledge or experience.\n\nWrite at least 250 words."
            ),
            question_type="task2",
            options={"min_words": 250},
        ),
        admin_id=admin_id,
    )
    print(f"Saved writing {writing_id}")
    publish(writing_id, admin_id)
    results.append(("writing", writing_id, hub_url(writing_id, "writing")))

    speaking_id = create_or_reuse(
        admin_id=admin_id,
        skill="speaking",
        title="Speaking 1 — Hometown and daily life",
        description="Part 1 interview prompts.",
        reuse=None,
    )
    save_bank_speaking(
        set_id=speaking_id,
        part=1,
        body=SpeakingBuilderSaveRequest(
            questions=[
                SpeakingBuilderQuestionIn(
                    prompt="Let's talk about your hometown. What do you like most about living there?",
                    speak_time_sec=45,
                    min_skip_sec=10,
                    prep_sec=0,
                    record_sec=45,
                ),
                SpeakingBuilderQuestionIn(
                    prompt="Has your hometown changed much in recent years? In what ways?",
                    speak_time_sec=45,
                    min_skip_sec=10,
                    prep_sec=0,
                    record_sec=45,
                ),
                SpeakingBuilderQuestionIn(
                    prompt="Do you prefer to spend your free time alone or with other people? Why?",
                    speak_time_sec=45,
                    min_skip_sec=10,
                    prep_sec=0,
                    record_sec=45,
                ),
                SpeakingBuilderQuestionIn(
                    prompt="What kind of work would you like to do in the future, and why?",
                    speak_time_sec=60,
                    min_skip_sec=10,
                    prep_sec=0,
                    record_sec=60,
                ),
            ]
        ),
        admin_id=admin_id,
    )
    print(f"Saved speaking {speaking_id}")
    publish(speaking_id, admin_id)
    results.append(("speaking", speaking_id, hub_url(speaking_id, "speaking")))

    print("\nPublished custom bank sets:")
    for skill, set_id, href in results:
        print(f"  {skill:10} {set_id}  {href}")


if __name__ == "__main__":
    main()
