"""Discord interaction boundary for the VALORANT role diagnostic."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from services.valocheck_service import (
    ValocheckService,
)

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


class ChoiceButton(discord.ui.Button):
    def __init__(self, label: str, score: int, row: int = 0):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=row,
        )
        self.score = int(score)
        self.choice_label = label

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, QuizView):
            return
        await view.disable_all(interaction)
        message = await view.service.answer(
            interaction.user,
            self.score,
            self.choice_label,
        )
        if message is not None:
            await interaction.followup.send(message, ephemeral=True)


class QuizView(discord.ui.View):
    def __init__(
        self,
        service: ValocheckService,
        user_id: int,
        timeout_sec: int,
    ):
        super().__init__(timeout=timeout_sec)
        self.service = service
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "このクイズはあなた用ではありません。",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        await self.service.expire_session(
            self.user_id,
            origin="QuizView.on_timeout",
        )

    def set_buttons(self, choices: list[tuple[str, int]]) -> None:
        self.clear_items()
        for index, (label, score) in enumerate(choices):
            self.add_item(
                ChoiceButton(
                    label=label,
                    score=score,
                    row=index // 2,
                )
            )

    async def disable_all(self, interaction: discord.Interaction) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            logger.debug(
                "Failed to disable quiz controls through interaction response",
                exc_info=True,
            )
            try:
                await interaction.edit_original_response(view=self)
            except Exception:
                logger.exception("Failed to disable quiz controls")


class StartView(discord.ui.View):
    def __init__(
        self,
        service: ValocheckService,
        user_id: int,
        timeout_sec: int,
    ):
        super().__init__(timeout=timeout_sec)
        self.service = service
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この操作はあなた用ではありません。",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        await self.service.expire_session(
            self.user_id,
            origin="StartView.on_timeout",
        )

    @discord.ui.button(label="開始", style=discord.ButtonStyle.primary)
    async def start(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(view=self)
        await self.service.start_questions(interaction.user)


class ValoCheckCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        config = get_config()
        self.service = ValocheckService(
            bot,
            guild_id=config.guild_id,
            role_enjoy_id=config.require_id(
                config.valo_role_enjoy_id,
                "ROLE_ENJOY_ID",
            ),
            role_gachi_id=config.require_id(
                config.valo_role_gachi_id,
                "ROLE_GACHI_ID",
            ),
            log_channel_id=config.valo_role_log_channel_id,
            admin_dm_user_id=config.dm_forward_user_id,
            view_timeout_sec=config.valo_check_view_timeout_sec,
            thresh_enjoy_only=config.valo_check_thresh_enjoy_only,
            thresh_gachi_only=config.valo_check_thresh_gachi_only,
            label_enjoy=config.valo_check_label_enjoy,
            label_gachi=config.valo_check_label_gachi,
            label_both=config.valo_check_label_both,
            completion_path=config.valo_check_data_path,
            questions_path=config.valo_check_questions_path,
            intro_path=config.valo_check_intro_path,
            start_view_factory=lambda user_id, timeout: StartView(
                self.service,
                user_id,
                timeout,
            ),
            quiz_view_factory=lambda user_id, timeout: QuizView(
                self.service,
                user_id,
                timeout,
            ),
        )

    @app_commands.command(
        name="valo_role",
        description="管理者が指定したメンバーにDMで診断を送ります",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        force: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        message = await self.service.diagnose(
            member,
            invoked_by=interaction.user,
            force=force,
        )
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(
        name="valo_role_reload",
        description="valo_questions.json を再読み込みします（管理者のみ）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role_reload(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        message = await self.service.reload(interaction.user)
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(
        name="valo_role_cancel",
        description="指定メンバーの診断を中断します（判定なし・ロール付与なし）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role_cancel(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "admin cancel",
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        message = await self.service.cancel(
            member,
            reason,
            interaction.user,
        )
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(
        name="valo_role_cancel_all",
        description="進行中の全診断を中断します（判定なし・ロール付与なし）",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def valo_role_cancel_all(
        self,
        interaction: discord.Interaction,
        reason: str = "admin cancel all",
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        message = await self.service.cancel_all(reason, interaction.user)
        await interaction.followup.send(message, ephemeral=True)

    async def _handle_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
        command_name: str,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。",
                ephemeral=True,
            )
            return
        await self.service.notify_admin(
            f"❌ VALO診断: {command_name} コマンドエラー",
            f"InvokedBy: {interaction.user}\n"
            f"Error: {type(error).__name__}: {error}",
        )
        raise error

    @valo_role.error
    async def valo_role_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await self._handle_command_error(
            interaction,
            error,
            "valo_role",
        )

    @valo_role_reload.error
    async def valo_role_reload_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await self._handle_command_error(
            interaction,
            error,
            "valo_role_reload",
        )

    @valo_role_cancel.error
    async def valo_role_cancel_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await self._handle_command_error(
            interaction,
            error,
            "valo_role_cancel",
        )

    @valo_role_cancel_all.error
    async def valo_role_cancel_all_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await self._handle_command_error(
            interaction,
            error,
            "valo_role_cancel_all",
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ValoCheckCog(bot))
