"""Writing module timing and scoring thresholds."""

TASK1_DURATION_MINUTES = 20
TASK2_DURATION_MINUTES = 40
WRITING_GRACE_SECONDS = 60

MAX_ESSAY_LENGTH = 20_000

# IELTS minimum word counts per task. A response that meets the minimum earns
# the upper band range; shorter responses are scaled down.
WRITING_MIN_WORDS: dict[int, int] = {
    1: 150,
    2: 250,
}
