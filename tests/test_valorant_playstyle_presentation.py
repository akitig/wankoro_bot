from pathlib import Path

import pytest

from repositories.valorant_playstyle_repository import ValorantPlaystyleRepository
from services.valorant_playstyle_presentation import (
    CATEGORY_PRESENTATION,
    answer_log_pages,
    classification_result_description,
    feedback_lines,
    percentage,
    progress_bar,
)
from services.valorant_playstyle_service import PlaystyleCategory, ValorantPlaystyleService

QUESTION_PATH = Path(__file__).parents[1] / "data" / "valorant_playstyle_questions.json"


def test_all_categories_have_expected_labels() -> None:
    assert set(CATEGORY_PRESENTATION) == set(PlaystyleCategory)
    assert CATEGORY_PRESENTATION[PlaystyleCategory.ENJOY][0] == "🥳 エンジョイ"
    assert CATEGORY_PRESENTATION[PlaystyleCategory.NEUTRAL][0] == "⚖️ 中立"
    assert CATEGORY_PRESENTATION[PlaystyleCategory.GACHI][0] == "🔥 ガチ"


@pytest.mark.parametrize(
    ("normalized", "expected_percentage", "expected_bar"),
    [
        (-1.0, 0, "░░░░░░░░░░"),
        (0.0, 0, "░░░░░░░░░░"),
        (0.78, 78, "████████░░"),
        (0.87, 87, "█████████░"),
        (1.0, 100, "██████████"),
        (2.0, 100, "██████████"),
    ],
)
def test_percentage_and_progress_bar_are_clamped(
    normalized: float, expected_percentage: int, expected_bar: str
) -> None:
    assert percentage(normalized) == expected_percentage
    assert progress_bar(normalized) == expected_bar
    assert len(progress_bar(normalized)) == 10


@pytest.mark.parametrize(
    ("receive", "give", "expected_receive", "expected_give"),
    [
        (
            3,
            3,
            "積極的に提案やアドバイスを受けたい",
            "必要だと思ったことは、その場で簡潔に伝える",
        ),
        (
            2,
            2,
            "理由が分かれば提案を取り入れやすい",
            "状況に合わせて、相談や振り返りの形で伝える",
        ),
        (
            1,
            1,
            "必要な場面で軽く提案されるくらいが合いやすい",
            "必要な場面に絞って伝える",
        ),
        (
            0,
            0,
            "基本的には自分で考えてプレイすることを好む",
            "基本的には相手のプレイ判断を尊重する",
        ),
    ],
)
def test_feedback_copy_matches_raw_scores(
    receive: int,
    give: int,
    expected_receive: str,
    expected_give: str,
) -> None:
    assert feedback_lines(receive, give) == (expected_receive, expected_give)


def test_shared_result_description_adds_weighted_score_only_when_requested() -> None:
    service = ValorantPlaystyleService(questions_path=QUESTION_PATH)
    answers = {
        question.id: max(
            question.choices,
            key=lambda choice: sum(choice.scores.values()),
        ).id
        for question in service.question_set.questions
    }
    classification = service.classify_complete(answers)

    dm = classification_result_description(classification)
    audit = classification_result_description(
        classification, include_weighted_score=True
    )

    assert "総合スコア" not in dm
    assert "総合スコア：100%" in audit
    assert dm in audit.replace("総合スコア：100%\n\n", "")


def test_answer_log_pages_restore_choice_ids_in_question_order() -> None:
    question_set = ValorantPlaystyleRepository(QUESTION_PATH).load()
    answers = {question.id: "c" for question in question_set.questions}

    pages = answer_log_pages(question_set, answers)
    rendered = "\n".join(pages)

    assert len(pages) == 3
    assert all(len(page) <= 4096 for page in pages)
    assert rendered.index("**Q1**") < rendered.index("**Q15**")
    for question in question_set.questions:
        selected = next(choice for choice in question.choices if choice.id == "c")
        assert question.text in rendered
        assert selected.text in rendered
    assert "+3" not in rendered
    assert "team +" not in rendered


def test_answer_log_pages_reject_unknown_saved_choice() -> None:
    question_set = ValorantPlaystyleRepository(QUESTION_PATH).load()
    answers = {question.id: "c" for question in question_set.questions}
    answers["q01"] = "unknown"

    with pytest.raises(ValueError, match="q01"):
        answer_log_pages(question_set, answers)
