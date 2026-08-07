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


def _service(policy=DEFAULT_CLASSIFICATION_POLICY) -> ValorantPlaystyleService:
    return ValorantPlaystyleService(questions_path=QUESTION_PATH, classification_policy=policy)


def _score(value: float, *, team=None, improvement=None, focus=None, win=None, missing=()):
    values = {
        "win": value if win is None else win,
        "team": value if team is None else team,
        "improvement": value if improvement is None else improvement,
        "focus": value if focus is None else focus,
        "feedback_receive": 0.0,
        "feedback_give": 0.0,
    }
    axes = MappingProxyType(
        {axis: AxisScore(0, 1, normalized) for axis, normalized in values.items()}
    )
    return PlaystyleScore(axes, (), missing)


def test_categories_are_only_the_stable_three_values() -> None:
    assert {category.value for category in PlaystyleCategory} == {
        "enjoy",
        "neutral",
        "gachi",
    }


def test_default_policy_values_and_feedback_exclusion() -> None:
    policy = DEFAULT_CLASSIFICATION_POLICY
    assert dict(policy.weights) == {
        "win": 0.20,
        "team": 0.35,
        "improvement": 0.25,
        "focus": 0.20,
    }
    assert sum(policy.weights.values()) == pytest.approx(1.0)
    assert policy.gachi_minimum == 0.65
    assert policy.neutral_minimum == 0.35
    assert dict(policy.gachi_axis_minimums) == {
        "team": 0.60,
        "improvement": 5 / 9,
        "focus": 5 / 9,
    }


@pytest.mark.parametrize(
    ("value", "category"),
    [
        (1.0, PlaystyleCategory.GACHI),
        (0.65, PlaystyleCategory.GACHI),
        (0.65 - 1e-9, PlaystyleCategory.NEUTRAL),
        (0.35, PlaystyleCategory.NEUTRAL),
        (0.35 - 1e-9, PlaystyleCategory.ENJOY),
        (0.0, PlaystyleCategory.ENJOY),
    ],
)
def test_three_category_boundaries(value: float, category: PlaystyleCategory) -> None:
    assert _service().classify(_score(value)).category is category


@pytest.mark.parametrize("axis", ["team", "improvement", "focus"])
def test_gachi_axis_gate_demotes_only_to_neutral(axis: str) -> None:
    values = {"team": 1.0, "improvement": 1.0, "focus": 1.0}
    values[axis] = DEFAULT_CLASSIFICATION_POLICY.gachi_axis_minimums[axis] - 1e-9
    result = _service().classify(_score(1.0, **values))

    assert result.weighted_score >= 0.65
    assert result.category is PlaystyleCategory.NEUTRAL


def test_gachi_has_no_win_gate() -> None:
    result = _service().classify(_score(1.0, win=0.0))
    assert result.weighted_score == pytest.approx(0.8)
    assert result.category is PlaystyleCategory.GACHI


def test_feedback_does_not_affect_classification() -> None:
    base = _score(0.5)
    changed_axes = dict(base.axes)
    changed_axes["feedback_receive"] = AxisScore(3, 3, 1.0)
    changed_axes["feedback_give"] = AxisScore(3, 3, 1.0)
    changed = PlaystyleScore(MappingProxyType(changed_axes), (), ())

    first = _service().classify(base)
    second = _service().classify(changed)
    assert first.weighted_score == second.weighted_score
    assert first.category is second.category


def test_incomplete_score_cannot_be_classified() -> None:
    with pytest.raises(IncompleteAnswersError):
        _service().classify(_score(1.0, missing=("q15",)))


def test_injected_threshold_changes_same_score_category() -> None:
    score = _score(0.60)
    strict = ClassificationPolicy(
        weights=DEFAULT_CLASSIFICATION_POLICY.weights,
        gachi_minimum=0.65,
        neutral_minimum=0.35,
        gachi_axis_minimums=DEFAULT_CLASSIFICATION_POLICY.gachi_axis_minimums,
    )
    relaxed = ClassificationPolicy(
        weights=DEFAULT_CLASSIFICATION_POLICY.weights,
        gachi_minimum=0.55,
        neutral_minimum=0.35,
        gachi_axis_minimums=DEFAULT_CLASSIFICATION_POLICY.gachi_axis_minimums,
    )
    assert _service(strict).classify(score).category is PlaystyleCategory.NEUTRAL
    assert _service(relaxed).classify(score).category is PlaystyleCategory.GACHI


@pytest.mark.parametrize(
    ("gachi", "neutral"),
    [(1.1, 0.35), (-0.1, 0.0), (0.65, -0.1), (0.65, 1.1), (0.5, 0.5), (0.4, 0.7)],
)
def test_policy_rejects_invalid_thresholds(gachi: float, neutral: float) -> None:
    with pytest.raises(ValueError):
        ClassificationPolicy(
            weights=DEFAULT_CLASSIFICATION_POLICY.weights,
            gachi_minimum=gachi,
            neutral_minimum=neutral,
            gachi_axis_minimums=DEFAULT_CLASSIFICATION_POLICY.gachi_axis_minimums,
        )
