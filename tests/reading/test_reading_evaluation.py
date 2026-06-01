"""Reading band table and scoring."""

from app.reading.evaluation import calculate_reading_band, is_answer_correct, score_answers


def test_is_answer_correct_tfng_and_completion():
    assert is_answer_correct("false", "FALSE")
    assert is_answer_correct("NOT GIVEN", "not given")
    assert is_answer_correct("loss aversion", "loss aversion")
    assert is_answer_correct("24", "twenty-four/twenty four/24")
    assert not is_answer_correct("true", "FALSE")


def test_calculate_reading_band_scales_partial_test():
    # 13/13 on a 13-q test should scale to 40 raw → band 9
    band = calculate_reading_band(13, total=13)
    assert band == 9.0


def test_calculate_reading_band_table_samples():
    assert calculate_reading_band(30, total=40) == 7.0
    assert calculate_reading_band(23, total=40) == 6.0
    assert calculate_reading_band(0, total=40) == 0.0


def test_score_answers_counts():
    questions = [
        {"id": "a", "correct_answer": "TRUE", "skill_tag": "tfng"},
        {"id": "b", "correct_answer": "FALSE", "skill_tag": "tfng"},
    ]
    raw, total, rows = score_answers(
        questions=questions,
        answers_by_qid={"a": "TRUE", "b": "TRUE"},
    )
    assert total == 2
    assert raw == 1
    assert len(rows) == 2
