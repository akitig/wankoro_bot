"""Validated question master data for the VALORANT playstyle diagnosis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from storage.json_store import load_json

SCHEMA_VERSION = 1
SUPPORTED_AXES = (
    "win",
    "team",
    "improvement",
    "focus",
    "feedback_receive",
    "feedback_give",
)
SUPPORTED_AXIS_SET = frozenset(SUPPORTED_AXES)


class QuestionValidationError(ValueError):
    """Raised when question master data violates the supported schema."""


@dataclass(frozen=True)
class Choice:
    id: str
    text: str
    scores: Mapping[str, int]


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    choices: tuple[Choice, ...]


@dataclass(frozen=True)
class QuestionSet:
    schema_version: int
    diagnosis_version: str
    questions: tuple[Question, ...]


def _required_nonempty_string(data: Mapping[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise QuestionValidationError(f"{context}.{key} must be a non-empty string")
    return value


def _validate_scores(raw_scores: Any, context: str) -> Mapping[str, int]:
    if not isinstance(raw_scores, dict) or not raw_scores:
        raise QuestionValidationError(f"{context}.scores must be a non-empty object")

    scores: dict[str, int] = {}
    for axis, score in raw_scores.items():
        if axis not in SUPPORTED_AXIS_SET:
            raise QuestionValidationError(f"{context}.scores has unknown axis: {axis}")
        if isinstance(score, bool) or not isinstance(score, int):
            raise QuestionValidationError(
                f"{context}.scores.{axis} must be an integer"
            )
        if not 0 <= score <= 3:
            raise QuestionValidationError(
                f"{context}.scores.{axis} must be between 0 and 3"
            )
        scores[axis] = score
    return MappingProxyType(scores)


def validate_question_data(data: Any) -> QuestionSet:
    """Validate decoded JSON and return immutable domain values."""

    if not isinstance(data, dict):
        raise QuestionValidationError("question data must be an object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise QuestionValidationError(
            f"schema_version must be {SCHEMA_VERSION}"
        )
    diagnosis_version = _required_nonempty_string(
        data, "diagnosis_version", "question data"
    )
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise QuestionValidationError("questions must be a non-empty array")

    question_ids: set[str] = set()
    questions: list[Question] = []
    for question_index, raw_question in enumerate(raw_questions):
        context = f"questions[{question_index}]"
        if not isinstance(raw_question, dict):
            raise QuestionValidationError(f"{context} must be an object")
        question_id = _required_nonempty_string(raw_question, "id", context)
        if question_id in question_ids:
            raise QuestionValidationError(f"duplicate question id: {question_id}")
        question_ids.add(question_id)
        question_text = _required_nonempty_string(raw_question, "question", context)
        raw_choices = raw_question.get("choices")
        if not isinstance(raw_choices, list) or not raw_choices:
            raise QuestionValidationError(f"{context}.choices must be a non-empty array")

        choice_ids: set[str] = set()
        choices: list[Choice] = []
        for choice_index, raw_choice in enumerate(raw_choices):
            choice_context = f"{context}.choices[{choice_index}]"
            if not isinstance(raw_choice, dict):
                raise QuestionValidationError(f"{choice_context} must be an object")
            choice_id = _required_nonempty_string(raw_choice, "id", choice_context)
            if choice_id in choice_ids:
                raise QuestionValidationError(
                    f"duplicate choice id in {question_id}: {choice_id}"
                )
            choice_ids.add(choice_id)
            choice_text = _required_nonempty_string(raw_choice, "text", choice_context)
            scores = _validate_scores(raw_choice.get("scores"), choice_context)
            choices.append(Choice(choice_id, choice_text, scores))

        questions.append(Question(question_id, question_text, tuple(choices)))

    return QuestionSet(SCHEMA_VERSION, diagnosis_version, tuple(questions))


class ValorantPlaystyleRepository:
    """Load and validate versioned playstyle question master data."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> QuestionSet:
        return validate_question_data(load_json(self._path))
