"""Discord event and persistent-view boundary for the BUMP panel."""

from __future__ import annotations

import discord
from discord.ext import commands

from config import get_config
from repositories.bump_panel_repository import BumpPanelRepository
from services.bump_panel_service import BumpPanelService


class BumpPanelView(discord.ui.View):
    def __init__(self, service: BumpPanelService, *, available: bool) -> None:
        super().__init__(timeout=None)
        self._service = service
        button = self.open_command
        button.label = "BUMPする" if available else "BUMP待機中"
        button.style = (
            discord.ButtonStyle.success
            if available
            else discord.ButtonStyle.secondary
        )
        button.disabled = not available

    @discord.ui.button(
        label="BUMPする",
        style=discord.ButtonStyle.success,
        custom_id="bump_panel:open_command",
    )
    async def open_command(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._service.send_command_guide(interaction)


class BumpPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        channel_id = config.require_id(config.bump_channel_id, "BUMP_CHANNEL_ID")
        disboard_bot_id = config.require_id(
            config.disboard_bot_id,
            "DISBOARD_BOT_ID",
        )
        repository = BumpPanelRepository(config.bump_panel_state_path)
        self.service = BumpPanelService(
            bot=bot,
            repository=repository,
            channel_id=channel_id,
            disboard_bot_id=disboard_bot_id,
            bump_command_id=config.disboard_bump_command_id,
            cooldown_seconds=config.bump_cooldown_seconds,
            view_factory=lambda available: BumpPanelView(
                self.service,
                available=available,
            ),
        )

    async def cog_load(self) -> None:
        self.bot.add_view(BumpPanelView(self.service, available=True))
        await self.service.initialize()

    async def cog_unload(self) -> None:
        await self.service.shutdown()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.service.ensure_panel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self.service.handle_message(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BumpPanelCog(bot))
