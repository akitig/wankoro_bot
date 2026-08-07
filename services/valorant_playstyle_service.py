"""Discord-independent scoring for the VALORANT playstyle diagnosis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from math import isclose
from pathlib import Path
from types import MappingProxyType

from repositories.valorant_playstyle_repository import (
    SUPPORTED_AXES,
    Choice,
    Question,
    QuestionSet,
    ValorantPlaystyleRepository,
)


class AnswerValidationError(ValueError):
    """Raised when answers do not match the loaded question set."""


class IncompleteAnswersError(AnswerValidationError):
    """Raised when a completed diagnosis is missing one or more answers."""

    def __init__(self, missing_question_ids: tuple[str, ...]) -> None:
        self.missing_question_ids = missing_question_ids
        super().__init__(
            "missing answers for questions: " + ", ".join(missing_question_ids)
        )


@dataclass(frozen=True)
class AxisScore:
    score: int
    max_score: int
    normalized: float


@dataclass(frozen=True)
class PlaystyleScore:
    axes: Mapping[str, AxisScore]
    answered_question_ids: tuple[str, ...]
    missing_question_ids: tuple[str, ...]


class PlaystyleCategory(str, Enum):
    ENJOY = "enjoy"
    ENJOY_LEANING = "enjoy_leaning"
    BALANCED = "balanced"
    GACHI_LEANING = "gachi_leaning"
    GACHI = "gachi"


@dataclass(frozen=True)
class ClassificationPolicy:
    weights: Mapping[str, float]
    gachi_weighted_minimum: float
    gachi_axis_minimums: Mapping[str, float]
    gachi_leaning_weighted_minimum: float
    gachi_leaning_axis_minimums: Mapping[str, float]
    balanced_minimum: float
    enjoy_leaning_minimum: float

    def __post_init__(self) -> None:
        primary_axes = {"win", "team", "improvement", "focus"}
        if set(self.weights) != primary_axes:
            raise ValueError("classification weights must contain the four primary axes")
        if not isclose(sum(self.weights.values()), 1.0):
            raise ValueError("classification weights must sum to 1.0")
        if set(self.gachi_axis_minimums) != primary_axes:
            raise ValueError("GACHI minimums must contain the four primary axes")
        if set(self.gachi_leaning_axis_minimums) != {
            "team",
            "improvement",
            "focus",
        }:
            raise ValueError(
                "GACHI_LEANING minimums must contain team, improvement, and focus"
            )


DEFAULT_CLASSIFICATION_POLICY = ClassificationPolicy(
    weights=MappingProxyType(
        {"win": 0.20, "team": 0.35, "improvement": 0.25, "focus": 0.20}
    ),
    gachi_weighted_minimum=0.80,
    gachi_axis_minimums=MappingProxyType(
        {"team": 0.80, "improvement": 2 / 3, "focus": 2 / 3, "win": 5 / 9}
    ),
    gachi_leaning_weighted_minimum=0.65,
    gachi_leaning_axis_minimums=MappingProxyType(
        {"team": 0.60, "improvement": 5 / 9, "focus": 5 / 9}
    ),
    balanced_minimum=0.45,
    enjoy_leaning_minimum=0.25,
)


@dataclass(frozen=True)
class PlaystyleClassification:
    category: PlaystyleCategory
    weighted_score: float
    score: PlaystyleScore


def _calculate_max_scores(question_set: QuestionSet) -> dict[str, int]:
    maximums = dict.fromkeys(SUPPORTED_AXES, 0)
    for question in question_set.questions:
        for axis in SUPPORTED_AXES:
            maximums[axis] += max(
                (choice.scores.get(axis, 0) for choice in question.choices),
                default=0,
            )
    return maximums


class ValorantPlaystyleService:
    """Validate answers and calculate per-axis scores without classification."""

    def __init__(
        self,
        question_set: QuestionSet | None = None,
        *,
        questions_path: Path | None = None,
        classification_policy: ClassificationPolicy = DEFAULT_CLASSIFICATION_POLICY,
    ) -> None:
        if (question_set is None) == (questions_path is None):
            raise ValueError("provide exactly one of question_set or questions_path")
        if question_set is None:
            assert questions_path is not None
            question_set = ValorantPlaystyleRepository(questions_path).load()
        self.question_set = question_set
        self._questions = {question.id: question for question in question_set.questions}
        self._max_scores = _calculate_max_scores(question_set)
        self.classification_policy = classification_policy

    @property
    def max_scores(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._max_scores))

    def missing_question_ids(self, answers: Mapping[str, str]) -> tuple[str, ...]:
        self._validate_answer_references(answers)
        return tuple(
            question.id
            for question in self.question_set.questions
            if question.id not in answers
        )

    def score_partial(self, answers: Mapping[str, str]) -> PlaystyleScore:
        """Score any valid subset of answers and report what remains unanswered."""

        choices = self._validate_answer_references(answers)
        raw_scores = dict.fromkeys(SUPPORTED_AXES, 0)
        for choice in choices:
            for axis, score in choice.scores.items():
                raw_scores[axis] += score

        missing = tuple(
            question.id
            for question in self.question_set.questions
            if question.id not in answers
        )
        axis_scores = {
            axis: AxisScore(
                score=raw_scores[axis],
                max_score=self._max_scores[axis],
                normalized=(
                    raw_scores[axis] / self._max_scores[axis]
                    if self._max_scores[axis]
                    else 0.0
                ),
            )
            for axis in SUPPORTED_AXES
        }
        answered = tuple(
            question.id
            for question in self.question_set.questions
            if question.id in answers
        )
        return PlaystyleScore(MappingProxyType(axis_scores), answered, missing)

    def score_complete(self, answers: Mapping[str, str]) -> PlaystyleScore:
        """Require every loaded question to be answered, then calculate scores."""

        result = self.score_partial(answers)
        if result.missing_question_ids:
            raise IncompleteAnswersError(result.missing_question_ids)
        return result

    def classify_complete(
        self, answers: Mapping[str, str]
    ) -> PlaystyleClassification:
        """Score and classify a complete set of answers."""

        return self.classify(self.score_complete(answers))

    def classify(self, score: PlaystyleScore) -> PlaystyleClassification:
        """Classify an already scored result only when no answers are missing."""

        if score.missing_question_ids:
            raise IncompleteAnswersError(score.missing_question_ids)
        policy = self.classification_policy
        weighted_score = sum(
            score.axes[axis].normalized * weight
            for axis, weight in policy.weights.items()
        )

        if weighted_score >= policy.gachi_weighted_minimum and self._meets_minimums(
            score, policy.gachi_axis_minimums
        ):
            category = PlaystyleCategory.GACHI
        elif (
            weighted_score >= policy.gachi_leaning_weighted_minimum
            and self._meets_minimums(score, policy.gachi_leaning_axis_minimums)
        ):
            category = PlaystyleCategory.GACHI_LEANING
        elif weighted_score >= policy.balanced_minimum:
            category = PlaystyleCategory.BALANCED
        elif weighted_score >= policy.enjoy_leaning_minimum:
            category = PlaystyleCategory.ENJOY_LEANING
        else:
            category = PlaystyleCategory.ENJOY
        return PlaystyleClassification(category, weighted_score, score)

    @staticmethod
    def _meets_minimums(
        score: PlaystyleScore, minimums: Mapping[str, float]
    ) -> bool:
        return all(
            score.axes[axis].normalized >= minimum
            for axis, minimum in minimums.items()
        )

    def _validate_answer_references(
        self, answers: Mapping[str, str]
    ) -> list[Choice]:
        if not isinstance(answers, Mapping):
            raise AnswerValidationError("answers must be a mapping")
        choices = []
        for question_id, choice_id in answers.items():
            question = self._questions.get(question_id)
            if question is None:
                raise AnswerValidationError(f"unknown question id: {question_id}")
            choice = self._find_choice(question, choice_id)
            if choice is None:
                raise AnswerValidationError(
                    f"unknown choice id for {question_id}: {choice_id}"
                )
            choices.append(choice)
        return choices

    @staticmethod
    def _find_choice(question: Question, choice_id: str) -> Choice | None:
        return next((choice for choice in question.choices if choice.id == choice_id), None)
