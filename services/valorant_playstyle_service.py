"""Discord-independent scoring for the VALORANT playstyle diagnosis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
    ) -> None:
        if (question_set is None) == (questions_path is None):
            raise ValueError("provide exactly one of question_set or questions_path")
        if question_set is None:
            assert questions_path is not None
            question_set = ValorantPlaystyleRepository(questions_path).load()
        self.question_set = question_set
        self._questions = {question.id: question for question in question_set.questions}
        self._max_scores = _calculate_max_scores(question_set)

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
