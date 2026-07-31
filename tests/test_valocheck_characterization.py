from pathlib import Path

import pytest

from cogs.valocheck import (
    DEFAULT_QUESTIONS,
    ValoCheckCog,
    _calc_max_score,
    _normalize_questions,
)


def _role_cog() -> ValoCheckCog:
    cog = ValoCheckCog.__new__(ValoCheckCog)
    cog.thresh_enjoy_only = 6
    cog.thresh_gachi_only = 12
    cog.label_enjoy = "ENJOY設定"
    cog.label_gachi = "GACHI設定"
    cog.label_both = "両方設定"
    return cog


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, (False, True, "ENJOY設定")),
        (6, (False, True, "ENJOY設定")),
        (7, (True, True, "両方設定")),
        (11, (True, True, "両方設定")),
        (12, (True, False, "GACHI設定")),
        (18, (True, False, "GACHI設定")),
    ],
)
def test_role_decision_boundaries_and_labels(
    score: int, expected: tuple[bool, bool, str]
) -> None:
    assert _role_cog()._calc_roles(score) == expected


def test_every_score_range_assigns_at_least_one_role() -> None:
    cog = _role_cog()

    for score in range(-10, 31):
        is_gachi, is_enjoy, _ = cog._calc_roles(score)
        assert is_gachi or is_enjoy


def test_invalid_question_structure_has_no_match() -> None:
    assert _normalize_questions([]) is None
    assert _normalize_questions([{"q": "missing choices"}]) is None
    assert _normalize_questions([{"q": "Q", "choices": [["A", "not-int"]]}]) is None


def test_question_scores_are_normalized_and_maximum_is_calculated() -> None:
    normalized = _normalize_questions(
        [{"q": " Q ", "choices": [["A", 1], ["B", 3]]}]
    )

    assert normalized == [{"q": " Q ", "choices": [("A", 1), ("B", 3)]}]
    assert _calc_max_score(normalized) == 3


def test_missing_question_file_uses_built_in_default(tmp_path: Path) -> None:
    cog = ValoCheckCog.__new__(ValoCheckCog)
    cog.questions_path = tmp_path / "missing-questions.json"
    cog.questions = []
    cog.max_score = 0

    assert cog._reload_questions(use_default=True) is True
    assert cog.questions is DEFAULT_QUESTIONS
    assert cog.max_score == _calc_max_score(DEFAULT_QUESTIONS)
