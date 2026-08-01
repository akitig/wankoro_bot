"""Discord UI and administrator command boundary for availability polls."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from repositories.availability_poll_repository import AvailabilityPollRepository
from services.availability_poll_service import AvailabilityPollService


class AvailabilityPollView(discord.ui.View):
    def __init__(
        self,
        service: AvailabilityPollService,
        *,
        poll_id: str | None,
        disabled: bool,
    ) -> None:
        super().__init__(timeout=None)
        self._service = service
        self._poll_id = poll_id
        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    def _interaction_poll_id(self, interaction: discord.Interaction) -> str | None:
        return self._poll_id or self._service.poll_id_from_message(interaction.message)

    @discord.ui.button(
        label="🎯 VALORANT",
        style=discord.ButtonStyle.primary,
        custom_id="availability_poll:valorant",
    )
    async def valorant(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._service.handle_answer(
            interaction,
            "valorant",
            self._interaction_poll_id(interaction),
        )

    @discord.ui.button(
        label="🎮 その他ゲーム",
        style=discord.ButtonStyle.primary,
        custom_id="availability_poll:other_game",
    )
    async def other_game(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._service.handle_answer(
            interaction,
            "other_game",
            self._interaction_poll_id(interaction),
        )

    @discord.ui.button(
        label="🗣️ 作業VC",
        style=discord.ButtonStyle.primary,
        custom_id="availability_poll:work_vc",
    )
    async def work_vc(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._service.handle_answer(
            interaction,
            "work_vc",
            self._interaction_poll_id(interaction),
        )

    @discord.ui.button(
        label="✖ 取り消す",
        style=discord.ButtonStyle.secondary,
        custom_id="availability_poll:cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._service.handle_answer(
            interaction,
            None,
            self._interaction_poll_id(interaction),
        )


class AvailabilityPollCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        channel_id = config.require_id(
            config.availability_poll_channel_id,
            "AVAILABILITY_POLL_CHANNEL_ID",
        )
        audit_guild_id = config.require_id(
            config.availability_poll_audit_guild_id,
            "AVAILABILITY_POLL_AUDIT_GUILD_ID",
        )
        audit_channel_id = config.require_id(
            config.availability_poll_audit_channel_id,
            "AVAILABILITY_POLL_AUDIT_CHANNEL_ID",
        )
        repository = AvailabilityPollRepository(config.availability_poll_state_path)
        self.service = AvailabilityPollService(
            bot=bot,
            repository=repository,
            channel_id=channel_id,
            timezone_name=config.availability_poll_timezone,
            weekday_windows=config.availability_poll_weekday_windows,
            holiday_windows=config.availability_poll_holiday_windows,
            audit_guild_id=audit_guild_id,
            audit_channel_id=audit_channel_id,
            view_factory=lambda poll_id, disabled: AvailabilityPollView(
                self.service,
                poll_id=poll_id,
                disabled=disabled,
            ),
        )

    async def cog_load(self) -> None:
        self.bot.add_view(
            AvailabilityPollView(self.service, poll_id=None, disabled=False)
        )
        await self.service.initialize()

    async def cog_unload(self) -> None:
        await self.service.shutdown()

    @app_commands.command(
        name="availability_poll_skip_next",
        description="次の「いまひま？」定期投稿だけをスキップします",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def availability_poll_skip_next(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.service.skip_next(interaction)

    @app_commands.command(
        name="availability_poll_stop",
        description="「いまひま？」の定期投稿を停止します",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def availability_poll_stop(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.service.stop(interaction)

    @app_commands.command(
        name="availability_poll_resume",
        description="停止中の「いまひま？」定期投稿を再開します",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def availability_poll_resume(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.service.resume(interaction)

    async def _command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "この操作は管理者だけが実行できます。",
                ephemeral=True,
            )
            return
        raise error

    @availability_poll_skip_next.error
    async def skip_next_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await self._command_error(interaction, error)

    @availability_poll_stop.error
    async def stop_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await self._command_error(interaction, error)

    @availability_poll_resume.error
    async def resume_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await self._command_error(interaction, error)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AvailabilityPollCog(bot))
