"""Generate MT4 founder interface JSON and WT1 chart PNG from mocktest/MT4 docx sources."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MT4 = REPO / "mocktest" / "MT4"
MOCK_ID = "a0000000-0000-4000-8000-000000000004"


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    text = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_transcript(docx_path: Path) -> str:
    t = docx_text(docx_path)
    m = re.search(r"TRANSCRIPT\n(.*?)\nQUESTIONS", t, re.S)
    if not m:
        raise ValueError(f"No transcript in {docx_path}")
    trans = m.group(1)
    trans = re.sub(r"\s*\[ANSWER:[^\]]+\]", "", trans)
    trans = re.sub(r"\([^)]*MCQ[^)]*\)", "", trans)
    trans = re.sub(r"\([^)]*Sentence completion[^)]*\)", "", trans)
    trans = re.sub(r"\([^)]*Note completion[^)]*\)", "", trans)
    trans = re.sub(r"______", "", trans)
    return re.sub(r"\n{3,}", "\n\n", trans).strip()


def extract_passage(docx_path: Path) -> tuple[str, str]:
    t = docx_text(docx_path)
    qi = t.find("Questions")
    body = t[:qi].strip() if qi > 0 else t
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    if lines[0].upper().startswith("READING PASSAGE"):
        title = lines[1]
        passage = "\n\n".join(lines[1:])
    else:
        title = lines[0]
        passage = body
    return title, passage


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_listening_s1() -> None:
    transcript = extract_transcript(MT4 / "LT" / "MT4 LT S1.docx")
    data = {
        "resource_id": "ielts_listening_mt4_section_1",
        "skill": "listening",
        "section": 1,
        "title": "University Admissions — Postgraduate Diploma Enquiry",
        "section_type": "social_dialogue",
        "speakers": ["ADVISOR", "APPLICANT"],
        "estimated_audio_duration": "approx. 2 min 40 sec",
        "total_questions": 10,
        "audio_file": "ElevenLabs_MT4_LT_S1.mp3",
        "mock_test_id": MOCK_ID,
        "transcript": transcript,
        "question_groups": [
            {
                "group_id": "mt4_s1_form_1_10",
                "range": "1-10",
                "question_type": "form_completion",
                "instruction": "Complete the form below. Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.",
                "form_title": "UNIVERSITY ADMISSIONS — APPLICANT ENQUIRY FORM",
                "questions": [
                    {"number": 1, "prompt": "Surname", "answer": "Nandakumar", "accepted_answers": ["Nandakumar"]},
                    {
                        "number": 2,
                        "prompt": "Mobile number",
                        "answer": "09899 903321",
                        "accepted_answers": ["09899 903321", "09899903321"],
                    },
                    {"number": 3, "prompt": "Most recent qualification", "answer": "Statistics", "accepted_answers": ["Statistics"]},
                    {
                        "number": 4,
                        "prompt": "Previous institution",
                        "answer": "Ashwood University",
                        "accepted_answers": ["Ashwood University"],
                    },
                    {"number": 5, "prompt": "Preferred intake", "answer": "September", "accepted_answers": ["September"]},
                    {
                        "number": 6,
                        "prompt": "Outstanding document",
                        "answer": "reference letter",
                        "accepted_answers": ["reference letter"],
                    },
                    {"number": 7, "prompt": "Application fee", "answer": "120", "accepted_answers": ["120", "£120"]},
                    {"number": 8, "prompt": "Coordinator appointment day", "answer": "Thursday", "accepted_answers": ["Thursday"]},
                    {"number": 9, "prompt": "Applicant reference", "answer": "AR4472", "accepted_answers": ["AR4472"]},
                    {"number": 10, "prompt": "Preferred campus", "answer": "Riverside", "accepted_answers": ["Riverside"]},
                ],
            }
        ],
    }
    write_json(MT4 / "LT/interface/BandForge_Listening_MT4_S1_Interface_Data.json", data)


def build_listening_s2() -> None:
    transcript = (
        "HOST: Good morning, everyone, and welcome to the Urban Futures Expo. I'm your guide for the next few minutes, "
        "so let me walk you through what's on offer today.\n"
        "The expo is divided into four themed zones this year — up from three last year, since we've added a new Mobility zone.\n"
        "The main hall opens daily at nine, but the Mobility zone — where our autonomous shuttle demo is — doesn't open until ten, "
        "since the shuttle needs a calibration run first thing.\n"
        "Now, one thing I'd really recommend: the air quality sensor network demo in Zone 2. It's a live feed showing pollution "
        "readings from around the city, updated every minute.\n"
        "That display was actually funded through a public grant, not by any of our exhibitors — which is worth knowing if you're "
        "asked to fill in the feedback survey later.\n"
        "If you're interested in the smart lighting project, that's over in Zone 3. It's cut street lighting energy use by around "
        "forty per cent in the pilot district.\n"
        "There's a workshop at two pm on sensor networks — seats are limited, so if you want one, register at the information desk "
        "near the entrance.\n"
        "For parking, the multi-storey next door is free for the first hour, after which normal rates apply.\n"
        "And a quick note — the newsletter sign-up isn't at the info desk, it's actually on a tablet stationed by the exit, "
        "so don't miss that on your way out.\n"
        "Everyone who fills in the feedback survey today goes into a prize draw — the winner gets a free pass to next year's expo, "
        "plus VIP access to the launch event.\n"
        "Last thing — please keep your wristband on throughout, it's your access to every zone including the sensor networks "
        "workshop this afternoon.\n"
        "Enjoy the expo, and I'll be around near the main stage if you have questions."
    )
    data = {
        "resource_id": "ielts_listening_mt4_section_2",
        "skill": "listening",
        "section": 2,
        "title": "Urban Futures Expo — Smart City Exhibits",
        "section_type": "social_monologue",
        "speaker": "HOST",
        "estimated_audio_duration": "approx. 3 min",
        "total_questions": 10,
        "audio_file": "ElevenLabs_MT4_LT_S2.mp3",
        "mock_test_id": MOCK_ID,
        "transcript": transcript,
        "question_groups": [
            {
                "group_id": "mt4_s2_mc_11_14",
                "range": "11-14",
                "question_type": "multiple_choice",
                "instruction": "Choose the correct letter, A, B or C.",
                "questions": [
                    {
                        "number": 11,
                        "prompt": "How many themed zones does the expo have this year?",
                        "options": [
                            {"letter": "A", "text": "three"},
                            {"letter": "B", "text": "five"},
                            {"letter": "C", "text": "four"},
                        ],
                        "answer": "C",
                    },
                    {
                        "number": 12,
                        "prompt": "What time does the Mobility zone open?",
                        "options": [
                            {"letter": "A", "text": "nine"},
                            {"letter": "B", "text": "ten"},
                            {"letter": "C", "text": "eleven"},
                        ],
                        "answer": "B",
                    },
                    {
                        "number": 13,
                        "prompt": "How was the air quality display funded?",
                        "options": [
                            {"letter": "A", "text": "an exhibitor"},
                            {"letter": "B", "text": "a public grant"},
                            {"letter": "C", "text": "ticket sales"},
                        ],
                        "answer": "B",
                    },
                    {
                        "number": 14,
                        "prompt": "Where can visitors sign up for the newsletter?",
                        "options": [
                            {"letter": "A", "text": "the info desk"},
                            {"letter": "B", "text": "Zone 1"},
                            {"letter": "C", "text": "by the exit"},
                        ],
                        "answer": "C",
                    },
                ],
            },
            {
                "group_id": "mt4_s2_sentence_15_20",
                "range": "15-20",
                "question_type": "sentence_completion",
                "instruction": "Complete the sentences below. Write NO MORE THAN TWO WORDS for each answer.",
                "questions": [
                    {
                        "number": 15,
                        "text_before": "The air quality readings update every",
                        "text_after": ".",
                        "answer": "minute",
                        "accepted_answers": ["minute"],
                    },
                    {
                        "number": 16,
                        "text_before": "The smart lighting pilot cut energy use by",
                        "text_after": "per cent.",
                        "answer": "40",
                        "accepted_answers": ["40", "forty"],
                    },
                    {
                        "number": 17,
                        "text_before": "Workshop seats can be reserved at the",
                        "text_after": "desk.",
                        "answer": "information",
                        "accepted_answers": ["information"],
                    },
                    {
                        "number": 18,
                        "text_before": "Parking is free for the first",
                        "text_after": ".",
                        "answer": "hour",
                        "accepted_answers": ["hour"],
                    },
                    {
                        "number": 19,
                        "text_before": "The prize draw winner receives a",
                        "text_after": "to next year's expo.",
                        "answer": "pass",
                        "accepted_answers": ["pass", "free pass"],
                    },
                    {
                        "number": 20,
                        "text_before": "Wristbands give access to every zone, including the afternoon",
                        "text_after": "workshop.",
                        "answer": "sensor networks",
                        "accepted_answers": ["sensor networks"],
                    },
                ],
            },
        ],
    }
    write_json(MT4 / "LT/interface/BandForge_Listening_MT4_S2_Interface_Data.json", data)


def build_listening_s3() -> None:
    transcript = extract_transcript(MT4 / "LT" / "MT4 LT S3.docx")
    data = {
        "resource_id": "ielts_listening_mt4_section_3",
        "skill": "listening",
        "section": 3,
        "title": "Student Discussion — Diet, Nutrition & Public Health",
        "section_type": "academic_conversation",
        "speakers": ["STUDENT 1", "STUDENT 2"],
        "estimated_audio_duration": "approx. 4 min",
        "total_questions": 10,
        "audio_file": "ElevenLabs_MT4_LT_S3.mp3",
        "mock_test_id": MOCK_ID,
        "transcript": transcript,
        "question_groups": [
            {
                "group_id": "mt4_s3_mc_multi_21_22",
                "range": "21-22",
                "question_numbers": [21, 22],
                "question_type": "multiple_choice_multiple",
                "instruction": "Choose TWO letters, A–D.",
                "stem": "Which TWO sources will the students use for their presentation?",
                "select_count": 2,
                "options": [
                    {"letter": "A", "text": "national school nutrition survey"},
                    {"letter": "B", "text": "a local hospital study"},
                    {"letter": "C", "text": "WHO regional report"},
                    {"letter": "D", "text": "a supermarket sales database"},
                ],
                "answers": ["A", "C"],
            },
            {
                "group_id": "mt4_s3_mc_single_23",
                "range": "23",
                "question_type": "multiple_choice_single",
                "instruction": "Choose the correct letter, A, B or C.",
                "questions": [
                    {
                        "number": 23,
                        "prompt": "How do the students frame the relationship between menu reform and nutrition education?",
                        "options": [
                            {"letter": "A", "text": "Menu reform is more effective"},
                            {"letter": "B", "text": "The two are complementary"},
                            {"letter": "C", "text": "Education is more effective"},
                        ],
                        "answer": "B",
                    }
                ],
            },
            {
                "group_id": "mt4_s3_note_24_30",
                "range": "24-30",
                "question_type": "sentence_completion",
                "instruction": "Complete the notes below. Write NO MORE THAN TWO WORDS for each answer.",
                "questions": [
                    {
                        "number": 24,
                        "text_before": "Student 1 covers: introduction, survey data,",
                        "text_after": "",
                        "answer": "literature review",
                        "accepted_answers": ["literature review"],
                    },
                    {
                        "number": 25,
                        "text_before": "Case study country:",
                        "text_after": "",
                        "answer": "Sweden",
                        "accepted_answers": ["Sweden"],
                    },
                    {
                        "number": 26,
                        "text_before": "Tracking period:",
                        "text_after": "",
                        "answer": "two years",
                        "accepted_answers": ["two years", "2 years"],
                    },
                    {
                        "number": 27,
                        "text_before": "Visual for sugar data: a",
                        "text_after": "",
                        "answer": "bar chart",
                        "accepted_answers": ["bar chart"],
                    },
                    {
                        "number": 28,
                        "text_before": "Submission date:",
                        "text_after": "",
                        "answer": "21st",
                        "accepted_answers": ["21st", "twenty-first", "twenty first"],
                    },
                    {
                        "number": 29,
                        "text_before": "Next meeting location:",
                        "text_after": "",
                        "answer": "library",
                        "accepted_answers": ["library", "the library"],
                    },
                    {
                        "number": 30,
                        "text_before": "Student 1 to bring:",
                        "text_after": "",
                        "answer": "laptop",
                        "accepted_answers": ["laptop"],
                    },
                ],
            },
        ],
    }
    write_json(MT4 / "LT/interface/BandForge_Listening_MT4_S3_Interface_Data.json", data)


def build_listening_s4() -> None:
    transcript = (
        "LECTURER: Today we're looking at how international environmental law has developed since the 1970s, "
        "and specifically how enforcement — always the weak point — has evolved.\n"
        "The starting point most scholars point to is the 1972 Stockholm Conference, which for the first time treated "
        "the environment as a subject of international concern, rather than purely a domestic matter.\n"
        "What Stockholm didn't produce, though, was any binding mechanism — it was largely a declaration of principles, "
        "with no enforcement teeth.\n"
        "That changed gradually through the 1980s and 90s with a wave of framework conventions — agreements that set out "
        "broad goals, leaving the specific, binding targets to be negotiated in protocol documents.\n"
        "The most famous example is probably the Montreal Protocol on ozone-depleting substances, often cited as the most "
        "successful environmental treaty in history because of its near-universal ratification.\n"
        "Contrast that with climate change treaties, where the central tension has always been between developed and "
        "developing nations over who bears the greater responsibility for emissions reductions.\n"
        "This tension shaped the Kyoto Protocol's structure, which set binding targets only for developed nations — a design "
        "later criticised as one reason for the United States' withdrawal from the agreement.\n"
        "The 2015 Paris Agreement took a different approach entirely — rather than top-down binding targets, it relies on "
        "nationally determined contributions, submitted and updated by each country individually.\n"
        "Critics argue this makes Paris weaker on paper, since there's no direct penalty for missing targets — but supporters "
        "counter that near-universal participation is itself a form of leverage, since no major emitter sits outside the framework.\n"
        "Looking forward, much of the current legal debate centres on climate litigation — private citizens and NGOs increasingly "
        "using domestic courts to hold governments accountable, effectively creating a new enforcement pathway outside the treaty "
        "system itself.\n"
        "A landmark case here was brought before a European court, where the ruling established that inadequate climate action "
        "could constitute a breach of human rights.\n"
        "Whether this approach scales globally remains an open question, and it's one we'll pick up in more depth in next week's "
        "seminar on climate litigation."
    )
    blanks = [
        (31, "international (31) ___________", "concern"),
        (32, "negotiated in (32) ___________ documents", "protocol"),
        (33, "near-universal (33) ___________", "ratification"),
        (34, "greater (34) ___________ for emissions", "responsibility"),
        (35, "United States' (35) ___________ from", "withdrawal"),
        (36, "nationally determined (36) ___________", "contributions"),
        (37, "form of (37) ___________", "leverage"),
        (38, "enforcement (38) ___________ outside", "pathway"),
        (39, "breach of (39) ___________ rights", "human"),
        (40, "seminar on (40) ___________ litigation", "climate"),
    ]
    questions = []
    for num, label, ans in blanks:
        questions.append(
            {
                "number": num,
                "text_before": label.split("___________")[0].strip(),
                "text_after": "",
                "answer": ans,
                "accepted_answers": [ans],
            }
        )
    data = {
        "resource_id": "ielts_listening_mt4_section_4",
        "skill": "listening",
        "section": 4,
        "title": "International Environmental Law Lecture",
        "section_type": "academic_lecture",
        "speaker": "LECTURER",
        "estimated_audio_duration": "approx. 4 min",
        "total_questions": 10,
        "audio_file": "ElevenLabs_MT4_LT_S4.mp3",
        "mock_test_id": MOCK_ID,
        "transcript": transcript,
        "question_groups": [
            {
                "group_id": "mt4_s4_summary_31_40",
                "range": "31-40",
                "question_type": "sentence_completion",
                "instruction": "Complete the summary below. Write ONE WORD ONLY for each answer.",
                "questions": questions,
            }
        ],
    }
    write_json(MT4 / "LT/interface/BandForge_Listening_MT4_S4_Interface_Data.json", data)


def build_reading_p1() -> None:
    title, passage = extract_passage(MT4 / "RT" / "MT4 RT S1.docx")
    data = {
        "resource_id": "ielts_reading_mt4_passage_1",
        "skill": "reading",
        "task": 1,
        "title": title,
        "description": "Academic Reading — MT4 passage 1.",
        "mock_test_id": MOCK_ID,
        "passage_text": passage,
        "question_groups": [
            {
                "group_id": "mt4_p1_tfng_1_6",
                "range": "1-6",
                "question_type": "tfng",
                "instruction": "Do the following statements agree with the information given in Reading Passage 1?",
                "questions": [
                    {"number": 1, "statement": "Historical predictions of mass unemployment caused by technology have generally proven accurate.", "answer": "FALSE"},
                    {"number": 2, "statement": "AI differs from earlier automation because it can perform cognitive as well as physical tasks.", "answer": "TRUE"},
                    {"number": 3, "statement": "The 2023 study concluded that most affected jobs would be entirely eliminated.", "answer": "FALSE"},
                    {"number": 4, "statement": "Earlier waves of automation mainly disadvantaged middle-skill occupations.", "answer": "TRUE"},
                    {"number": 5, "statement": "All high-skill professions are equally vulnerable to AI-driven automation.", "answer": "FALSE"},
                    {"number": 6, "statement": "Universal basic income pilots have conclusively proven the approach is not fiscally viable.", "answer": "NOT GIVEN"},
                ],
            },
            {
                "group_id": "mt4_p1_features_7_10",
                "range": "7-10",
                "question_type": "matching_features",
                "instruction": "Match each statement with the correct ending, A–F.",
                "findings": [
                    {"label": "A", "text": "are favoured by policymakers despite weaker outcomes."},
                    {"label": "B", "text": "depends on institutional and policy choices, not the technology itself."},
                    {"label": "C", "text": "tend to produce better employment outcomes than broader alternatives."},
                    {"label": "D", "text": "may remove informal mentorship for junior employees."},
                    {"label": "E", "text": "have been rejected by most national governments."},
                    {"label": "F", "text": "require physical dexterity that AI cannot replicate."},
                ],
                "questions": [
                    {"number": 7, "prompt": "Narrow, technically focused retraining courses", "answer": "C"},
                    {"number": 8, "prompt": "Broad upskilling programmes", "answer": "A"},
                    {"number": 9, "prompt": "Flattened management hierarchies", "answer": "D"},
                    {"number": 10, "prompt": "The overall outcome of automation for workers", "answer": "B"},
                ],
            },
            {
                "group_id": "mt4_p1_sentence_11_13",
                "range": "11-13",
                "question_type": "sentence_completion",
                "instruction": "Answer the questions below using NO MORE THAN THREE WORDS from the passage for each answer.",
                "questions": [
                    {
                        "number": 11,
                        "sentence": "What term do economists use to describe the hollowing-out of middle-skill jobs? ______________",
                        "answer": "job polarisation",
                        "accepted_answers": ["job polarisation", "job polarization"],
                    },
                    {
                        "number": 12,
                        "sentence": "According to the passage, what capability allows manual service jobs to remain relatively insulated from automation? ______________",
                        "answer": "physical dexterity",
                        "accepted_answers": ["physical dexterity", "situational judgement", "situational judgment"],
                    },
                    {
                        "number": 13,
                        "sentence": "What have some firms started reducing as AI takes on more review tasks? ______________",
                        "answer": "middle managers",
                        "accepted_answers": ["middle managers", "middle management"],
                    },
                ],
            },
        ],
    }
    write_json(MT4 / "RT/interface/BandForge_Reading_MT4_P1_Interface_Data.json", data)


def build_reading_p2() -> None:
    title, passage = extract_passage(MT4 / "RT" / "MT4 RT S2.docx")
    data = {
        "resource_id": "ielts_reading_mt4_passage_2",
        "skill": "reading",
        "task": 2,
        "title": title,
        "description": "Academic Reading — MT4 passage 2.",
        "mock_test_id": MOCK_ID,
        "passage_text": passage,
        "question_groups": [
            {
                "group_id": "mt4_p2_ynng_14_19",
                "range": "14-19",
                "question_type": "tfng",
                "options_variant": "yes_no",
                "instruction": "Do the following statements agree with the claims of the writer?",
                "questions": [
                    {"number": 14, "statement": "Cognitive biases occur in random, unpredictable patterns.", "answer": "NO"},
                    {"number": 15, "statement": "The wheel-spinning experiment showed that arbitrary numbers can influence unrelated estimates.", "answer": "YES"},
                    {"number": 16, "statement": "Anchoring effects are limited to laboratory settings and do not occur in real-world negotiations.", "answer": "NO"},
                    {"number": 17, "statement": "Highly educated individuals are generally less susceptible to confirmation bias than others.", "answer": "NO"},
                    {"number": 18, "statement": "Loss aversion means losses are felt more intensely than equivalent gains are enjoyed.", "answer": "YES"},
                    {"number": 19, "statement": "Retirement scheme defaults were redesigned in direct response to loss aversion research.", "answer": "YES"},
                ],
            },
            {
                "group_id": "mt4_p2_info_20_23",
                "range": "20-23",
                "question_type": "matching_information",
                "instruction": "Which paragraph contains the following information? Write the correct letter, C–F.",
                "questions": [
                    {"number": 20, "statement": "An example of a bias being exploited by policymakers to promote better outcomes", "answer": "F"},
                    {"number": 21, "statement": "A description of a bias affecting how people process politically charged information", "answer": "C"},
                    {"number": 22, "statement": "An explanation of why simply teaching people about bias often fails to reduce it", "answer": "E"},
                    {"number": 23, "statement": "A specific example of biased behaviour among financial investors", "answer": "D"},
                ],
            },
            {
                "group_id": "mt4_p2_summary_24_26",
                "range": "24-26",
                "question_type": "matching_features",
                "instruction": "Complete the summary below using words from the box. Write the correct letter, A–I.",
                "findings": [
                    {"label": "A", "text": "awareness"},
                    {"label": "B", "text": "decision-making environment"},
                    {"label": "C", "text": "bias blind spot"},
                    {"label": "D", "text": "salary"},
                    {"label": "E", "text": "false confidence"},
                    {"label": "F", "text": "anchoring effect"},
                    {"label": "G", "text": "motivated reasoning"},
                    {"label": "H", "text": "checklist"},
                    {"label": "I", "text": "immunity"},
                ],
                "questions": [
                    {"number": 24, "prompt": "Interventions aimed purely at raising ___ of cognitive bias have proven largely ineffective", "answer": "A"},
                    {"number": 25, "prompt": "sometimes even producing a ___, whereby people believe themselves less vulnerable than others", "answer": "C"},
                    {"number": 26, "prompt": "More effective approaches tend to focus on redesigning the ___ itself", "answer": "B"},
                ],
            },
        ],
    }
    write_json(MT4 / "RT/interface/BandForge_Reading_MT4_P2_Interface_Data.json", data)


def build_reading_p3() -> None:
    title, passage = extract_passage(MT4 / "RT" / "MT4 RT S3.docx")
    data = {
        "resource_id": "ielts_reading_mt4_passage_3",
        "skill": "reading",
        "task": 3,
        "title": title,
        "description": "Academic Reading — MT4 passage 3.",
        "mock_test_id": MOCK_ID,
        "passage_text": passage,
        "question_groups": [
            {
                "group_id": "mt4_p3_info_27_31",
                "range": "27-31",
                "question_type": "matching_information",
                "instruction": "Which paragraph contains the following information? Write the correct letter, A–G.",
                "questions": [
                    {"number": 27, "statement": "A description of an alternative model that does not rely on individual consent", "answer": "D"},
                    {"number": 28, "statement": "Mention of a disputed study on the economic effects of data regulation", "answer": "B"},
                    {"number": 29, "statement": "A general prediction about the future trajectory of data protection law", "answer": "G"},
                    {"number": 30, "statement": "An example illustrating the practical limits of consent-based frameworks", "answer": "E"},
                    {"number": 31, "statement": "A description of GDPR's core founding principles", "answer": "A"},
                ],
            },
            {
                "group_id": "mt4_p3_info_32_36",
                "range": "32-36",
                "question_type": "matching_information",
                "instruction": "Match each item with the correct paragraph, A–G.",
                "questions": [
                    {"number": 32, "prompt": "Terms-of-service agreements that are rarely read in full", "answer": "C"},
                    {"number": 33, "prompt": "Data categories proposed for special protection regardless of consent", "answer": "D"},
                    {"number": 34, "prompt": "Facial recognition data collected without any consent process", "answer": "E"},
                    {"number": 35, "prompt": "Compliance costs said to favour large technology firms", "answer": "B"},
                    {"number": 36, "prompt": "Aggregation of individually consented-to data producing unanticipated outcomes", "answer": "F"},
                ],
            },
            {
                "group_id": "mt4_p3_sentence_37_40",
                "range": "37-40",
                "question_type": "sentence_completion",
                "instruction": "Answer the questions below using NO MORE THAN THREE WORDS from the passage for each answer.",
                "questions": [
                    {
                        "number": 37,
                        "sentence": "What right, established under GDPR, allows individuals to request the erasure of their data? ______________",
                        "answer": "right to be forgotten",
                        "accepted_answers": ["right to be forgotten", "the right to be forgotten"],
                    },
                    {
                        "number": 38,
                        "sentence": "What term describes the situation where consent frameworks provide legal cover without genuine understanding? ______________",
                        "answer": "symbolic",
                        "accepted_answers": ["symbolic", "largely symbolic"],
                    },
                    {
                        "number": 39,
                        "sentence": "According to the passage, what should institutions bear responsibility for under the alternative data-protection model? ______________",
                        "answer": "minimise harm",
                        "accepted_answers": ["minimise harm", "minimize harm", "justify collection"],
                    },
                    {
                        "number": 40,
                        "sentence": "What kind of decisions does the passage cite as examples of the cumulative effects of aggregated data (insurance pricing, credit eligibility, and what else)? ______________",
                        "answer": "employment screening",
                        "accepted_answers": ["employment screening"],
                    },
                ],
            },
        ],
    }
    write_json(MT4 / "RT/interface/BandForge_Reading_MT4_P3_Interface_Data.json", data)


def build_writing() -> None:
    t1 = {
        "resource_id": "ielts_writing_mt4_task_1",
        "skill": "writing",
        "task": 1,
        "title": "WRITING TASK 1 — Adult obesity trends (USA, UK, Japan)",
        "mock_test_id": MOCK_ID,
        "question_type": "task1_academic",
        "prompt": (
            "You should spend about 20 minutes on this task.\n\n"
            "The graph below shows the percentage of adults classified as obese in the UK, the USA, and Japan "
            "between 1980 and 2020.\n\n"
            "Summarise the information by selecting and reporting the main features, and make comparisons where relevant.\n\n"
            "Write at least 150 words."
        ),
        "image_file": "MT4_WT_T1_chart.png",
        "image_key": "writing/m04/task1/chart.png",
        "options": {
            "min_words": 150,
            "image_url": "writing/m04/task1/chart.png",
            "title": "WRITING TASK 1 — Adult obesity rates (USA, UK, Japan)",
            "figure_label": "Figure 1",
            "chart": {
                "type": "line",
                "title": "Percentage of adults classified as obese, 1980–2020",
                "source": "Illustrative obesity trend data",
                "years": [1980, 1990, 2000, 2010, 2020],
                "y_max": 50,
                "series": [
                    {"label": "USA", "values": [15, 23, 31, 36, 42]},
                    {"label": "UK", "values": [7, 13, 21, 26, 28]},
                    {"label": "Japan", "values": [2.0, 2.5, 3.0, 3.5, 4.3]},
                ],
            },
        },
    }
    t2 = {
        "resource_id": "ielts_writing_mt4_task_2",
        "skill": "writing",
        "task": 2,
        "title": "WRITING TASK 2 — Misinformation on social media",
        "mock_test_id": MOCK_ID,
        "question_type": "task2_essay",
        "prompt": (
            "You should spend about 40 minutes on this task.\n\n"
            "Misinformation spreads rapidly through social media platforms. Why does this happen and how can it be effectively controlled?\n\n"
            "Give reasons for your answer and include any relevant examples from your own knowledge or experience.\n\n"
            "Write at least 250 words."
        ),
        "options": {"min_words": 250},
    }
    write_json(MT4 / "WT/interface/BandForge_Writing_MT4_T1_Interface_Data.json", t1)
    write_json(MT4 / "WT/interface/BandForge_Writing_MT4_T2_Interface_Data.json", t2)


def build_chart_png() -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available — skip chart PNG")
        return

    years = [1980, 1990, 2000, 2010, 2020]
    series = {
        "USA": [15, 23, 31, 36, 42],
        "UK": [7, 13, 21, 26, 28],
        "Japan": [2.0, 2.5, 3.0, 3.5, 4.3],
    }
    fig, ax = plt.subplots(figsize=(8, 5))
    for label, values in series.items():
        ax.plot(years, values, marker="o", linewidth=2, label=label)
    ax.set_title("Percentage of adults classified as obese, 1980–2020")
    ax.set_xlabel("Year")
    ax.set_ylabel("Obesity rate (%)")
    ax.set_ylim(0, 50)
    ax.legend()
    ax.grid(True, alpha=0.3)
    out = MT4 / "WT/interface/MT4_WT_T1_chart.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Wrote chart -> {out}")


def main() -> None:
    build_listening_s1()
    build_listening_s2()
    build_listening_s3()
    build_listening_s4()
    build_reading_p1()
    build_reading_p2()
    build_reading_p3()
    build_writing()
    build_chart_png()
    print("MT4 interface JSON complete.")


if __name__ == "__main__":
    main()
