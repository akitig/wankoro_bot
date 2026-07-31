"""Business logic for the VALORANT role diagnostic."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord

from repositories.valocheck_repository import ValocheckRepository

logger = logging.getLogger(__name__)

DEFAULT_INTRO_TITLE = "VALORANT ロール診断（Gachi/Enjoy）"
DEFAULT_INTRO_TEXT = (
    "この診断は、コンペにおけるプレイスタイルのズレを減らすためのものです。\n\n"
    "・Gachi：勝利のためにチームワーク/改善/戦略に寄せる\n"
    "・Enjoy：勝敗よりも雰囲気や気軽さを重視する\n\n"
    "※どちらでもコール/報告は前提です。\n"
    "※マップ名称が分からない等の初心者要素は、改善しつつ大目に見てください。\n\n"
    "準備ができたら「開始」を押してね。"
)
DEFAULT_QUESTIONS = [
    {
        "q": "Q1. 今日のコンペの目的に一番近いのは？",
        "choices": [
            ("ランクを上げたい。勝つために合わせたい", 3),
            ("勝ちたいけど、雰囲気も大事。両立したい", 2),
            ("できれば勝ちたいけど、気楽にやりたい", 1),
            ("勝敗は二の次。みんなで遊べればOK", 0),
        ],
    }
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_intro(data: Any) -> tuple[str, str] | None:
    if not isinstance(data, dict):
        return None
    title = data.get("title")
    text = data.get("text")
    if not isinstance(title, str) or not isinstance(text, str):
        return None
    return title, text


def _normalize_questions(qs: Any) -> list[dict[str, Any]] | None:
    if not isinstance(qs, list) or len(qs) == 0:
        return None
    out = []
    for item in qs:
        if not isinstance(item, dict):
            continue
        question = item.get("q")
        raw_choices = item.get("choices")
        if (
            not isinstance(question, str)
            or not isinstance(raw_choices, list)
            or len(raw_choices) < 2
        ):
            continue
        choices = []
        for choice in raw_choices:
            if (
                isinstance(choice, list)
                and len(choice) == 2
                and isinstance(choice[0], str)
                and isinstance(choice[1], int)
            ):
                choices.append((choice[0], choice[1]))
        if len(choices) >= 2:
            out.append({"q": question, "choices": choices})
    return out or None


def _calc_max_score(questions: list[dict[str, Any]]) -> int:
    return sum(max(score for _, score in question["choices"]) for question in questions)


class ValocheckService:
    """Own diagnostic state, decisions, persistence, and Discord operations."""

    def __init__(
        self,
        bot: Any,
        *,
        guild_id: int,
        role_enjoy_id: int,
        role_gachi_id: int,
        log_channel_id: int | None,
        admin_dm_user_id: int | None,
        view_timeout_sec: int,
        thresh_enjoy_only: int,
        thresh_gachi_only: int,
        label_enjoy: str,
        label_gachi: str,
        label_both: str,
        completion_path: Path,
        questions_path: Path,
        intro_path: Path,
        start_view_factory: Callable[[int, int], Any],
        quiz_view_factory: Callable[[int, int], Any],
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.role_enjoy_id = role_enjoy_id
        self.role_gachi_id = role_gachi_id
        self.log_channel_id = log_channel_id
        self.admin_dm_user_id = admin_dm_user_id
        self.view_timeout_sec = view_timeout_sec
        self.thresh_enjoy_only = thresh_enjoy_only
        self.thresh_gachi_only = thresh_gachi_only
        self.label_enjoy = label_enjoy
        self.label_gachi = label_gachi
        self.label_both = label_both
        self._start_view_factory = start_view_factory
        self._quiz_view_factory = quiz_view_factory
        self._repository = ValocheckRepository(
            completion_path=completion_path,
            questions_path=questions_path,
            intro_path=intro_path,
        )

        intro = _normalize_intro(self._repository.load_intro())
        if intro is None:
            self.intro_title = DEFAULT_INTRO_TITLE
            self.intro_text = DEFAULT_INTRO_TEXT
        else:
            self.intro_title, self.intro_text = intro

        self.questions: list[dict[str, Any]] = []
        self.max_score = 0
        self.reload_questions(use_default=True)
        self.sessions: dict[int, dict[str, Any]] = {}
        self._repository.load()

    def reload_questions(self, *, use_default: bool = False) -> bool:
        normalized = _normalize_questions(self._repository.load_questions())
        if normalized is None and use_default:
            self.questions = DEFAULT_QUESTIONS
        elif normalized is None:
            return False
        else:
            self.questions = normalized
        self.max_score = _calc_max_score(self.questions)
        return True

    def calculate_roles(self, score: int) -> tuple[bool, bool, str]:
        if score >= self.thresh_gachi_only:
            return True, False, self.label_gachi
        if score <= self.thresh_enjoy_only:
            return False, True, self.label_enjoy
        return True, True, self.label_both

    def _shuffle_questions(self) -> list[dict[str, Any]]:
        questions = []
        for question in self.questions:
            choices = list(question["choices"])
            random.shuffle(choices)
            questions.append({"q": question["q"], "choices": choices})
        return questions

    async def diagnose(
        self,
        member: Any,
        *,
        invoked_by: Any,
        force: bool = False,
    ) -> str:
        if member.bot:
            return "Botは対象にできません。"
        if self._repository.has_completion(member.id) and not force:
            return "このメンバーは既に診断済みです。"
        if member.id in self.sessions:
            return "このメンバーは現在診断中です。"
        if not self.questions:
            await self.notify_admin(
                "❌ VALO診断: 質問0件",
                f"InvokedBy: {invoked_by} / Target: {member} ({member.id})",
            )
            return "質問が読み込めていません。運営に連絡してね。"

        self.sessions[member.id] = {
            "idx": -1,
            "score": 0,
            "answers": [],
            "questions": self._shuffle_questions(),
            "invoked_by": invoked_by.id,
            "invoked_by_name": str(invoked_by),
            "forced": force,
            "force_enjoy": False,
        }
        try:
            await self._send_intro(member)
        except discord.Forbidden:
            logger.exception("Diagnostic direct message was forbidden")
            self.sessions.pop(member.id, None)
            await self.notify_admin(
                "❌ VALO診断: DM送信Forbidden",
                f"InvokedBy: {invoked_by}\nTarget: {member} ({member.id})",
            )
            return "DMを送れませんでした。相手がサーバーDMを拒否しています。"
        except Exception:
            logger.exception("Failed to send diagnostic direct message")
            self.sessions.pop(member.id, None)
            await self.notify_admin(
                "❌ VALO診断: DM送信で例外",
                f"InvokedBy: {invoked_by}\nTarget: {member} ({member.id})",
            )
            return "DM送信に失敗しました。管理者に連絡してね。"
        return f"{member.mention} にDMで診断を送りました。"

    async def _send_intro(self, user: Any) -> None:
        embed = discord.Embed(
            title=self.intro_title,
            description=self.intro_text,
            color=0xF4A261,
        )
        if self.bot.user and self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.set_footer(text="灯麗会 Discord サーバー｜VALORANT ロール診断 🐶")
        view = self._start_view_factory(user.id, self.view_timeout_sec)
        self.sessions[user.id]["dm_message"] = await user.send(embed=embed, view=view)

    async def start_questions(self, user: Any) -> None:
        session = self.sessions.get(user.id)
        if not session:
            await self.notify_admin(
                "⚠️ VALO診断: start_questionsでセッション無し",
                f"Target: <@{user.id}> (`{user.id}`)\nOrigin: `start_questions`",
            )
            return
        session["idx"] = 0
        await self._send_question(user, 0)

    async def _send_question(self, user: Any, idx: int) -> None:
        session = self.sessions.get(user.id)
        if not session:
            await self.notify_admin(
                "⚠️ VALO診断: _send_questionでセッション無し",
                f"Target: <@{user.id}> (`{user.id}`)\nidx={idx}",
            )
            return
        session_questions = session.get("questions")
        if not isinstance(session_questions, list) or not session_questions:
            await self.notify_admin_session(
                "⚠️ VALO診断: セッション質問が無い",
                user.id,
                session,
                origin="_send_question",
            )
            return
        if idx < 0 or idx >= len(session_questions):
            await self.notify_admin_session(
                "⚠️ VALO診断: idx範囲外",
                user.id,
                session,
                origin=f"_send_question idx={idx}",
            )
            return
        view = self._quiz_view_factory(user.id, self.view_timeout_sec)
        view.set_buttons(session_questions[idx]["choices"])
        embed = discord.Embed(
            title=f"VALORANT ロール診断（{idx + 1}/{len(session_questions)}）",
            description=session_questions[idx]["q"],
            color=0xF4A261,
        )
        embed.set_footer(text="回答すると次の問題に進みます。")
        await session["dm_message"].edit(embed=embed, view=view)

    async def answer(self, user: Any, add_score: int, choice_label: str) -> str | None:
        session = self.sessions.get(user.id)
        if not session:
            await self.notify_admin(
                "⚠️ VALO診断: on_answerでセッション無し",
                f"Target: <@{user.id}> (`{user.id}`)\n"
                f"Choice: {choice_label} ({add_score}点)",
            )
            return "セッションが見つかりません。管理者に連絡してね。"

        questions = session.get("questions", [])
        question_count = len(questions) if isinstance(questions, list) else 0
        current_idx = max(0, int(session.get("idx", 0)))
        last_two = (
            {question_count - 2, question_count - 1}
            if question_count >= 2
            else set()
        )
        if current_idx in last_two and int(add_score) == 0:
            session["force_enjoy"] = True
        session["score"] = int(session.get("score", 0)) + int(add_score)
        session.setdefault("answers", []).append(
            {"choice": choice_label, "score": int(add_score)}
        )
        session["idx"] = current_idx + 1

        if session["idx"] >= question_count:
            await self._finalize(user, session)
            self.sessions.pop(user.id, None)
        else:
            await self._send_question(user, session["idx"])
        return None

    async def _finalize(self, user: Any, session: dict[str, Any]) -> None:
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(self.guild_id)
            except Exception:
                logger.exception("Failed to resolve diagnostic guild")
        if guild is None:
            await self.notify_admin_session(
                "❌ VALO診断: guild取得失敗", user.id, session, origin="_finalize"
            )
            return
        try:
            member = guild.get_member(user.id) or await guild.fetch_member(user.id)
        except Exception:
            logger.exception("Failed to resolve diagnostic member")
            await self.notify_admin_session(
                "❌ VALO診断: member取得失敗", user.id, session, origin="_finalize"
            )
            return

        role_enjoy = guild.get_role(self.role_enjoy_id)
        role_gachi = guild.get_role(self.role_gachi_id)
        if role_enjoy is None or role_gachi is None:
            await self.notify_admin_session(
                "❌ VALO診断: ロールID不正", user.id, session, origin="_finalize"
            )
            try:
                await user.send("ロールID設定が正しくないみたい。運営に連絡してね。")
            except Exception:
                logger.exception("Failed to notify user about role configuration")
            return

        score = int(session.get("score", 0))
        if session.get("force_enjoy"):
            is_gachi, is_enjoy, label = False, True, self.label_enjoy
        else:
            is_gachi, is_enjoy, label = self.calculate_roles(score)
        remove_roles = [
            role
            for role in (role_enjoy, role_gachi)
            if role in member.roles
        ]
        add_roles = [
            role
            for enabled, role in ((is_enjoy, role_enjoy), (is_gachi, role_gachi))
            if enabled
        ]
        try:
            if remove_roles:
                await member.remove_roles(
                    *remove_roles, reason="VALO role check reset"
                )
            if add_roles:
                await member.add_roles(*add_roles, reason="VALO role check result")
        except discord.Forbidden:
            logger.exception("Insufficient permission to update diagnostic roles")
            await self.notify_admin_session(
                "❌ VALO診断: ロール付与権限不足",
                user.id,
                session,
                origin="_finalize",
            )
            try:
                await user.send(
                    "ロール付与に失敗しました（権限不足）。Botの権限/ロール位置を確認してね。"
                )
            except Exception:
                logger.exception("Failed to notify user about role permission error")
            return
        except Exception:
            logger.exception("Failed to update diagnostic roles")
            await self.notify_admin_session(
                "❌ VALO診断: ロール付与で例外",
                user.id,
                session,
                origin="_finalize",
            )
            try:
                await user.send("ロール付与に失敗しました。管理者に連絡してね。")
            except Exception:
                logger.exception("Failed to notify user about role update error")
            return

        await self._deliver_result(user, session, score, label)
        completion = {
            "completed_at": _utc_now(),
            "score": score,
            "max_score": self.max_score,
            "result": label,
            "answers": session.get("answers", []),
            "invoked_by": session.get("invoked_by"),
            "invoked_by_name": session.get("invoked_by_name"),
            "forced": bool(session.get("forced")),
            "force_enjoy": bool(session.get("force_enjoy")),
        }
        self._repository.save_completion(member.id, completion)
        await self._log_to_channel(guild, member, score, label, session)

    async def _deliver_result(
        self, user: Any, session: dict[str, Any], score: int, label: str
    ) -> None:
        embed = discord.Embed(
            title="VALORANT ロール診断 完了 🐶",
            description=f"✅ 判定：**{label}**\nスコア：**{score}/{self.max_score}**",
            color=0xF4A261,
        )
        message = session.get("dm_message")
        if isinstance(message, discord.Message):
            try:
                await message.edit(embed=embed, view=None)
                return
            except Exception:
                logger.debug(
                    "Failed to edit diagnostic result message; trying direct message",
                    exc_info=True,
                )
        try:
            await user.send(embed=embed)
        except Exception:
            logger.exception("Failed to deliver diagnostic result")

    async def expire_session(
        self, user_id: int, origin: str = "expire_session"
    ) -> None:
        session = self.sessions.pop(user_id, None)
        if not isinstance(session, dict):
            return
        embed = discord.Embed(
            title="VALORANT ロール診断",
            description=(
                "⏰ 一定時間操作がなかったため **期限切れ** になりました。\n"
                "もう一度受けたい場合は、管理者に診断を送ってもらってください。"
            ),
            color=0xE76F51,
        )
        message = session.get("dm_message")
        try:
            if isinstance(message, discord.Message):
                await message.edit(embed=embed, view=None)
        except Exception:
            logger.exception("Failed to update expired diagnostic message")
        await self.notify_admin_session(
            "⏰ VALO診断: セッション期限切れ", user_id, session, origin
        )

    async def cancel_session(
        self, user_id: int, reason: str, invoker: Any
    ) -> bool:
        session = self.sessions.pop(user_id, None)
        if not session:
            return False
        message = session.get("dm_message")
        if isinstance(message, discord.Message):
            embed = discord.Embed(
                title="VALORANT ロール診断 中断",
                description=(
                    "この診断は管理者によって中断されました。\n"
                    "判定・ロール付与は行われません。\n\n"
                    f"理由: {reason}"
                ),
                color=0xE76F51,
            )
            try:
                await message.edit(embed=embed, view=None)
            except Exception:
                logger.exception("Failed to update cancelled diagnostic message")
        await self.notify_admin_session(
            "🛑 VALO診断: 管理者中断",
            user_id,
            session,
            origin=f"cancel reason={reason}",
        )
        return True

    async def reload(self, invoker: Any) -> str:
        if self.sessions:
            return "現在診断中のユーザーがいるため、リロードできません。"
        if not self.reload_questions(use_default=False):
            await self.notify_admin(
                "❌ VALO診断: 質問再読み込み失敗",
                f"InvokedBy: {invoker}",
            )
            return "質問の再読み込みに失敗しました。JSON形式/パスを確認してね。"
        return (
            f"質問を再読み込みしました。質問数={len(self.questions)} "
            f"/ max_score={self.max_score}"
        )

    async def cancel(self, member: Any, reason: str, invoker: Any) -> str:
        if not await self.cancel_session(member.id, reason, invoker):
            return "このメンバーは現在診断中ではありません。"
        return f"{member.mention} の診断を中断しました（判定なし）。"

    async def cancel_all(self, reason: str, invoker: Any) -> str:
        user_ids = list(self.sessions)
        if not user_ids:
            return "診断中のユーザーはいません。"
        count = 0
        for user_id in user_ids:
            if await self.cancel_session(user_id, reason, invoker):
                count += 1
        return f"診断中セッションを {count} 件中断しました（判定なし）。"

    async def notify_admin(self, title: str, body: str) -> None:
        if not self.admin_dm_user_id:
            return
        admin = self.bot.get_user(self.admin_dm_user_id)
        if admin is None:
            try:
                admin = await self.bot.fetch_user(self.admin_dm_user_id)
            except Exception:
                logger.exception("Failed to resolve diagnostic administrator")
                return
        try:
            await admin.send(f"**{title}**\n{body}")
        except Exception:
            logger.exception("Failed to send diagnostic administrator notice")

    async def notify_admin_session(
        self, title: str, user_id: int, session: dict[str, Any], origin: str
    ) -> None:
        answers = session.get("answers", [])
        summary = self._build_summary_line(answers)
        recent = self._build_recent_answers(answers)
        body = (
            f"Origin: `{origin}`\n"
            f"Target: <@{user_id}> (`{user_id}`)\n"
            f"InvokedBy: **{session.get('invoked_by_name', 'unknown')}**"
        )
        invoked_by_id = session.get("invoked_by")
        if invoked_by_id is not None:
            body += f" (`{invoked_by_id}`)"
        body += (
            "\n"
            f"Session: idx={int(session.get('idx', -1))} "
            f"score={int(session.get('score', 0))}/{self.max_score}\n"
            f"Summary: {summary}\nRecent:\n{recent}\n"
        )
        await self.notify_admin(title, body)

    @staticmethod
    def _build_summary_line(answers: Any) -> str:
        parts = []
        for index, answer in enumerate(answers or []):
            score = int(answer.get("score", 0)) if isinstance(answer, dict) else 0
            parts.append(f"Q{index + 1}={score}点")
        return " / ".join(parts) if parts else "(no answers)"

    @staticmethod
    def _build_recent_answers(answers: Any, count: int = 3) -> str:
        if not isinstance(answers, list) or not answers:
            return "(no answers)"
        lines = []
        start = max(0, len(answers) - count)
        for index in range(start, len(answers)):
            answer = answers[index]
            if isinstance(answer, dict):
                lines.append(
                    f"Q{index + 1}={int(answer.get('score', 0))}点: "
                    f"{str(answer.get('choice', ''))}"
                )
        return "\n".join(lines) if lines else "(no answers)"

    async def _get_log_channel(self, guild: Any) -> Any:
        if not self.log_channel_id:
            return None
        channel = guild.get_channel(self.log_channel_id)
        if channel is not None:
            return channel
        try:
            return await guild.fetch_channel(self.log_channel_id)
        except Exception:
            logger.exception("Failed to resolve diagnostic log channel")
            return None

    async def _log_to_channel(
        self,
        guild: Any,
        member: Any,
        score: int,
        label: str,
        session: dict[str, Any],
    ) -> None:
        channel = await self._get_log_channel(guild)
        if channel is None:
            return
        answers = session.get("answers", [])
        embed = discord.Embed(
            title="VALO ロール診断ログ",
            description=(
                f"対象: {member.mention}\n"
                f"🧾 {self._build_summary_line(answers)}\n"
                f"結果: **{label}**\n"
                f"スコア: **{score}/{self.max_score}**\n"
                f"管理者: **{session.get('invoked_by_name', 'unknown')}**\n"
                f"force: **{'YES' if session.get('forced') else 'NO'}**\n"
                "force_enjoy(last2=0): "
                f"**{'YES' if session.get('force_enjoy') else 'NO'}**"
            ),
            color=0x264653,
        )
        session_questions = session.get("questions", [])
        for index, answer in enumerate(answers):
            question = f"Q{index + 1}"
            if isinstance(session_questions, list) and index < len(session_questions):
                question = session_questions[index].get("q", question)
            if isinstance(answer, dict):
                value = (
                    f"{answer.get('choice', '')}\n"
                    f"**{int(answer.get('score', 0))}点**"
                )
            else:
                value = str(answer)
            embed.add_field(name=question, value=value, inline=False)
        try:
            await channel.send(embed=embed)
        except Exception:
            logger.exception("Failed to send diagnostic audit event")
