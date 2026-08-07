import pytest

from services.valorant_playstyle_presentation import (
    CATEGORY_PRESENTATION,
    feedback_lines,
    percentage,
    progress_bar,
)
from services.valorant_playstyle_service import PlaystyleCategory


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
