from pathlib import Path
from types import MappingProxyType

import pytest

from services.valorant_playstyle_service import (
    DEFAULT_CLASSIFICATION_POLICY,
    AxisScore,
    ClassificationPolicy,
    IncompleteAnswersError,
    PlaystyleCategory,
    PlaystyleScore,
    ValorantPlaystyleService,
)

QUESTION_PATH = Path(__file__).parents[1] / "data" / "valorant_playstyle_questions.json"
PRIMARY_AXES = ("win", "team", "improvement", "focus")


@pytest.fixture
def service() -> ValorantPlaystyleService:
    return ValorantPlaystyleService(questions_path=QUESTION_PATH)


def _score(
    *,
    win: float,
    team: float,
    improvement: float,
    focus: float,
    feedback_receive: float = 0.0,
    feedback_give: float = 0.0,
    missing: tuple[str, ...] = (),
) -> PlaystyleScore:
    normalized = {
        "win": win,
        "team": team,
        "improvement": improvement,
        "focus": focus,
        "feedback_receive": feedback_receive,
        "feedback_give": feedback_give,
    }
    axes = {
        axis: AxisScore(score=0, max_score=1, normalized=value)
        for axis, value in normalized.items()
    }
    return PlaystyleScore(MappingProxyType(axes), (), missing)


def test_default_weights_are_complete_and_sum_to_one() -> None:
    policy = DEFAULT_CLASSIFICATION_POLICY

    assert dict(policy.weights) == {
        "win": 0.20,
        "team": 0.35,
        "improvement": 0.25,
        "focus": 0.20,
    }
    assert sum(policy.weights.values()) == pytest.approx(1.0)
    assert "feedback_receive" not in policy.weights
    assert "feedback_give" not in policy.weights


def test_policy_rejects_weights_that_do_not_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        ClassificationPolicy(
            weights={"win": 0.1, "team": 0.35, "improvement": 0.25, "focus": 0.2},
            gachi_weighted_minimum=0.8,
            gachi_axis_minimums=DEFAULT_CLASSIFICATION_POLICY.gachi_axis_minimums,
            gachi_leaning_weighted_minimum=0.65,
            gachi_leaning_axis_minimums=(
                DEFAULT_CLASSIFICATION_POLICY.gachi_leaning_axis_minimums
            ),
            balanced_minimum=0.45,
            enjoy_leaning_minimum=0.25,
        )


@pytest.mark.parametrize(
    ("normalized", "expected_weighted", "expected_category"),
    [
        (1.0, 1.0, PlaystyleCategory.GACHI),
        (0.0, 0.0, PlaystyleCategory.ENJOY),
    ],
)
def test_uniform_extremes(
    service: ValorantPlaystyleService,
    normalized: float,
    expected_weighted: float,
    expected_category: PlaystyleCategory,
) -> None:
    result = service.classify(
        _score(
            win=normalized,
            team=normalized,
            improvement=normalized,
            focus=normalized,
        )
    )

    assert result.weighted_score == pytest.approx(expected_weighted)
    assert result.category is expected_category


def test_gachi_at_exact_weighted_boundary(service: ValorantPlaystyleService) -> None:
    result = service.classify(_score(win=0.8, team=0.8, improvement=0.8, focus=0.8))

    assert result.weighted_score == pytest.approx(0.8)
    assert result.category is PlaystyleCategory.GACHI


@pytest.mark.parametrize(
    ("axis", "minimum"),
    [
        ("team", 0.8),
        ("improvement", 2 / 3),
        ("focus", 2 / 3),
        ("win", 5 / 9),
    ],
)
def test_gachi_accepts_each_axis_at_its_exact_minimum(
    service: ValorantPlaystyleService, axis: str, minimum: float
) -> None:
    values = dict.fromkeys(PRIMARY_AXES, 1.0)
    values[axis] = minimum

    result = service.classify(_score(**values))

    assert result.weighted_score >= 0.8
    assert result.category is PlaystyleCategory.GACHI


@pytest.mark.parametrize(
    ("axis", "minimum"),
    [
        ("team", 0.8),
        ("improvement", 2 / 3),
        ("focus", 2 / 3),
        ("win", 5 / 9),
    ],
)
def test_gachi_rejects_each_axis_just_below_its_minimum(
    service: ValorantPlaystyleService, axis: str, minimum: float
) -> None:
    values = dict.fromkeys(PRIMARY_AXES, 0.9)
    values[axis] = minimum - 1e-9

    result = service.classify(_score(**values))

    assert result.weighted_score >= 0.8
    assert result.category is not PlaystyleCategory.GACHI


def test_gachi_leaning_at_exact_weighted_boundary(
    service: ValorantPlaystyleService,
) -> None:
    result = service.classify(
        _score(win=0.65, team=0.65, improvement=0.65, focus=0.65)
    )

    assert result.weighted_score == pytest.approx(0.65)
    assert result.category is PlaystyleCategory.GACHI_LEANING


@pytest.mark.parametrize(
    ("axis", "minimum"),
    [("team", 0.6), ("improvement", 5 / 9), ("focus", 5 / 9)],
)
def test_gachi_leaning_accepts_each_axis_at_its_exact_minimum(
    service: ValorantPlaystyleService, axis: str, minimum: float
) -> None:
    values = dict.fromkeys(PRIMARY_AXES, 1.0)
    values[axis] = minimum

    result = service.classify(_score(**values))

    assert result.weighted_score >= 0.65
    assert result.category is PlaystyleCategory.GACHI_LEANING


def test_gachi_leaning_has_no_win_minimum(service: ValorantPlaystyleService) -> None:
    result = service.classify(_score(win=0.0, team=1.0, improvement=1.0, focus=1.0))

    assert result.weighted_score == pytest.approx(0.8)
    assert result.category is PlaystyleCategory.GACHI_LEANING


def test_high_weighted_score_cannot_bypass_team_gate(
    service: ValorantPlaystyleService,
) -> None:
    result = service.classify(_score(win=1.0, team=0.59, improvement=1.0, focus=1.0))

    assert result.weighted_score > 0.8
    assert result.category is PlaystyleCategory.BALANCED


@pytest.mark.parametrize("axis", ["improvement", "focus"])
def test_high_weighted_score_cannot_bypass_upper_axis_gate(
    service: ValorantPlaystyleService, axis: str
) -> None:
    values = dict.fromkeys(PRIMARY_AXES, 1.0)
    values[axis] = 5 / 9 - 1e-9

    result = service.classify(_score(**values))

    assert result.weighted_score > 0.8
    assert result.category is PlaystyleCategory.BALANCED


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        (0.45, PlaystyleCategory.BALANCED),
        (0.45 - 1e-9, PlaystyleCategory.ENJOY_LEANING),
        (0.25, PlaystyleCategory.ENJOY_LEANING),
        (0.25 - 1e-9, PlaystyleCategory.ENJOY),
    ],
)
def test_lower_classification_boundaries(
    service: ValorantPlaystyleService,
    normalized: float,
    expected: PlaystyleCategory,
) -> None:
    result = service.classify(
        _score(
            win=normalized,
            team=normalized,
            improvement=normalized,
            focus=normalized,
        )
    )

    assert result.weighted_score == pytest.approx(normalized)
    assert result.category is expected


def test_feedback_does_not_change_weighted_score_or_category(
    service: ValorantPlaystyleService,
) -> None:
    low_feedback = service.classify(
        _score(win=0.5, team=0.5, improvement=0.5, focus=0.5)
    )
    high_feedback = service.classify(
        _score(
            win=0.5,
            team=0.5,
            improvement=0.5,
            focus=0.5,
            feedback_receive=1.0,
            feedback_give=1.0,
        )
    )

    assert low_feedback.weighted_score == high_feedback.weighted_score
    assert low_feedback.category is high_feedback.category


def test_incomplete_score_cannot_be_classified(
    service: ValorantPlaystyleService,
) -> None:
    partial = service.score_partial({"q01": "a"})

    with pytest.raises(IncompleteAnswersError) as error:
        service.classify(partial)

    assert error.value.missing_question_ids == partial.missing_question_ids


def test_real_question_master_can_score_and_classify_complete_answers(
    service: ValorantPlaystyleService,
) -> None:
    answers = {
        question.id: max(
            question.choices,
            key=lambda choice: sum(choice.scores.values()),
        ).id
        for question in service.question_set.questions
    }

    result = service.classify_complete(answers)

    assert result.category is PlaystyleCategory.GACHI
    assert result.weighted_score == pytest.approx(1.0)
    assert result.score.missing_question_ids == ()
    assert all(result.score.axes[axis].normalized == 1.0 for axis in PRIMARY_AXES)
