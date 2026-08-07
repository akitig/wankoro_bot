from pathlib import Path

import pytest

from repositories.valorant_playstyle_repository import validate_question_data
from services.valorant_playstyle_service import (
    AnswerValidationError,
    IncompleteAnswersError,
    ValorantPlaystyleService,
)

QUESTION_PATH = Path(__file__).parents[1] / "data" / "valorant_playstyle_questions.json"
EXPECTED_MAX_SCORES = {
    "win": 9,
    "team": 15,
    "improvement": 9,
    "focus": 9,
    "feedback_receive": 3,
    "feedback_give": 3,
}


@pytest.fixture
def service() -> ValorantPlaystyleService:
    return ValorantPlaystyleService(questions_path=QUESTION_PATH)


def _answers_for_extreme(
    service: ValorantPlaystyleService, *, maximum: bool
) -> dict[str, str]:
    def total_score(choice) -> int:
        return sum(choice.scores.values())

    answers = {}
    for question in service.question_set.questions:
        selected = (max if maximum else min)(question.choices, key=total_score)
        answers[question.id] = selected.id
    return answers


def test_max_scores_are_derived_from_current_question_master(
    service: ValorantPlaystyleService,
) -> None:
    assert dict(service.max_scores) == EXPECTED_MAX_SCORES


def test_full_maximum_normalizes_every_axis_to_one(
    service: ValorantPlaystyleService,
) -> None:
    result = service.score_complete(_answers_for_extreme(service, maximum=True))

    assert result.missing_question_ids == ()
    for axis, expected_maximum in EXPECTED_MAX_SCORES.items():
        assert result.axes[axis].score == expected_maximum
        assert result.axes[axis].max_score == expected_maximum
        assert result.axes[axis].normalized == 1.0


def test_full_minimum_scores_every_axis_as_zero(
    service: ValorantPlaystyleService,
) -> None:
    result = service.score_complete(_answers_for_extreme(service, maximum=False))

    assert all(axis.score == 0 for axis in result.axes.values())
    assert all(axis.normalized == 0.0 for axis in result.axes.values())


@pytest.mark.parametrize(
    ("choice_id", "expected_team", "expected_win"),
    [("a", 3, 3), ("d", 1, 2)],
)
def test_q15_scores_multiple_axes(
    service: ValorantPlaystyleService,
    choice_id: str,
    expected_team: int,
    expected_win: int,
) -> None:
    result = service.score_partial({"q15": choice_id})

    assert result.axes["team"].score == expected_team
    assert result.axes["win"].score == expected_win


def test_feedback_questions_do_not_affect_primary_axes(
    service: ValorantPlaystyleService,
) -> None:
    result = service.score_partial({"q13": "b", "q14": "a"})

    assert result.axes["feedback_receive"].score == 3
    assert result.axes["feedback_give"].score == 3
    for axis in ("win", "team", "improvement", "focus"):
        assert result.axes[axis].score == 0


def test_partial_scoring_reports_missing_questions_in_master_order(
    service: ValorantPlaystyleService,
) -> None:
    result = service.score_partial({"q03": "a", "q01": "c"})

    assert result.answered_question_ids == ("q01", "q03")
    assert result.missing_question_ids == tuple(
        question_id
        for question_id in (f"q{index:02d}" for index in range(1, 16))
        if question_id not in {"q01", "q03"}
    )
    assert service.missing_question_ids({"q03": "a", "q01": "c"}) == (
        result.missing_question_ids
    )


def test_complete_scoring_rejects_missing_answers(
    service: ValorantPlaystyleService,
) -> None:
    with pytest.raises(IncompleteAnswersError) as error:
        service.score_complete({"q01": "a"})

    assert error.value.missing_question_ids[0] == "q02"
    assert error.value.missing_question_ids[-1] == "q15"


def test_unknown_question_is_rejected(service: ValorantPlaystyleService) -> None:
    with pytest.raises(AnswerValidationError, match="unknown question id"):
        service.score_partial({"q99": "a"})


def test_unknown_choice_is_rejected(service: ValorantPlaystyleService) -> None:
    with pytest.raises(AnswerValidationError, match="unknown choice id"):
        service.score_partial({"q01": "unknown"})


def test_zero_maximum_axis_normalizes_safely() -> None:
    question_set = validate_question_data(
        {
            "schema_version": 1,
            "diagnosis_version": "test",
            "questions": [
                {
                    "id": "q01",
                    "question": "Question",
                    "choices": [
                        {"id": "a", "text": "A", "scores": {"win": 0}}
                    ],
                }
            ],
        }
    )
    service = ValorantPlaystyleService(question_set)

    result = service.score_complete({"q01": "a"})

    assert result.axes["team"].max_score == 0
    assert result.axes["team"].normalized == 0.0
