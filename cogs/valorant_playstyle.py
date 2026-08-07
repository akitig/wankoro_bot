"""Discord flow for the VALORANT playstyle diagnosis."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from repositories.valorant_playstyle_result_repository import (
    ValorantPlaystyleResultRepository,
)
from services.valorant_playstyle_presentation import (
    AXIS_LABELS,
    CATEGORY_PRESENTATION,
    feedback_lines,
    percentage,
    progress_bar,
)
from services.valorant_playstyle_result_service import (
    ValorantPlaystyleResultService,
)
from services.valorant_playstyle_service import (
    ClassificationPolicy,
    PlaystyleClassification,
    ValorantPlaystyleService,
)

logger = logging.getLogger(__name__)
QUESTION_PATH = Path("data/valorant_playstyle_questions.json")
NUMBER_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")

INTRO_TEXT = """この診断は、VALORANTの「上手い・下手」を決めるものではありません！

普段どんなふうにコンペを遊びたいかを確認して、
灯麗会で一緒に遊ぶ人とのミスマッチを減らすための診断です。

灯麗会では、エンジョイ・ガチに関係なく、

・故意に試合を投げない
・試合に必要なコミュニケーションを取る
・必要な場面では試合を優先する

ことを前提としています。

「できるか」ではなく、
普段どう遊びたいかで答えてください！

全15問です。"""


@dataclass
class DiagnosisSession:
    user: Any
    administrator_id: int
    administrator_name: str
    answers: dict[str, str] = field(default_factory=dict)
    question_index: int = -1
    dm_message: Any = None
    last_activity: float = field(default_factory=time.monotonic)
    timeout_generation: int = 0
    timeout_task: asyncio.Task[None] | None = None


class StartDiagnosisView(discord.ui.View):
    def __init__(self, cog: ValorantPlaystyleCog, user_id: int) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("この診断はあなた用ではありません。", ephemeral=True)
        return False

    @discord.ui.button(label="診断を始める", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog.start_questions(self.user_id)


class AnswerButton(discord.ui.Button):
    def __init__(self, number: int, choice_id: str) -> None:
        super().__init__(label=str(number), style=discord.ButtonStyle.secondary)
        self.choice_id = choice_id

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, QuestionView):
            return
        for item in view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(view=view)
        await view.cog.answer_question(view.user_id, view.question_id, self.choice_id)


class QuestionView(discord.ui.View):
    def __init__(
        self,
        cog: ValorantPlaystyleCog,
        user_id: int,
        question_id: str,
        choice_ids: list[str],
    ) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        self.question_id = question_id
        for number, choice_id in enumerate(choice_ids, start=1):
            self.add_item(AnswerButton(number, choice_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("この診断はあなた用ではありません。", ephemeral=True)
        return False


class ValorantPlaystyleCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        policy = ClassificationPolicy(
            weights={"win": 0.20, "team": 0.35, "improvement": 0.25, "focus": 0.20},
            gachi_minimum=config.valo_playstyle_gachi_min,
            neutral_minimum=config.valo_playstyle_neutral_min,
            gachi_axis_minimums={
                "team": config.valo_playstyle_gachi_team_min,
                "improvement": config.valo_playstyle_gachi_improvement_min,
                "focus": config.valo_playstyle_gachi_focus_min,
            },
        )
        self.core = ValorantPlaystyleService(
            questions_path=QUESTION_PATH,
            classification_policy=policy,
        )
        repository = ValorantPlaystyleResultRepository(config.valo_playstyle_results_path)
        self.results = ValorantPlaystyleResultService(self.core, repository)
        self.timeout_seconds = config.valo_playstyle_timeout_seconds
        self.timeout_channel_id = config.require_id(
            config.valo_playstyle_timeout_channel_id,
            "VALO_PLAYSTYLE_TIMEOUT_CHANNEL_ID",
        )
        self.resend_user_id = config.require_id(
            config.valo_playstyle_resend_user_id,
            "VALO_PLAYSTYLE_RESEND_USER_ID",
        )
        self.sessions: dict[int, DiagnosisSession] = {}

    async def cog_load(self) -> None:
        self.results.repository.load()
        await self.results.reevaluate_all(self.core.question_set.diagnosis_version)

    async def cog_unload(self) -> None:
        for session in self.sessions.values():
            if session.timeout_task is not None:
                session.timeout_task.cancel()
        self.sessions.clear()

    @app_commands.command(name="valo_role", description="指定メンバーへVALORANT診断を送信します")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        if member.bot:
            await interaction.followup.send("Botは診断対象にできません。", ephemeral=True)
            return
        if member.id in self.sessions:
            await interaction.followup.send("このメンバーは現在診断中です。", ephemeral=True)
            return
        session = DiagnosisSession(
            user=member,
            administrator_id=interaction.user.id,
            administrator_name=str(interaction.user),
        )
        self.sessions[member.id] = session
        embed = discord.Embed(
            title="🐶 VALORANTプレイスタイル診断",
            description=INTRO_TEXT,
            color=0xF4A261,
        )
        try:
            session.dm_message = await member.send(
                embed=embed,
                view=StartDiagnosisView(self, member.id),
            )
        except discord.Forbidden:
            self.sessions.pop(member.id, None)
            await interaction.followup.send(
                "DMを送れませんでした。対象ユーザーのDM設定を確認してください。",
                ephemeral=True,
            )
            return
        except Exception:
            self.sessions.pop(member.id, None)
            logger.exception("Failed to send playstyle diagnosis DM")
            await interaction.followup.send("診断DMの送信に失敗しました。", ephemeral=True)
            return
        self._reset_timeout(session)
        await interaction.followup.send(f"{member.mention} に診断を送信しました。", ephemeral=True)

    async def start_questions(self, user_id: int) -> None:
        session = self.sessions.get(user_id)
        if session is None:
            return
        session.question_index = 0
        self._reset_timeout(session)
        await self._show_question(session)

    async def answer_question(self, user_id: int, question_id: str, choice_id: str) -> None:
        session = self.sessions.get(user_id)
        if session is None:
            return
        question = self.core.question_set.questions[session.question_index]
        if question.id != question_id:
            return
        session.answers[question_id] = choice_id
        session.question_index += 1
        self._reset_timeout(session)
        if session.question_index < len(self.core.question_set.questions):
            await self._show_question(session)
            return
        await self._complete(session)

    async def _show_question(self, session: DiagnosisSession) -> None:
        question = self.core.question_set.questions[session.question_index]
        choices = random.sample(list(question.choices), k=len(question.choices))
        lines = [
            f"{NUMBER_EMOJIS[index]} {choice.text}"
            for index, choice in enumerate(choices)
        ]
        embed = discord.Embed(
            title="🐶 VALORANTプレイスタイル診断",
            description=(
                f"**Q{session.question_index + 1} / {len(self.core.question_set.questions)}**\n\n"
                f"{question.text}\n\n" + "\n".join(lines)
            ),
            color=0xF4A261,
        )
        await session.dm_message.edit(
            embed=embed,
            view=QuestionView(
                self,
                session.user.id,
                question.id,
                [choice.id for choice in choices],
            ),
        )

    async def _complete(self, session: DiagnosisSession) -> None:
        classification = self.core.classify_complete(session.answers)
        embed = self._result_embed(classification)
        try:
            await self.results.save_completed(
                user_id=session.user.id,
                answers=session.answers,
                classification=classification,
                diagnosis_version=self.core.question_set.diagnosis_version,
                invoked_by=session.administrator_id,
                invoked_by_name=session.administrator_name,
            )
        except Exception:
            logger.exception("Failed to persist playstyle diagnosis result")
            error_embed = discord.Embed(
                title="🐶 診断結果を保存できませんでした",
                description="診断結果の保存に失敗しました。管理者へ連絡してください。",
                color=0xE76F51,
            )
            await session.dm_message.edit(embed=error_embed, view=None)
        else:
            await session.dm_message.edit(embed=embed, view=None)
        finally:
            self._remove_session(session.user.id)

    def _result_embed(self, classification: PlaystyleClassification) -> discord.Embed:
        title, category_text = CATEGORY_PRESENTATION[classification.category]
        sections = [title, "", category_text, "", "━━━━━━━━━━━━━━", ""]
        for axis in ("win", "team", "improvement", "focus"):
            normalized = classification.score.axes[axis].normalized
            sections.extend(
                [AXIS_LABELS[axis], f"{progress_bar(normalized)} {percentage(normalized)}%", ""]
            )
        receive, give = feedback_lines(
            classification.score.axes["feedback_receive"].score,
            classification.score.axes["feedback_give"].score,
        )
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
        return discord.Embed(title="🐶 診断結果", description="\n".join(sections), color=0xF4A261)

    def _reset_timeout(self, session: DiagnosisSession) -> None:
        session.last_activity = time.monotonic()
        session.timeout_generation += 1
        if session.timeout_task is not None:
            session.timeout_task.cancel()
        generation = session.timeout_generation
        session.timeout_task = asyncio.create_task(
            self._timeout_after(session.user.id, generation)
        )

    async def _timeout_after(self, user_id: int, generation: int) -> None:
        try:
            await asyncio.sleep(self.timeout_seconds)
        except asyncio.CancelledError:
            return
        session = self.sessions.get(user_id)
        if session is None or session.timeout_generation != generation:
            return
        await self._expire(session)

    async def _expire(self, session: DiagnosisSession) -> None:
        timeout_text = self._timeout_duration_text()
        embed = discord.Embed(
            title="🐶 診断が時間切れになりました！",
            description=(
                f"最後の操作から{timeout_text}経過したため、\n"
                "今回の診断を終了しました。\n\n"
                "もう一度診断を受ける場合は、\n"
                f"<@{self.resend_user_id}>から再送してもらってください。"
            ),
            color=0xE76F51,
        )
        try:
            await session.dm_message.edit(embed=embed, view=None)
        except Exception:
            logger.exception("Failed to update timed-out playstyle diagnosis DM")
        channel = self.bot.get_channel(self.timeout_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.timeout_channel_id)
            except Exception:
                logger.exception("Failed to resolve playstyle timeout channel")
        if channel is not None:
            notification = discord.Embed(
                title="🐶 VALORANT診断がタイムアウトしました",
                description=(
                    f"対象：{session.user.mention}\n"
                    f"進捗：{len(session.answers)} / {len(self.core.question_set.questions)}\n"
                    f"送信者：<@{session.administrator_id}>\n\n"
                    f"最後の操作から{timeout_text}経過したため、診断を終了しました。\n\n"
                    f"必要であれば、<@{self.resend_user_id}> から診断を再送してください。"
                ),
                color=0xE76F51,
            )
            try:
                await channel.send(embed=notification)
            except Exception:
                logger.exception("Failed to send playstyle timeout notification")
        self._remove_session(session.user.id)

    def _remove_session(self, user_id: int) -> None:
        session = self.sessions.pop(user_id, None)
        if session is not None and session.timeout_task is not None:
            session.timeout_task.cancel()

    def _timeout_duration_text(self) -> str:
        if self.timeout_seconds % 60 == 0:
            return f"{self.timeout_seconds // 60}分"
        return f"{self.timeout_seconds}秒"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ValorantPlaystyleCog(bot))
