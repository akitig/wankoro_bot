"""Discord command and view boundaries for VALORANT map selection."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import get_config
from services.valomap_service import ValomapService


class ValorantMap(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = get_config()
        self.service = ValomapService(bans_path=config.valomap_bans_path)

    @app_commands.command(
        name="valomap",
        description="VALORANTの全コンペマップを表示します（BAN済みは❌）",
    )
    async def valomap_all(self, interaction: discord.Interaction) -> None:
        listing = await self.service.get_map_listing()
        description = "\n".join(
            f"❌ ~~{name}~~" if banned else f"✅ {name}"
            for name, banned in listing
        )
        embed = discord.Embed(
            title="🎯 VALORANT コンペマップ一覧",
            description=description,
            color=0xFF4655,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="valomappool",
        description="BANされていないVALORANTマップを表示します",
    )
    async def valomap_pool(self, interaction: discord.Interaction) -> None:
        available = await self.service.get_available_maps()
        if not available:
            await interaction.response.send_message(
                "❌ 現在、利用可能なマップはありません。", ephemeral=True
            )
            return
        description = "\n".join(
            f"✅ {map_data['displayName']}" for map_data in available
        )
        embed = discord.Embed(
            title="🎯 現在のVALORANTコンペマッププール（BAN除外）",
            description=description,
            color=0x00BFFF,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="valomapselect",
        description="BANされていないマップからランダムに選びます",
    )
    async def valomap_select(self, interaction: discord.Interaction) -> None:
        selected = await self.service.select_random_map()
        if selected is None:
            await interaction.response.send_message(
                "❌ 利用可能なマップがありません。BANを解除してください。"
            )
            return
        name = selected["displayName"]
        image = selected.get("splash")
        embed = discord.Embed(
            title="🎲 ランダム選出マップ",
            description=f"**{name}** が選ばれました！",
            color=0xFF4655,
        )
        if image:
            embed.set_image(url=image)
        await interaction.response.send_message(embed=embed)

    class MapBanDropdown(discord.ui.Select):
        def __init__(self, service: ValomapService, maps: list[dict[str, Any]]) -> None:
            self.service = service
            options = [
                discord.SelectOption(
                    label=map_data["displayName"],
                    description="BANするマップを選択",
                )
                for map_data in maps
                if not service.is_banned(map_data["displayName"])
            ]
            super().__init__(
                placeholder="BANするマップを選んでください",
                options=options,
                min_values=1,
                max_values=1,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            selected = self.values[0]
            self.service.ban_map(selected)
            await interaction.response.edit_message(
                content=f"🚫 `{selected}` をBANしました。",
                view=None,
            )

    class MapBanView(discord.ui.View):
        def __init__(self, service: ValomapService, maps: list[dict[str, Any]]) -> None:
            super().__init__(timeout=60)
            self.add_item(ValorantMap.MapBanDropdown(service, maps))

    @app_commands.command(
        name="valomapban",
        description="ドロップダウンでBANするマップを選びます",
    )
    async def valomap_ban_ui(self, interaction: discord.Interaction) -> None:
        available = await self.service.get_available_maps()
        if not available:
            await interaction.response.send_message(
                "❌ すべてのマップがBAN済みです。", ephemeral=True
            )
            return
        view = ValorantMap.MapBanView(self.service, available)
        await interaction.response.send_message(
            "BANするマップを選んでください：", view=view, ephemeral=True
        )

    @app_commands.command(name="valomapclear", description="すべてのBANを解除します")
    async def valomap_clear(self, interaction: discord.Interaction) -> None:
        self.service.clear_bans()
        await interaction.response.send_message("✅ すべてのマップBANを解除しました。")

    @app_commands.command(
        name="valocustom",
        description="VALORANTマップ関連コマンド一覧を表示します",
    )
    async def valomap_help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🎮 VALORANT マップ管理コマンド一覧",
            description="わんころBot🐶 のVALORANT用マップ管理コマンドです。",
            color=0xFFD700,
        )
        commands_info = [
            ("/valomap", "全マップ一覧を表示（BAN済みは❌打消し線付き）"),
            ("/valomappool", "BANされていないマップのみを表示"),
            ("/valomapselect", "BANされていないマップからランダムに選出"),
            ("/valomapban", "ドロップダウンUIでBAN設定"),
            ("/valomapclear", "全てのBANを解除"),
            ("/valocustom", "このコマンド一覧を表示します"),
        ]
        for name, description in commands_info:
            embed.add_field(name=name, value=description, inline=False)
        embed.set_footer(text="Powered by わんころBot🐶")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.service.initialize()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ValorantMap(bot))
    logging.getLogger(__name__).info("VALORANT map Cog initialized")
