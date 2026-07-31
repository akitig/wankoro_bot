import pytest

from services.valocheck_service import (
    DEFAULT_QUESTIONS,
    ValocheckService,
    _calc_max_score,
    _normalize_intro,
    _normalize_questions,
)


def _role_service() -> ValocheckService:
    service = ValocheckService.__new__(ValocheckService)
    service.thresh_enjoy_only = 6
    service.thresh_gachi_only = 12
    service.label_enjoy = "ENJOY設定"
    service.label_gachi = "GACHI設定"
    service.label_both = "両方設定"
    return service


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
    assert _role_service().calculate_roles(score) == expected


def test_every_score_range_assigns_at_least_one_role() -> None:
    service = _role_service()

    for score in range(-10, 31):
        is_gachi, is_enjoy, _ = service.calculate_roles(score)
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


def test_missing_question_file_uses_built_in_default() -> None:
    class RepositoryStub:
        def load_questions(self) -> None:
            return None

    service = ValocheckService.__new__(ValocheckService)
    service._repository = RepositoryStub()
    service.questions = []
    service.max_score = 0

    assert service.reload_questions(use_default=True) is True
    assert service.questions is DEFAULT_QUESTIONS
    assert service.max_score == _calc_max_score(DEFAULT_QUESTIONS)


def test_intro_raw_data_validation_preserves_fallback_boundary() -> None:
    assert _normalize_intro({"title": "題", "text": "本文"}) == (
        "題",
        "本文",
    )
    assert _normalize_intro(None) is None
    assert _normalize_intro({"title": "題"}) is None
