"""Presentation values for VALORANT playstyle diagnosis results."""

from __future__ import annotations

from services.valorant_playstyle_service import PlaystyleCategory

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
