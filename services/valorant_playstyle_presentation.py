"""Presentation values for VALORANT playstyle diagnosis results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repositories.valorant_playstyle_repository import QuestionSet
from services.valorant_playstyle_service import (
    PlaystyleCategory,
    PlaystyleClassification,
)

CATEGORY_PRESENTATION = {
    PlaystyleCategory.GACHI: (
        "🔥 ガチ",
        "チームで相談しながら試合を組み立て、\n"
        "うまくいかなかったところを改善しながら\n"
        "勝利を目指すプレイスタイルです。\n"
        "必要な場面ではしっかり集中し、\n"
        "チームゲームとしてVALORANTを楽しむ傾向があります。",
    ),
    PlaystyleCategory.NEUTRAL: (
        "⚖️ 中立",
        "勝ちを目指すことと、\n"
        "楽しく遊ぶことの両方を大切にするプレイスタイルです。\n"
        "メンバーや状況に合わせながら、\n"
        "チームとして遊ぶことを大切にする傾向があります。",
    ),
    PlaystyleCategory.ENJOY: (
        "🥳 エンジョイ",
        "勝敗や細かな振り返りより、\n"
        "みんなで楽しく遊べることを大切にするプレイスタイルです。\n"
        "チームゲームには参加しつつ、\n"
        "雰囲気や自由度を重視する傾向があります。",
    ),
}

AXIS_LABELS = {
    "win": "🏆 勝利志向",
    "team": "🤝 チーム志向",
    "improvement": "🔧 改善志向",
    "focus": "🎯 集中志向",
}

FEEDBACK_RECEIVE = {
    3: "積極的に提案やアドバイスを受けたい",
    2: "理由が分かれば提案を取り入れやすい",
    1: "必要な場面で軽く提案されるくらいが合いやすい",
    0: "基本的には自分で考えてプレイすることを好む",
}
FEEDBACK_GIVE = {
    3: "必要だと思ったことは、その場で簡潔に伝える",
    2: "状況に合わせて、相談や振り返りの形で伝える",
    1: "必要な場面に絞って伝える",
    0: "基本的には相手のプレイ判断を尊重する",
}


def percentage(normalized: float) -> int:
    return round(min(1.0, max(0.0, normalized)) * 100)


def progress_bar(normalized: float) -> str:
    filled = round(min(1.0, max(0.0, normalized)) * 10)
    return "█" * filled + "░" * (10 - filled)


def feedback_lines(receive_score: int, give_score: int) -> tuple[str, str]:
    return FEEDBACK_RECEIVE[receive_score], FEEDBACK_GIVE[give_score]


def _result_description(
    *,
    category: PlaystyleCategory,
    normalized_axes: Mapping[str, float],
    feedback_receive: int,
    feedback_give: int,
    weighted_score: float | None,
) -> str:
    title, category_text = CATEGORY_PRESENTATION[category]
    sections = [title, "", category_text, ""]
    if weighted_score is not None:
        sections.extend([f"総合スコア：{percentage(weighted_score)}%", ""])
    sections.extend(["━━━━━━━━━━━━━━", ""])
    for axis in ("win", "team", "improvement", "focus"):
        normalized = normalized_axes[axis]
        sections.extend(
            [AXIS_LABELS[axis], f"{progress_bar(normalized)} {percentage(normalized)}%", ""]
        )
    receive, give = feedback_lines(feedback_receive, feedback_give)
    sections.extend(
        [
            "━━━━━━━━━━━━━━",
            "",
            "💬 フィードバック傾向",
            f"・{receive}",
            f"・{give}",
            "",
            "※この診断は実力やランクを評価するものではありません。",
        ]
    )
    return "\n".join(sections)


def classification_result_description(
    classification: PlaystyleClassification,
    *,
    include_weighted_score: bool = False,
) -> str:
    """Render the shared result body used by DMs and audit logs."""

    axes = classification.score.axes
    return _result_description(
        category=classification.category,
        normalized_axes={axis: value.normalized for axis, value in axes.items()},
        feedback_receive=axes["feedback_receive"].score,
        feedback_give=axes["feedback_give"].score,
        weighted_score=(classification.weighted_score if include_weighted_score else None),
    )


def stored_result_description(
    result: Mapping[str, Any],
    *,
    include_weighted_score: bool = True,
) -> str:
    """Render the latest persisted category and axis summary."""

    axes = result["axes"]
    return _result_description(
        category=PlaystyleCategory(result["category"]),
        normalized_axes={axis: value["normalized"] for axis, value in axes.items()},
        feedback_receive=axes["feedback_receive"]["score"],
        feedback_give=axes["feedback_give"]["score"],
        weighted_score=(result["weighted_score"] if include_weighted_score else None),
    )


def answer_log_pages(
    question_set: QuestionSet,
    answers: Mapping[str, str],
    *,
    questions_per_page: int = 5,
) -> tuple[str, ...]:
    """Restore saved choice IDs into bounded human-readable answer pages."""

    if questions_per_page <= 0:
        raise ValueError("questions_per_page must be positive")
    blocks: list[str] = []
    for index, question in enumerate(question_set.questions, start=1):
        choice_id = answers.get(question.id)
        choice = next(
            (candidate for candidate in question.choices if candidate.id == choice_id),
            None,
        )
        if choice is None:
            raise ValueError(f"cannot restore saved answer for {question.id}")
        blocks.append(f"**Q{index}**\n{question.text}\n\n**回答**\n{choice.text}")

    pages = tuple(
        "\n\n━━━━━━━━━━━━━━\n\n".join(
            blocks[start : start + questions_per_page]
        )
        for start in range(0, len(blocks), questions_per_page)
    )
    if any(len(page) > 4096 for page in pages):
        raise ValueError("answer log page exceeds Discord embed description limit")
    return pages
