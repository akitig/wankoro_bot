"""Discord command and component boundaries for the Joya bell feature."""

from __future__ import annotations

from collections.abc import Callable

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from services.joya_service import JoyaService


def _only_user(user_id: int) -> Callable[[discord.Interaction], bool]:
    def _pred(interaction: discord.Interaction) -> bool:
        return bool(interaction.user and interaction.user.id == user_id)

    return _pred


class JoyaView(discord.ui.View):
    def __init__(self, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    @discord.ui.button(
        label="🔔 除夜の鐘を鳴らす",
        style=discord.ButtonStyle.primary,
        custom_id="joya:ring",
    )
    async def ring(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        cog = interaction.client.get_cog("JoyaGacha")
        if not isinstance(cog, JoyaGacha):
            await interaction.response.send_message(
                "Cogが見つからない。管理者に連絡して。",
                ephemeral=True,
            )
            return
        await cog.service.handle_joya(interaction)


class JoyaGacha(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        self.service = JoyaService(
            bot,
            data_path=str(config.joya_data_path),
            min_sec=config.joya_min_sec,
            max_sec=config.joya_max_sec,
            winner_role_id=config.joya_winner_role_id,
            channel_id=config.joya_channel_id,
            view_factory=lambda disabled=False: JoyaView(disabled=disabled),
        )

    async def cog_load(self) -> None:
        self.bot.add_view(JoyaView())

    @app_commands.command(name="joya", description="除夜の鐘を1回鳴らす")
    async def joya(self, interaction: discord.Interaction) -> None:
        await self.service.handle_joya(interaction)

    @app_commands.command(
        name="joya_panel",
        description="除夜の鐘ボタンを.env指定チャンネルに投稿",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def joya_panel(self, interaction: discord.Interaction) -> None:
        await self.service.post_panel(interaction)

    @app_commands.command(
        name="joya_status",
        description="現在の回数と設定を表示",
    )
    async def joya_status(self, interaction: discord.Interaction) -> None:
        await self.service.send_status(interaction)

    @app_commands.command(
        name="joya_config",
        description="クールダウン最短/最長を設定（分）",
    )
    @app_commands.check(_only_user(746347536100360283))
    async def joya_config(
        self,
        interaction: discord.Interaction,
        min_minutes: app_commands.Range[int, 1, 120],
        max_minutes: app_commands.Range[int, 1, 120],
    ) -> None:
        await self.service.configure(interaction, min_minutes, max_minutes)

    @app_commands.command(
        name="joya_config_reset",
        description="クールダウン設定を.envの値に戻す",
    )
    @app_commands.check(_only_user(746347536100360283))
    async def joya_config_reset(self, interaction: discord.Interaction) -> None:
        await self.service.reset_config(interaction)

    @app_commands.command(
        name="joya_reset_all",
        description="除夜の鐘の状態を完全リセット（回数/勝者/CD/パネル情報）",
    )
    @app_commands.check(_only_user(746347536100360283))
    async def joya_reset_all(self, interaction: discord.Interaction) -> None:
        await self.service.reset_all(interaction)

    @joya_panel.error
    @joya_config.error
    @joya_config_reset.error
    @joya_reset_all.error
    async def _cmd_err(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "実行できない（許可ユーザーのみ）。",
                ephemeral=True,
            )
            return
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "権限が足りない。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "エラーが出た。ログを見てくれ。",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JoyaGacha(bot))
