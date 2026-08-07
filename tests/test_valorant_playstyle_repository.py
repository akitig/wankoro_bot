import copy
import json
from pathlib import Path

import pytest

from repositories.valorant_playstyle_repository import (
    SUPPORTED_AXIS_SET,
    QuestionValidationError,
    ValorantPlaystyleRepository,
    validate_question_data,
)

QUESTION_PATH = Path(__file__).parents[1] / "data" / "valorant_playstyle_questions.json"


def _valid_data() -> dict:
    return {
        "schema_version": 1,
        "diagnosis_version": "test",
        "questions": [
            {
                "id": "q01",
                "question": "Question",
                "choices": [
                    {"id": "a", "text": "A", "scores": {"win": 0}},
                    {"id": "b", "text": "B", "scores": {"win": 3}},
                ],
            }
        ],
    }


def test_question_master_contains_expected_ordered_questions_and_choices() -> None:
    question_set = ValorantPlaystyleRepository(QUESTION_PATH).load()

    assert question_set.schema_version == 1
    assert question_set.diagnosis_version == "2.0"
    assert [question.id for question in question_set.questions] == [
        f"q{index:02d}" for index in range(1, 16)
    ]
    assert len({question.id for question in question_set.questions}) == 15
    for question in question_set.questions:
        assert len(question.choices) == 4
        assert [choice.id for choice in question.choices] == ["a", "b", "c", "d"]
        assert len({choice.id for choice in question.choices}) == 4
        for choice in question.choices:
            assert set(choice.scores) <= SUPPORTED_AXIS_SET


def test_repository_loads_utf8_json_and_validates_it(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    data = _valid_data()
    data["questions"][0]["question"] = "日本語の質問"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = ValorantPlaystyleRepository(path).load()

    assert loaded.questions[0].text == "日本語の質問"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version=2), "schema_version"),
        (lambda data: data.update(diagnosis_version=""), "diagnosis_version"),
        (lambda data: data.update(questions=[]), "questions"),
        (
            lambda data: data["questions"][0].update(id=""),
            "id must be a non-empty string",
        ),
        (
            lambda data: data["questions"].append(copy.deepcopy(data["questions"][0])),
            "duplicate question id",
        ),
        (
            lambda data: data["questions"][0].update(question=""),
            "question must be a non-empty string",
        ),
        (
            lambda data: data["questions"][0].update(choices=[]),
            "choices must be a non-empty array",
        ),
        (
            lambda data: data["questions"][0]["choices"][0].update(id=""),
            "id must be a non-empty string",
        ),
        (
            lambda data: data["questions"][0]["choices"].append(
                copy.deepcopy(data["questions"][0]["choices"][0])
            ),
            "duplicate choice id",
        ),
        (
            lambda data: data["questions"][0]["choices"][0].update(text=""),
            "text must be a non-empty string",
        ),
        (
            lambda data: data["questions"][0]["choices"][0].update(
                scores={"unknown": 1}
            ),
            "unknown axis",
        ),
        (
            lambda data: data["questions"][0]["choices"][0].update(
                scores={"win": -1}
            ),
            "between 0 and 3",
        ),
        (
            lambda data: data["questions"][0]["choices"][0].update(
                scores={"win": 4}
            ),
            "between 0 and 3",
        ),
        (
            lambda data: data["questions"][0]["choices"][0].update(
                scores={"win": 1.5}
            ),
            "must be an integer",
        ),
        (
            lambda data: data["questions"][0]["choices"][0].update(
                scores={"win": True}
            ),
            "must be an integer",
        ),
    ],
)
def test_invalid_question_data_is_rejected(mutation, message: str) -> None:
    data = _valid_data()
    mutation(data)

    with pytest.raises(QuestionValidationError, match=message):
        validate_question_data(data)


def test_empty_choice_scores_are_rejected() -> None:
    data = _valid_data()
    data["questions"][0]["choices"][0]["scores"] = {}

    with pytest.raises(QuestionValidationError, match="scores must be a non-empty object"):
        validate_question_data(data)
