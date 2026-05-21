"""Unit tests for Listening answer evaluation."""

from app.listening.evaluation import calculate_band, is_answer_correct, score_answers


class TestGreenfieldAnswers:
    """Greenfield College Part 1 correct-answer matching."""

    def test_first_name_priya(self) -> None:
        assert is_answer_correct("Priya", "Priya")

    def test_surname_mehta(self) -> None:
        assert is_answer_correct("mehta", "Mehta")

    def test_nationality_indian(self) -> None:
        assert is_answer_correct("Indian", "Indian")

    def test_occupation_nurse(self) -> None:
        assert is_answer_correct("nurse", "nurse")

    def test_course_level(self) -> None:
        assert is_answer_correct(
            "upper intermediate",
            "upper intermediate",
        )

    def test_class_day_tuesday(self) -> None:
        assert is_answer_correct("Tuesday", "Tuesday")

    def test_start_date_variants(self) -> None:
        key = "14 March / fourteenth of March / 14th March"
        assert is_answer_correct("14 March", key)
        assert is_answer_correct("fourteenth of March", key)

    def test_course_fee_variants(self) -> None:
        key = "685 / £685 / six hundred eighty-five"
        assert is_answer_correct("685", key)
        assert is_answer_correct("£685", key)

    def test_payment_method(self) -> None:
        key = "bank / bank transfer"
        assert is_answer_correct("bank transfer", key)
        assert is_answer_correct("bank", key)

    def test_additional_note(self) -> None:
        key = "large print handouts / large print"
        assert is_answer_correct("large print", key)
        assert is_answer_correct("large print handouts", key)


class TestBandScaling:
    def test_ten_of_ten_scales_to_band(self) -> None:
        questions = [{"id": str(i), "correct_answer": "x", "skill_tag": "detail"} for i in range(10)]
        answers_by_qid = {str(i): "x" for i in range(10)}
        raw, total, _ = score_answers(questions=questions, answers_by_qid=answers_by_qid)
        assert raw == 10
        assert total == 10
        band = calculate_band(raw, total=10)
        assert band == 9.0

    def test_empty_answer_wrong(self) -> None:
        assert not is_answer_correct("", "Priya")
        assert not is_answer_correct(None, "Priya")
