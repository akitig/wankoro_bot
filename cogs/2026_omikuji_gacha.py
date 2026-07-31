"""Discord command and component boundaries for the Omikuji feature."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from services.omikuji_service import OmikujiService


class OmikujiView(discord.ui.View):
    def __init__(self, cog: OmikujiGachaCog) -> None:
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.button(
        label="🎴 おみくじを引く（50pt）",
        style=discord.ButtonStyle.primary,
        custom_id="omikuji:draw_2026",
    )
    async def draw_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._cog.handle_draw(interaction)

    @discord.ui.button(
        label="💰 ポイント確認",
        style=discord.ButtonStyle.secondary,
        custom_id="omikuji:points_2026",
    )
    async def points_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._cog.handle_points(interaction)


class OmikujiGachaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        self.service = OmikujiService(
            bot,
            points_path=str(config.omikuji_points_path),
            rest_vc_id=config.omikuji_rest_vc_id,
            resetter_user_id=config.omikuji_resetter_user_id,
            panel_channel_id=config.omikuji_panel_channel_id,
        )
        self._view = OmikujiView(self)

    async def cog_load(self) -> None:
        await self.service.load()
        self.bot.add_view(self._view)
        self.service.start()

    async def cog_unload(self) -> None:
        self.service.stop()

    async def handle_draw(self, interaction: discord.Interaction) -> None:
        await self.service.handle_draw(interaction)

    async def handle_points(self, interaction: discord.Interaction) -> None:
        await self.service.handle_points(interaction)

    @app_commands.command(
        name="omikuji_panel",
        description="初春おみくじガチャのパネルを指定チャンネルに投稿します",
    )
    async def omikuji_panel(self, interaction: discord.Interaction) -> None:
        await self.service.post_panel(interaction, self._view)

    @app_commands.command(
        name="omikuji_reset_points",
        description="全員のポイントを初期値（500pt）にリセットします（指定ユーザーのみ）",
    )
    async def omikuji_reset_points(self, interaction: discord.Interaction) -> None:
        await self.service.reset_points(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OmikujiGachaCog(bot))
