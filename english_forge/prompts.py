"""Prompt pack — Sets 1–4 with anchors + reference example answers.

Reference transcripts are listen-only models (not the only correct answer).
Grade bands map to product sets:
  1-3  → Set 1 (Class 1–3)
  4-5  → Set 2 (Class 3–6)
  6-8  → Set 3 (Class 6–8)
  9-10 → Set 4 (Class 8–10)
"""

from __future__ import annotations

from .schemas import GradeBand, SpeakPrompt

_META = {
    "1-3": (20, 30),
    "4-5": (30, 40),
    "6-8": (45, 60),
    "9-10": (60, 90),
}


def _p(
    band: GradeBand,
    pid: str,
    title: str,
    prompt: str,
    hint: str | None,
    *,
    reference_transcript: str | None = None,
    is_anchor: bool = False,
    skills: list[str] | None = None,
    difficulty: str = "easy",
) -> SpeakPrompt:
    target, mx = _META[band]
    return SpeakPrompt(
        id=pid,
        grade_band=band,
        title=title,
        prompt=prompt,
        listen_hint=hint,
        target_duration_sec=target,
        max_duration_sec=mx,
        reference_transcript=reference_transcript,
        is_anchor=is_anchor,
        skills=skills or [],
        difficulty=difficulty,
    )


# --- Set 1 · Class 1–3 ---
PROMPTS_1_3: list[SpeakPrompt] = [
    _p(
        "1-3",
        "ef-1-3-intro",
        "About you",
        "Tell me about yourself.",
        "Say your name, age or class, and one thing you like.",
        reference_transcript=(
            "Hello! My name is Aarav. I am eight years old. I study in Class 3. "
            "I like playing with my friends. My favourite colour is blue. I am happy to be here."
        ),
        is_anchor=True,
        skills=["self_introduction", "fluency", "sentence_formation"],
    ),
    _p(
        "1-3",
        "ef-1-3-family",
        "My family",
        "Tell me about your family.",
        "Say who lives with you and one thing you do together.",
        reference_transcript=(
            "I have a small family. I live with my mother, father, and my sister. "
            "We like eating dinner together. I love my family very much."
        ),
        is_anchor=True,
        skills=["family", "sentence_formation"],
    ),
    _p(
        "1-3",
        "ef-1-3-school",
        "My school",
        "Tell me about your school.",
        "Say one thing you like at school.",
        reference_transcript=(
            "My school is very nice. I have many friends there. I like my classroom. "
            "My favourite subject is English. I like going to school every day."
        ),
        is_anchor=True,
        skills=["school", "vocabulary"],
    ),
    _p(
        "1-3",
        "ef-1-3-game",
        "Favourite game",
        "What is your favourite game?",
        "Name the game and say why you like it.",
        reference_transcript=(
            "My favourite game is cricket. I play cricket with my friends. "
            "I like hitting the ball and running. I feel very happy when I play cricket."
        ),
        skills=["hobbies", "sentence_formation"],
    ),
    _p(
        "1-3",
        "ef-1-3-after-school",
        "After school",
        "What do you like to do after school?",
        "Say one or two things you do when you come home.",
        reference_transcript=(
            "After school, I come home and have some food. Then I do my homework. "
            "After that, I like to play with my friends or watch cartoons."
        ),
        skills=["daily_routine", "fluency"],
    ),
]

# --- Set 2 · Class 3–6 (band id 4-5) ---
PROMPTS_4_5: list[SpeakPrompt] = [
    _p(
        "4-5",
        "ef-4-5-intro",
        "Introduce yourself",
        "Introduce yourself.",
        "Share your name, class, family, and two things you enjoy.",
        reference_transcript=(
            "Hi, my name is Ananya. I am eleven years old and I study in Class 5. "
            "I live with my parents and my younger brother. I enjoy reading storybooks "
            "and playing badminton. I also like learning new things at school."
        ),
        is_anchor=True,
        skills=["self_introduction", "fluency", "vocabulary"],
        difficulty="easy",
    ),
    _p(
        "4-5",
        "ef-4-5-school",
        "Your school",
        "Tell me about your school.",
        "Mention places at school and what you like learning.",
        reference_transcript=(
            "I study in a school near my home. It has many classrooms, a big playground, "
            "and a library. My favourite subject is science because I enjoy learning how "
            "things work. I also like spending time with my friends during lunch."
        ),
        is_anchor=True,
        skills=["school", "sentence_connection"],
    ),
    _p(
        "4-5",
        "ef-4-5-friend",
        "Best friend",
        "Tell me about your best friend.",
        "Say their name, how you know them, and what you do together.",
        reference_transcript=(
            "My best friend's name is Riya. We study in the same class and sit together "
            "sometimes. She is kind and funny, and she always helps me when I have a problem. "
            "We enjoy playing badminton and talking during our free time."
        ),
        skills=["friendship", "description"],
    ),
    _p(
        "4-5",
        "ef-4-5-hobby",
        "Favourite hobby",
        "What is your favourite hobby?",
        "Say what you do and why you enjoy it.",
        reference_transcript=(
            "My favourite hobby is drawing. I started drawing when I was very young. "
            "I usually draw animals, houses, and nature. Drawing helps me relax, and I like "
            "showing my pictures to my family."
        ),
        skills=["hobbies", "reasons"],
    ),
    _p(
        "4-5",
        "ef-4-5-favourite-day",
        "Favourite day",
        "Tell me about your favourite day of the week.",
        "Say which day and what you usually do.",
        reference_transcript=(
            "My favourite day is Sunday because I don't have school. I usually wake up "
            "a little late and have breakfast with my family. In the afternoon, I play "
            "outside with my friends. In the evening, we sometimes watch a movie together."
        ),
        skills=["narration", "daily_routine"],
    ),
]

# --- Set 3 · Class 6–8 ---
PROMPTS_6_8: list[SpeakPrompt] = [
    _p(
        "6-8",
        "ef-6-8-intro",
        "About you",
        "Tell me about yourself.",
        "Introduce yourself and share interests plus one future hope.",
        reference_transcript=(
            "Hello, my name is Kabir. I am thirteen years old and I study in Class 8. "
            "I enjoy playing football, reading science-fiction books, and spending time "
            "with my friends. My favourite subject is science because I am curious about "
            "how the world works. In the future, I would like to learn more about technology."
        ),
        is_anchor=True,
        skills=["self_introduction", "fluency", "vocabulary"],
        difficulty="medium",
    ),
    _p(
        "6-8",
        "ef-6-8-school",
        "Your school",
        "Tell me about your school.",
        "Describe places, a favourite subject, and one activity.",
        reference_transcript=(
            "My school is a friendly and active place. There are many classrooms, a library, "
            "a science laboratory, and a large playground. I particularly enjoy science classes "
            "because our teachers often explain topics through experiments. I also like "
            "participating in school activities because they help me become more confident."
        ),
        is_anchor=True,
        skills=["school", "explanation"],
        difficulty="medium",
    ),
    _p(
        "6-8",
        "ef-6-8-teacher",
        "Favourite teacher",
        "Describe your favourite teacher.",
        "Say who they are and why their classes help you.",
        reference_transcript=(
            "My favourite teacher is my science teacher, Mr. Sharma. He explains difficult "
            "topics using simple examples, so they are easier to understand. He also "
            "encourages us to ask questions instead of simply memorising information. "
            "I like his classes because they are interesting and interactive."
        ),
        skills=["description", "reasons"],
        difficulty="medium",
    ),
    _p(
        "6-8",
        "ef-6-8-free-time",
        "Free time",
        "What do you like doing in your free time?",
        "Mention two or three activities and why they help you.",
        reference_transcript=(
            "In my free time, I usually play football with my friends. I also enjoy watching "
            "educational videos and reading books. Sometimes I help my parents with small "
            "things around the house. I think having different activities is useful because "
            "it helps me learn and relax at the same time."
        ),
        skills=["hobbies", "explanation"],
        difficulty="medium",
    ),
    _p(
        "6-8",
        "ef-6-8-study-opinion",
        "Study habits",
        "Which is better: studying alone or studying with friends?",
        "Give your preference and one clear reason for each side.",
        reference_transcript=(
            "I think studying with friends can be better for some subjects. When we study "
            "together, we can explain difficult ideas to each other and discuss different "
            "answers. However, studying alone can be more useful when I need to concentrate. "
            "So, I think both methods are useful depending on the situation."
        ),
        skills=["opinion", "comparison"],
        difficulty="medium",
    ),
]

# --- Set 4 · Class 8–10 (band id 9-10) ---
PROMPTS_9_10: list[SpeakPrompt] = [
    _p(
        "9-10",
        "ef-9-10-intro",
        "Introduce yourself",
        "Introduce yourself.",
        "Share who you are, interests, and a longer-term goal.",
        reference_transcript=(
            "Hi, my name is Meera. I am fifteen years old and I am currently studying in "
            "Class 10. I would describe myself as a curious and hardworking student. I enjoy "
            "reading, playing badminton, and learning about technology. I am especially "
            "interested in science because I like understanding how things work. In the "
            "future, I hope to develop skills that will help me pursue a career I enjoy."
        ),
        is_anchor=True,
        skills=["self_introduction", "fluency", "vocabulary"],
        difficulty="hard",
    ),
    _p(
        "9-10",
        "ef-9-10-school",
        "Your school",
        "Tell me about your school.",
        "Go beyond buildings — what role has school played for you?",
        reference_transcript=(
            "My school has played an important role in my life because I have learned much "
            "more than just academic subjects there. Apart from regular classes, we have "
            "sports activities, competitions, and cultural events. I particularly appreciate "
            "the teachers because many of them encourage students to ask questions and think "
            "independently. My favourite part of school is probably spending time with my "
            "classmates because we learn from each other as well."
        ),
        is_anchor=True,
        skills=["school", "reflection"],
        difficulty="hard",
    ),
    _p(
        "9-10",
        "ef-9-10-friend",
        "Good friend",
        "What makes someone a good friend?",
        "Give reasons and one example of respectful friendship.",
        reference_transcript=(
            "I think a good friend is someone who is trustworthy, supportive, and honest. "
            "A good friend should be able to listen when you have a problem and should also "
            "tell you the truth when you make a mistake. I also think friendship should be "
            "based on respect. You don't have to agree with your friends all the time, but "
            "you should respect their opinions."
        ),
        skills=["opinion", "reasoning"],
        difficulty="hard",
    ),
    _p(
        "9-10",
        "ef-9-10-tech",
        "Technology",
        "Is technology helpful for students?",
        "Give one benefit and one careful point, then your view.",
        reference_transcript=(
            "I think technology can be very helpful for students if it is used properly. "
            "Students can use the internet to find information, watch educational videos, "
            "and practise different skills. However, technology can also become a distraction, "
            "especially when students spend too much time on games or social media. Therefore, "
            "I think the important thing is to use technology in a balanced and responsible way."
        ),
        skills=["opinion", "comparison"],
        difficulty="hard",
    ),
    _p(
        "9-10",
        "ef-9-10-memorable",
        "Memorable day",
        "Tell me about a memorable day in your life.",
        "Narrate what happened and what you learned.",
        reference_transcript=(
            "One memorable day for me was when I participated in a school competition. I was "
            "nervous before going on stage because I had never spoken in front of so many "
            "people before. However, once I started, I became more comfortable and finished "
            "my presentation successfully. My teachers and friends congratulated me afterwards. "
            "That experience taught me that preparation can help us become more confident."
        ),
        skills=["narration", "reflection"],
        difficulty="hard",
    ),
]

_BY_BAND: dict[GradeBand, list[SpeakPrompt]] = {
    "1-3": PROMPTS_1_3,
    "4-5": PROMPTS_4_5,
    "6-8": PROMPTS_6_8,
    "9-10": PROMPTS_9_10,
}


def list_prompts(grade_band: GradeBand) -> list[SpeakPrompt]:
    return list(_BY_BAND.get(grade_band) or [])


def get_prompt(prompt_id: str) -> SpeakPrompt | None:
    for band_prompts in _BY_BAND.values():
        for p in band_prompts:
            if p.id == prompt_id:
                return p
    return None


def default_prompt(grade_band: GradeBand) -> SpeakPrompt:
    items = list_prompts(grade_band)
    if items:
        return items[0]
    return _p(
        grade_band,
        f"ef-{grade_band}-fallback",
        "About you",
        "Tell me about yourself.",
        None,
    )
