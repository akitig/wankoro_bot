"""Discord command, view, and event boundaries for the Xmas gacha feature."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from services.xmas_service import XmasService


class t_xmas_gacha_result_view(discord.ui.View):
    def __init__(self, cog: t_xmas_gacha) -> None:
        super().__init__(timeout=300)
        self._cog = cog

    @discord.ui.button(
        label="↩️ 名前を戻す",
        style=discord.ButtonStyle.secondary,
        custom_id="xmas_gacha:revert",
    )
    async def revert(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._cog.service.revert(interaction)


class t_xmas_gacha_view(discord.ui.View):
    def __init__(self, cog: t_xmas_gacha) -> None:
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.button(
        label="🎁 ガチャを引く",
        style=discord.ButtonStyle.success,
        custom_id="xmas_gacha:pull",
    )
    async def pull(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._cog.service.pull(interaction)


class t_xmas_gacha(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        self.service = XmasService(
            bot,
            csv_path=config.xmas_gacha_csv_path,
            state_path=config.xmas_gacha_state_path,
            channel_id=config.xmas_gacha_channel_id,
            cutoff=config.xmas_gacha_cutoff,
            panel_view_factory=lambda: t_xmas_gacha_view(self),
            result_view_factory=lambda: t_xmas_gacha_result_view(self),
        )

    async def cog_load(self) -> None:
        self.bot.add_view(t_xmas_gacha_view(self))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.service.ensure_panel()

    @app_commands.command(
        name="xmas_gacha_panel",
        description="クリスマスガチャのパネルを送信（手動）",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def xmas_gacha_panel(self, interaction: discord.Interaction) -> None:
        await self.service.send_panel(interaction)

    @app_commands.command(
        name="xmas_gacha_revert_all",
        description="ガチャで変わった名前を、可能な限り全員戻す",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def xmas_gacha_revert_all(self, interaction: discord.Interaction) -> None:
        await self.service.revert_all(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(t_xmas_gacha(bot))
