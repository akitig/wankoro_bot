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
    CATEGORY_PRESENTATION,
    answer_log_pages,
    classification_result_description,
    stored_result_description,
)
from services.valorant_playstyle_result_service import (
    ValorantPlaystyleResultService,
)
from services.valorant_playstyle_service import (
    ClassificationPolicy,
    PlaystyleCategory,
    PlaystyleClassification,
    ValorantPlaystyleService,
)

logger = logging.getLogger(__name__)
QUESTION_PATH = Path("data/valorant_playstyle_questions.json")
NUMBER_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")
MAX_DISCORD_SNOWFLAKE = (1 << 64) - 1

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
        self.diagnosis_guild_id = config.guild_id
        self.log_guild_id = config.require_id(
            config.valo_playstyle_log_guild_id,
            "VALO_PLAYSTYLE_LOG_GUILD_ID",
        )
        self.log_channel_id = config.require_id(
            config.valo_playstyle_log_channel_id,
            "VALO_PLAYSTYLE_LOG_CHANNEL_ID",
        )
        self.resend_user_id = config.require_id(
            config.valo_playstyle_resend_user_id,
            "VALO_PLAYSTYLE_RESEND_USER_ID",
        )
        self.sessions: dict[int, DiagnosisSession] = {}
        self._startup_validation_done = False

    async def cog_load(self) -> None:
        self.results.repository.load()
        await self.results.reevaluate_all(self.core.question_set.diagnosis_version)

    async def cog_unload(self) -> None:
        for session in self.sessions.values():
            if session.timeout_task is not None:
                session.timeout_task.cancel()
        self.sessions.clear()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._startup_validation_done:
            return
        self._startup_validation_done = True
        self._validate_cross_guild_setup()

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
            logger.warning(
                "Playstyle diagnosis DM was forbidden: target=%s requester=%s",
                member.id,
                interaction.user.id,
            )
            await interaction.followup.send(
                "DMを送れませんでした。対象ユーザーのDM設定を確認してください。",
                ephemeral=True,
            )
            await self._send_dm_failure_audit(member, interaction.user)
            return
        except Exception:
            self.sessions.pop(member.id, None)
            logger.exception(
                "Failed to send playstyle diagnosis DM: target=%s requester=%s",
                member.id,
                interaction.user.id,
            )
            await interaction.followup.send("診断DMの送信に失敗しました。", ephemeral=True)
            await self._send_dm_failure_audit(member, interaction.user)
            return
        self._reset_timeout(session)
        await interaction.followup.send(f"{member.mention} に診断を送信しました。", ephemeral=True)
        await self._send_audit(
            discord.Embed(
                title="🐶 VALORANT診断を送信しました",
                description=(
                    f"{self._audit_identity('対象', member)}\n\n"
                    f"{self._audit_identity('送信者', interaction.user)}\n\n"
                    "状態：診断開始待ち"
                ),
                color=0xF4A261,
            ),
            context="diagnosis start",
        )

    async def show_answer_log(
        self,
        interaction: discord.Interaction,
        *,
        user: discord.Member | None,
        user_id: str | None,
    ) -> None:
        if interaction.guild_id != self.log_guild_id:
            await interaction.response.send_message(
                "🐶 このコマンドはVALORANT診断の管理サーバーでのみ使用できます。",
                ephemeral=True,
            )
            return
        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions is None or not permissions.administrator:
            await interaction.response.send_message(
                "🐶 このコマンドは管理者のみ使用できます。",
                ephemeral=True,
            )
            return
        if interaction.channel_id != self.log_channel_id:
            await interaction.response.send_message(
                "🐶 このコマンドはVALORANT診断ログチャンネルでのみ使用できます。",
                ephemeral=True,
            )
            return
        if user is not None and user_id is not None:
            await interaction.response.send_message(
                "🐶 user と user_id はどちらか一方だけ指定してください。",
                ephemeral=True,
            )
            return
        if user is None and user_id is None:
            await interaction.response.send_message(
                "🐶 user または user_id を指定してください。",
                ephemeral=True,
            )
            return
        target_id = user.id if user is not None else self._parse_user_id(user_id)
        if target_id is None:
            await interaction.response.send_message(
                "🐶 User IDが正しくありません。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        result = self.results.repository.get_result(target_id)
        if result is None:
            await interaction.followup.send(
                "🐶 このユーザーのVALORANT診断結果はまだありません。",
                ephemeral=True,
            )
            return
        current_version = self.core.question_set.diagnosis_version
        if result["diagnosis_version"] != current_version:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🐶 VALORANT診断 回答ログ",
                    description=(
                        "⚠️ この診断結果は現在と異なる質問バージョンで記録されています。\n"
                        "回答内容を安全に復元できないため、詳細表示できません。\n\n"
                        f"診断Version：{result['diagnosis_version']}\n"
                        f"現在Version：{current_version}"
                    ),
                    color=0xE9C46A,
                ),
                ephemeral=True,
            )
            return
        try:
            pages = answer_log_pages(self.core.question_set, result["answers"])
        except ValueError:
            logger.exception(
                "Failed to restore playstyle answers: requester=%s target=%s",
                interaction.user.id,
                target_id,
            )
            await interaction.followup.send(
                "⚠️ 保存された回答内容を安全に復元できませんでした。",
                ephemeral=True,
            )
            return
        target_text = await self._resolve_user_display(target_id, fallback=user)
        invoked_by = result.get("invoked_by")
        invoked_by_text = (
            await self._resolve_user_display(
                invoked_by,
                fallback_name=result.get("invoked_by_name"),
            )
            if invoked_by is not None
            else "不明"
        )
        category_title = CATEGORY_PRESENTATION[PlaystyleCategory(result["category"])][0]
        summary = discord.Embed(
            title="🐶 VALORANT診断 回答ログ",
            description=(
                f"対象：{target_text}\n"
                f"対象User ID：{target_id}\n"
                f"診断結果：{category_title}\n"
                f"診断日時：{result['completed_at']}\n"
                f"最終評価日時：{result['evaluated_at']}\n"
                f"送信者：{invoked_by_text}\n"
                f"送信者ID：{invoked_by if invoked_by is not None else '不明'}\n\n"
                f"{stored_result_description(result)}"
            ),
            color=0xF4A261,
        )
        await interaction.followup.send(embed=summary, ephemeral=True)
        total_pages = len(pages)
        for index, page in enumerate(pages, start=1):
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"🐶 VALORANT診断 回答ログ {index}/{total_pages}",
                    description=page,
                    color=0xF4A261,
                ),
                ephemeral=True,
            )
        logger.info(
            "Playstyle answer log viewed: requester=%s target=%s",
            interaction.user.id,
            target_id,
        )

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
            logger.exception(
                "Failed to persist playstyle diagnosis result: target=%s requester=%s",
                session.user.id,
                session.administrator_id,
            )
            error_embed = discord.Embed(
                title="🐶 診断結果を保存できませんでした",
                description="診断結果の保存に失敗しました。管理者へ連絡してください。",
                color=0xE76F51,
            )
            await self._send_audit(
                discord.Embed(
                    title="⚠️ VALORANT診断結果の保存に失敗しました",
                    description=(
                        f"{self._audit_identity('対象', session.user)}\n\n"
                        f"{self._audit_identity('送信者', user_id=session.administrator_id, fallback_name=session.administrator_name)}"
                    ),
                    color=0xE76F51,
                ),
                context="result persistence failure",
            )
            await session.dm_message.edit(embed=error_embed, view=None)
        else:
            await session.dm_message.edit(embed=embed, view=None)
            await self._send_audit(
                discord.Embed(
                    title="🐶 VALORANT診断が完了しました",
                    description=(
                        f"{self._audit_identity('対象', session.user)}\n\n"
                        f"{self._audit_identity('送信者', user_id=session.administrator_id, fallback_name=session.administrator_name)}\n\n"
                        "🐶 診断結果\n\n"
                        f"{classification_result_description(classification, include_weighted_score=True)}"
                    ),
                    color=0xF4A261,
                ),
                context="diagnosis completion",
            )
        finally:
            self._remove_session(session.user.id)

    def _result_embed(self, classification: PlaystyleClassification) -> discord.Embed:
        return discord.Embed(
            title="🐶 診断結果",
            description=classification_result_description(classification),
            color=0xF4A261,
        )

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
        await self._send_audit(
            discord.Embed(
                title="🐶 VALORANT診断がタイムアウトしました",
                description=(
                    f"{self._audit_identity('対象', session.user)}\n"
                    f"進捗：{len(session.answers)} / {len(self.core.question_set.questions)}\n"
                    f"{self._audit_identity('送信者', user_id=session.administrator_id, fallback_name=session.administrator_name)}\n\n"
                    f"最後の操作から{timeout_text}経過したため、診断を終了しました。\n\n"
                    f"必要であれば、<@{self.resend_user_id}> から診断を再送してください。"
                ),
                color=0xE76F51,
            ),
            context="diagnosis timeout",
        )
        self._remove_session(session.user.id)

    async def _send_dm_failure_audit(self, member: Any, administrator: Any) -> None:
        await self._send_audit(
            discord.Embed(
                title="⚠️ VALORANT診断の送信に失敗しました",
                description=(
                    f"{self._audit_identity('対象', member)}\n\n"
                    f"{self._audit_identity('送信者', administrator)}\n"
                    "理由：DMを送信できませんでした"
                ),
                color=0xE76F51,
            ),
            context="diagnosis DM failure",
        )

    async def _send_audit(self, embed: discord.Embed, *, context: str) -> bool:
        guild = self.bot.get_guild(self.log_guild_id)
        if guild is None:
            logger.error(
                "VALORANT playstyle log guild is unavailable: guild_id=%s context=%s",
                self.log_guild_id,
                context,
            )
            return False
        channel = guild.get_channel(self.log_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(self.log_channel_id)
            except Exception:
                logger.exception("Failed to resolve playstyle log channel: %s", context)
                return False
        channel_guild_id = getattr(getattr(channel, "guild", None), "id", None)
        if channel_guild_id != self.log_guild_id:
            logger.error(
                "VALORANT playstyle log channel guild mismatch: expected=%s actual=%s channel_id=%s context=%s",
                self.log_guild_id,
                channel_guild_id,
                self.log_channel_id,
                context,
            )
            return False
        try:
            await channel.send(embed=embed)
        except Exception:
            logger.exception("Failed to send playstyle audit log: %s", context)
            return False
        return True

    def _validate_cross_guild_setup(self) -> None:
        diagnosis_guild = self.bot.get_guild(self.diagnosis_guild_id)
        if diagnosis_guild is None:
            logger.error(
                "VALORANT diagnosis guild is unavailable: guild_id=%s",
                self.diagnosis_guild_id,
            )
        log_guild = self.bot.get_guild(self.log_guild_id)
        if log_guild is None:
            logger.error(
                "VALORANT playstyle log guild is unavailable: guild_id=%s",
                self.log_guild_id,
            )
            return
        channel = log_guild.get_channel(self.log_channel_id)
        if channel is None:
            logger.error(
                "VALORANT playstyle log channel is unavailable: guild_id=%s channel_id=%s",
                self.log_guild_id,
                self.log_channel_id,
            )
            return
        channel_guild_id = getattr(getattr(channel, "guild", None), "id", None)
        if channel_guild_id != self.log_guild_id:
            logger.error(
                "VALORANT playstyle log channel guild mismatch: expected=%s actual=%s channel_id=%s",
                self.log_guild_id,
                channel_guild_id,
                self.log_channel_id,
            )
            return
        bot_member = getattr(log_guild, "me", None)
        if bot_member is None:
            logger.error(
                "Bot member is unavailable in VALORANT playstyle log guild: guild_id=%s",
                self.log_guild_id,
            )
            return
        permissions = channel.permissions_for(bot_member)
        missing = [
            name
            for name in ("view_channel", "send_messages", "embed_links")
            if not getattr(permissions, name, False)
        ]
        if missing:
            logger.error(
                "VALORANT playstyle log channel permissions are missing: guild_id=%s channel_id=%s permissions=%s",
                self.log_guild_id,
                self.log_channel_id,
                ",".join(missing),
            )
            return
        logger.info(
            "VALORANT playstyle cross-guild setup validated: diagnosis_guild_id=%s log_guild_id=%s log_channel_id=%s",
            self.diagnosis_guild_id,
            self.log_guild_id,
            self.log_channel_id,
        )

    @staticmethod
    def _parse_user_id(value: str | None) -> int | None:
        if value is None or not value or not value.isascii() or not value.isdigit():
            return None
        parsed = int(value)
        if parsed <= 0 or parsed > MAX_DISCORD_SNOWFLAKE:
            return None
        return parsed

    async def _resolve_user_display(
        self,
        user_id: int,
        *,
        fallback: Any | None = None,
        fallback_name: str | None = None,
    ) -> str:
        diagnosis_guild = self.bot.get_guild(self.diagnosis_guild_id)
        user = diagnosis_guild.get_member(user_id) if diagnosis_guild is not None else None
        if user is None:
            user = self.bot.get_user(user_id)
        if user is None and fallback is not None and fallback.id == user_id:
            user = fallback
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                logger.warning(
                    "Failed to resolve Discord user display: user_id=%s",
                    user_id,
                    exc_info=True,
                )
        if user is not None:
            name = getattr(user, "display_name", None) or getattr(user, "name", None)
            mention = getattr(user, "mention", f"<@{user_id}>")
            return f"{name or user_id} ({mention})"
        if fallback_name:
            return f"{fallback_name} (<@{user_id}>)"
        return str(user_id)

    @staticmethod
    def _audit_identity(
        label: str,
        user: Any | None = None,
        *,
        user_id: int | None = None,
        fallback_name: str | None = None,
    ) -> str:
        resolved_id = user.id if user is not None else user_id
        if resolved_id is None:
            raise ValueError("audit identity requires a user ID")
        name = (
            getattr(user, "display_name", None)
            or getattr(user, "name", None)
            or fallback_name
            or str(resolved_id)
        )
        mention = getattr(user, "mention", f"<@{resolved_id}>")
        id_label = "対象User ID" if label == "対象" else f"{label}ID"
        return f"{label}：{name} ({mention})\n{id_label}：{resolved_id}"

    def _remove_session(self, user_id: int) -> None:
        session = self.sessions.pop(user_id, None)
        if session is not None and session.timeout_task is not None:
            session.timeout_task.cancel()

    def _timeout_duration_text(self) -> str:
        if self.timeout_seconds % 60 == 0:
            return f"{self.timeout_seconds // 60}分"
        return f"{self.timeout_seconds}秒"


class ValorantPlaystyleLogCog(commands.Cog):
    """Management-Guild-only access to persisted diagnosis answers."""

    def __init__(self, diagnosis: ValorantPlaystyleCog) -> None:
        self.diagnosis = diagnosis

    @app_commands.command(
        name="valo_role_log",
        description="指定ユーザーの最新VALORANT診断回答を確認します",
    )
    @app_commands.describe(
        user="管理サーバーに参加している対象ユーザー",
        user_id="対象ユーザーのDiscord User ID（数字）",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role_log(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
        user_id: str | None = None,
    ) -> None:
        await self.diagnosis.show_answer_log(
            interaction,
            user=user,
            user_id=user_id,
        )


async def setup(bot: commands.Bot) -> None:
    diagnosis = ValorantPlaystyleCog(bot)
    await bot.add_cog(diagnosis)
    await bot.add_cog(
        ValorantPlaystyleLogCog(diagnosis),
        guild=discord.Object(id=diagnosis.log_guild_id),
    )
